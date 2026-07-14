/**
 * DatabaseManagerView — inventory-first GUI + legacy SQLite tables.
 */
(function (global) {
  "use strict";

  var state = {
    apiOrigin: "",
    headers: {},
    botId: "",
    tables: [],
    activeTable: "inventory_items",
    tableMeta: null,
    rows: [],
    selectedIds: {},
    editingRowId: null,
    editingInventoryId: null,
    importWizard: { filePath: null, preview: null },
  };

  function getApiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
  }

  function authHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json", Accept: "application/json" };
  }

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showDbToast(message, kind) {
    if (!message) return;
    var existing = document.getElementById("db-toast");
    if (existing) existing.remove();
    var toast = document.createElement("div");
    toast.id = "db-toast";
    var isError = kind === "error";
    var isSuccess = kind === "success";
    toast.className =
      "db-toast" +
      (isError ? " db-toast-error" : isSuccess ? " db-toast-success" : "");
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<span class="db-toast-icon" aria-hidden="true">' +
      (isError ? "✕" : "✓") +
      "</span><span class=\"db-toast-text\"></span>";
    toast.querySelector(".db-toast-text").textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.classList.add("visible");
      });
    });
    setTimeout(function () {
      toast.classList.remove("visible");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 420);
    }, isError ? 3200 : 2600);
  }

  function setStatus(message, kind) {
    if (!message) return;
    if (kind === "loading") return;
    showDbToast(message, kind === "success" ? "success" : "error");
  }

  function selectedBotId() {
    var sel = el("db-bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function isInventoryView() {
    return state.activeTable === "inventory_items";
  }

  function activeTableMeta() {
    return state.tables.find(function (t) { return t.name === state.activeTable; }) || null;
  }

  function isBotGlobalsView() {
    return state.activeTable === "bot_globals";
  }

  function isCustomTableView() {
    var meta = activeTableMeta();
    return !!(meta && meta.custom);
  }

  function allowsInsertView() {
    var meta = activeTableMeta();
    return !!(state.botId && meta && meta.allow_insert);
  }

  function parseFetchResponse(res) {
    return res.text().then(function (text) {
      var data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (e) {
          data = { detail: "Invalid JSON (HTTP " + res.status + ")" };
        }
      }
      return { ok: res.ok, status: res.status, data: data };
    });
  }

  function apiErrorMessage(result, fallback) {
    if (!result || !result.data) return fallback;
    var detail = result.data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && detail[0].msg) return detail[0].msg;
    return fallback + " (" + (result.status || "?") + ")";
  }

  function applyBotIdFromUrl() {
    var sel = el("db-bot-select");
    if (!sel) return;
    var params = new URLSearchParams(global.location.search || "");
    var fromUrl = params.get("bot_id");
    if (fromUrl && sel.querySelector('option[value="' + fromUrl + '"]')) sel.value = fromUrl;
  }

  function rememberBotId() {
    var id = selectedBotId();
    try {
      if (global.sessionStorage) {
        if (id) global.sessionStorage.setItem("db_manager_bot_id", id);
        else global.sessionStorage.removeItem("db_manager_bot_id");
      }
    } catch (e) {}
  }

  function confirmDanger(options) {
    if (global.AppConfirm && typeof global.AppConfirm.danger === "function") {
      return global.AppConfirm.danger(options);
    }
    var msg = (options.title || "") + "\n" + (options.message || "");
    return Promise.resolve(global.confirm(msg));
  }

  function closeActionsDropdown() {
    var menu = el("db-actions-dropdown-menu");
    var btn = el("db-actions-dropdown-btn");
    if (menu) menu.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function toggleActionsDropdown() {
    var menu = el("db-actions-dropdown-menu");
    var btn = el("db-actions-dropdown-btn");
    if (!menu || !btn) return;
    var open = menu.hidden;
    if (open) {
      updateToolbar();
      menu.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    } else {
      closeActionsDropdown();
    }
  }

  function canUnifiedAddRow() {
    if (!state.botId) return false;
    if (isInventoryView()) return true;
    return allowsInsertView();
  }

  function handleUnifiedAddRow() {
    if (!canUnifiedAddRow()) return;
    if (isInventoryView()) {
      openManualModal(null);
      return;
    }
    openGenericRowModal();
  }

  function updateToolbar() {
    var toolbar = el("db-actions-toolbar");
    var addBtn = el("db-unified-add-row-btn");
    var delSelectedBtn = el("db-delete-selected-btn");
    var importDrop = el("db-import-txt-btn-drop");
    var createDrop = el("db-create-table-btn-drop");
    var deleteTableDrop = el("db-delete-table-btn-drop");
    var dropdownBtn = el("db-actions-dropdown-btn");
    var inv = isInventoryView() && !!state.botId;
    var canAdd = canUnifiedAddRow();
    var selectedCount = Object.keys(state.selectedIds).filter(function (k) { return state.selectedIds[k]; }).length;

    if (toolbar) toolbar.hidden = !state.botId;

    if (addBtn) {
      addBtn.disabled = !canAdd;
      addBtn.title = !state.botId
        ? tr("database.select_bot_first")
        : canAdd
          ? ""
          : tr("database.add_row_unavailable");
    }

    if (delSelectedBtn) {
      var showDeleteSelected = inv && selectedCount > 0;
      delSelectedBtn.classList.toggle("is-visible", showDeleteSelected);
      delSelectedBtn.disabled = !showDeleteSelected;
      delSelectedBtn.title = showDeleteSelected
        ? tr("database.delete_selected") + " (" + selectedCount + ")"
        : "";
    }

    if (importDrop) {
      importDrop.hidden = !inv;
      importDrop.disabled = !inv;
    }

    if (createDrop) {
      createDrop.disabled = !state.botId;
    }

    if (deleteTableDrop) {
      deleteTableDrop.disabled = !(!!state.botId && isCustomTableView());
    }

    if (dropdownBtn) {
      dropdownBtn.disabled = !state.botId;
    }
  }

  function loadBots() {
    return fetch(state.apiOrigin + "/api/analytics/bots", { headers: state.headers })
      .then(parseFetchResponse)
      .then(function (result) {
        var sel = el("db-bot-select");
        if (!sel) return;
        if (!result.ok) {
          setStatus(apiErrorMessage(result, tr("database.load_bots_error")), "error");
          return;
        }
        var bots = Array.isArray(result.data) ? result.data : [];
        var prev = sel.value;
        sel.innerHTML = '<option value="">' + tr("common.select_bot") + "</option>";
        bots.forEach(function (b) {
          var opt = document.createElement("option");
          opt.value = String(b.id);
          opt.textContent = b.name || "Bot " + b.id;
          sel.appendChild(opt);
        });
        if (prev && sel.querySelector('option[value="' + prev + '"]')) sel.value = prev;
        applyBotIdFromUrl();
      });
  }

  function loadTables() {
    state.botId = selectedBotId();
    rememberBotId();
    state.selectedIds = {};
    if (!state.botId) {
      state.tables = [];
      updateToolbar();
      renderTablesList();
      renderGridPlaceholder(tr("database.pick_bot"));
      return Promise.resolve();
    }
    setStatus("", "");
    return fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/tables", {
      headers: state.headers,
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.load_tables_error")));
        state.tables = (result.data && result.data.tables) || [];
        if (!state.tables.some(function (t) { return t.name === state.activeTable; })) {
          var inv = state.tables.find(function (t) { return t.name === "inventory_items"; });
          state.activeTable = inv ? inv.name : (state.tables[0] ? state.tables[0].name : "");
        }
        renderTablesList();
        updateToolbar();
        if (state.activeTable) return loadTableData();
        renderGridPlaceholder(tr("database.no_managed"));
      })
      .catch(function (err) {
        renderGridPlaceholder(err.message || tr("database.load_tables_error"));
        setStatus(err.message, "error");
      });
  }

  function loadInventoryItems() {
    var url =
      state.apiOrigin +
      "/api/inventory/items?bot_id=" +
      encodeURIComponent(state.botId) +
      "&limit=2000";
    return fetch(url, { headers: state.headers })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.load_data_error")));
        state.tableMeta = {
          table: "inventory_items",
          columns: ["id", "product_id", "content", "status", "assigned_to_user", "issued_at", "created_at"],
          primary_key: ["id"],
          editable_columns: ["product_id", "content", "status"],
          total: result.data.total,
        };
        state.rows = result.data.rows || [];
        state.editingRowId = null;
        renderInventoryGrid();
        setStatus("", "");
      });
  }

  function loadTableData() {
    if (!state.botId || !state.activeTable) return Promise.resolve();
    if (isInventoryView()) return loadInventoryItems();
    var url =
      state.apiOrigin +
      "/api/projects/" +
      encodeURIComponent(state.botId) +
      "/db/data?table=" +
      encodeURIComponent(state.activeTable) +
      "&limit=2000";
    return fetch(url, { headers: state.headers })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.load_data_error")));
        state.tableMeta = result.data;
        state.rows = (result.data && result.data.rows) || [];
        state.editingRowId = null;
        renderLegacyGrid();
        setStatus("", "");
      })
      .catch(function (err) {
        renderGridPlaceholder(err.message);
        setStatus(err.message, "error");
      });
  }

  function renderTablesList() {
    var list = el("db-tables-list");
    if (!list) return;
    list.innerHTML = "";
    if (!state.tables.length) {
      list.innerHTML = '<div class="db-sidebar-empty">' + tr("database.no_tables") + "</div>";
      return;
    }
    state.tables.forEach(function (table) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "db-table-btn" + (table.name === state.activeTable ? " active" : "");
      btn.innerHTML =
        '<span class="db-table-name">' + escapeHtml(table.name) + "</span>" +
        '<span class="db-table-count">' + escapeHtml(table.row_count) + "</span>";
      btn.title = table.label || table.name;
      btn.onclick = function () {
        state.activeTable = table.name;
        state.selectedIds = {};
        closeActionsDropdown();
        renderTablesList();
        updateToolbar();
        loadTableData();
      };
      list.appendChild(btn);
    });
  }

  function renderGridPlaceholder(message) {
    var wrap = el("db-grid-wrap");
    if (!wrap) return;
    wrap.innerHTML = '<div class="db-grid-empty">' + escapeHtml(message) + "</div>";
  }

  function renderInventoryEmptyState() {
    var wrap = el("db-grid-wrap");
    if (!wrap) return;
    wrap.innerHTML =
      '<div class="db-empty-state">' +
      '<div class="db-empty-icon">📦</div>' +
      "<h3>" + escapeHtml(tr("database.empty_inventory_title")) + "</h3>" +
      "<p>" + escapeHtml(tr("database.empty_inventory_body")) + "</p>" +
      '<button type="button" class="db-btn-primary" id="db-empty-create-btn">' +
      escapeHtml(tr("database.create_first_item")) +
      "</button></div>";
    var btn = el("db-empty-create-btn");
    if (btn) btn.onclick = openManualModal;
  }

  function renderInventoryGrid() {
    var wrap = el("db-grid-wrap");
    if (!wrap) return;
    if (!state.rows.length) {
      renderInventoryEmptyState();
      return;
    }
    var cols = ["id", "product_id", "content", "status", "assigned_to_user", "issued_at"];
    var html = '<div class="db-grid-scroll"><table class="db-grid"><thead><tr>';
    html += '<th class="db-check-col"><input type="checkbox" id="db-select-all" /></th>';
    cols.forEach(function (c) {
      html += "<th>" + escapeHtml(c) + "</th>";
    });
    html += '<th class="db-actions-col">Actions</th></tr></thead><tbody>';
    state.rows.forEach(function (row) {
      var id = String(row.id);
      var checked = state.selectedIds[id] ? " checked" : "";
      html += '<tr data-id="' + escapeHtml(id) + '">';
      html += '<td class="db-check-col"><input type="checkbox" class="db-row-check" data-id="' + escapeHtml(id) + '"' + checked + " /></td>";
      cols.forEach(function (c) {
        var val = row[c];
        if (c === "content") {
          html += '<td class="db-cell-json"><code>' + escapeHtml(formatContentPreview(val)) + "</code></td>";
        } else {
          html += "<td>" + escapeHtml(val == null ? "" : val) + "</td>";
        }
      });
      html += '<td class="db-actions-col">' +
        '<button type="button" class="db-row-btn" data-inv-edit="' + escapeHtml(id) + '">✏️</button>' +
        '<button type="button" class="db-row-btn db-row-delete" data-inv-del="' + escapeHtml(id) + '">🗑</button>' +
        "</td></tr>";
    });
    html += "</tbody></table></div>";
    wrap.innerHTML = html;

    var selectAll = el("db-select-all");
    if (selectAll) {
      selectAll.onchange = function () {
        var on = selectAll.checked;
        state.rows.forEach(function (r) {
          state.selectedIds[String(r.id)] = on;
        });
        renderInventoryGrid();
      };
    }
    wrap.querySelectorAll(".db-row-check").forEach(function (cb) {
      cb.onchange = function () {
        state.selectedIds[cb.getAttribute("data-id")] = cb.checked;
        updateDeleteSelectedButton();
      };
    });
    updateDeleteSelectedButton();
    wrap.querySelectorAll("[data-inv-edit]").forEach(function (btn) {
      btn.onclick = function () {
        var row = state.rows.find(function (r) { return String(r.id) === btn.getAttribute("data-inv-edit"); });
        if (row) openManualModal(row);
      };
    });
    wrap.querySelectorAll("[data-inv-del]").forEach(function (btn) {
      btn.onclick = function () {
        deleteInventoryItems([parseInt(btn.getAttribute("data-inv-del"), 10)]);
      };
    });
  }

  function truncateCell(val, max) {
    var text = val == null ? "" : String(val);
    max = max || 80;
    if (text.length <= max) return text;
    return text.slice(0, max - 1) + "…";
  }

  function formatContentPreview(raw) {
    if (raw == null) return "";
    if (typeof raw === "object") return JSON.stringify(raw);
    try {
      return JSON.stringify(JSON.parse(String(raw)), null, 0);
    } catch (e) {
      return String(raw);
    }
  }

  function rowKey(row) {
    if (!state.tableMeta) return "";
    return state.tableMeta.primary_key.map(function (k) { return String(row[k]); }).join("|");
  }

  function primaryKeyFromRow(row) {
    var pk = {};
    (state.tableMeta.primary_key || []).forEach(function (k) { pk[k] = row[k]; });
    return pk;
  }

  function renderLegacyGrid() {
    var wrap = el("db-grid-wrap");
    if (!wrap || !state.tableMeta) return;
    var columns = state.tableMeta.columns || [];
    var editable = state.tableMeta.editable_columns || [];
    var rows = state.rows;
    var html = "";
    if (isBotGlobalsView()) {
      html += '<p class="db-table-hint">' + escapeHtml(tr("database.bot_globals_hint")) + "</p>";
    } else if (isCustomTableView()) {
      html += '<p class="db-table-hint">' + escapeHtml(tr("database.custom_table_hint")) + "</p>";
    }
    html += '<div class="db-grid-scroll"><table class="db-grid"><thead><tr>';
    columns.forEach(function (col) { html += "<th>" + escapeHtml(col) + "</th>"; });
    html += '<th class="db-actions-col">Actions</th></tr></thead><tbody>';
    if (!rows.length) {
      html += '<tr><td colspan="' + (columns.length + 1) + '" class="db-grid-empty-cell">' + escapeHtml(tr("database.no_records")) + "</td></tr>";
    }
    rows.forEach(function (row) {
      var rk = rowKey(row);
      var isEditing = state.editingRowId === rk;
      html += '<tr data-row-key="' + escapeHtml(rk) + '">';
      columns.forEach(function (col) {
        var val = row[col];
        var canEdit = editable.indexOf(col) >= 0 && state.tableMeta.primary_key.indexOf(col) < 0;
        if (isEditing && canEdit) {
          html += '<td><input class="db-cell-input" data-col="' + escapeHtml(col) + '" value="' + escapeHtml(val == null ? "" : val) + '" /></td>';
        } else {
          html += "<td title='" + escapeHtml(val == null ? "" : val) + "'>" + escapeHtml(truncateCell(val)) + "</td>";
        }
      });
      html += '<td class="db-actions-col">';
      if (isEditing) {
        html += '<button type="button" class="db-row-btn db-row-save" data-action="save">' + escapeHtml(tr("common.save")) + "</button>";
        html += '<button type="button" class="db-row-btn" data-action="cancel">' + escapeHtml(tr("common.cancel")) + "</button>";
      } else {
        html += '<button type="button" class="db-row-btn" data-action="edit">✏️</button>';
        html += '<button type="button" class="db-row-btn db-row-delete" data-action="delete">🗑</button>';
      }
      html += "</td></tr>";
    });
    html += "</tbody></table></div>";
    wrap.innerHTML = html;
    wrap.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var trEl = btn.closest("tr");
        var key = trEl.getAttribute("data-row-key");
        var row = rows.find(function (r) { return rowKey(r) === key; });
        if (!row) return;
        var action = btn.getAttribute("data-action");
        if (action === "edit") { state.editingRowId = key; renderLegacyGrid(); }
        else if (action === "cancel") { state.editingRowId = null; renderLegacyGrid(); }
        else if (action === "save") saveLegacyRow(trEl, row);
        else if (action === "delete") deleteLegacyRow(row);
      };
    });
  }

  function saveLegacyRow(trEl, row) {
    var values = {};
    trEl.querySelectorAll(".db-cell-input").forEach(function (input) {
      values[input.getAttribute("data-col")] = input.value;
    });
    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/row", {
      method: "PUT",
      headers: state.headers,
      body: JSON.stringify({ table: state.activeTable, primary_key: primaryKeyFromRow(row), values: values }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.save_error")));
        state.editingRowId = null;
        return loadTables();
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function deleteLegacyRow(row) {
    confirmDanger({
      title: tr("common.confirm_delete_title"),
      message: tr("database.delete_confirm"),
    }).then(function (ok) {
      if (!ok) return;
      fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/row", {
        method: "DELETE",
        headers: state.headers,
        body: JSON.stringify({ table: state.activeTable, primary_key: primaryKeyFromRow(row) }),
      })
        .then(parseFetchResponse)
        .then(function (result) {
          if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.delete_error")));
          return loadTables();
        })
        .catch(function (err) { setStatus(err.message, "error"); });
    });
  }

  function openGenericRowModal() {
    if (!allowsInsertView()) return;
    var modal = el("db-row-modal");
    var body = el("db-row-modal-body");
    if (!modal || !body) return;
    var title = el("db-row-modal-title");
    if (title) title.textContent = isBotGlobalsView() ? tr("database.add_global") : tr("database.add_table_row");
    body.innerHTML = "";
    if (isBotGlobalsView()) {
      body.innerHTML =
        '<p class="db-field-hint">' + escapeHtml(tr("database.bot_globals_hint")) + "</p>" +
        '<label class="db-field-label">' + escapeHtml(tr("database.global_key")) + '</label>' +
        '<input type="text" id="db-row-field-key" class="db-field-input" placeholder="price" />' +
        '<label class="db-field-label">' + escapeHtml(tr("database.global_value")) + '</label>' +
        '<input type="text" id="db-row-field-value" class="db-field-input" placeholder="250" />';
    } else {
      var cols = (state.tableMeta && state.tableMeta.editable_columns) || [];
      var fields = cols.filter(function (c) { return c !== "updated_at"; });
      fields.forEach(function (col) {
        body.innerHTML +=
          '<label class="db-field-label">' + escapeHtml(col) + '</label>' +
          '<input type="text" class="db-field-input db-row-dynamic" data-col="' + escapeHtml(col) + '" />';
      });
    }
    modal.hidden = false;
  }

  function closeGenericRowModal() {
    var modal = el("db-row-modal");
    if (modal) modal.hidden = true;
  }

  function saveGenericRowModal() {
    if (!state.botId || !state.activeTable) return;
    var values = {};
    if (isBotGlobalsView()) {
      values.key = (el("db-row-field-key") && el("db-row-field-key").value || "").trim();
      values.value = el("db-row-field-value") ? el("db-row-field-value").value : "";
      if (!values.key) {
        setStatus(tr("database.global_key") + "?", "error");
        return;
      }
    } else {
      document.querySelectorAll(".db-row-dynamic").forEach(function (input) {
        values[input.getAttribute("data-col")] = input.value;
      });
      if (!Object.keys(values).length) {
        setStatus(tr("database.columns_required"), "error");
        return;
      }
    }
    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/row", {
      method: "POST",
      headers: state.headers,
      body: JSON.stringify({ table: state.activeTable, values: values }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.save_error")));
        closeGenericRowModal();
        setStatus(tr("database.insert_ok"), "success");
        return loadTables();
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function openCreateTableModal() {
    if (!state.botId) return;
    el("db-new-table-name").value = "";
    el("db-new-table-columns").value = "";
    el("db-new-table-key").value = "";
    el("db-create-table-modal").hidden = false;
  }

  function closeCreateTableModal() {
    el("db-create-table-modal").hidden = true;
  }

  function saveCreateTableModal() {
    if (!state.botId) return;
    var name = (el("db-new-table-name").value || "").trim();
    var colsRaw = (el("db-new-table-columns").value || "").trim();
    var keyCol = (el("db-new-table-key").value || "").trim();
    var columns = colsRaw.split(/[,;]+/).map(function (c) { return c.trim(); }).filter(Boolean);
    if (!name || !columns.length || !keyCol) {
      setStatus(tr("database.columns_required"), "error");
      return;
    }
    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/custom-tables", {
      method: "POST",
      headers: state.headers,
      body: JSON.stringify({ name: name, columns: columns, key_column: keyCol }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.save_error")));
        closeCreateTableModal();
        state.activeTable = name;
        setStatus(tr("database.create_table_ok", { name: name }), "success");
        return loadTables();
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function deleteCustomTable() {
    if (!state.botId || !isCustomTableView()) return;
    var name = state.activeTable;
    confirmDanger({
      title: tr("common.confirm_delete_title"),
      message: tr("database.delete_table_confirm", { name: name }),
    }).then(function (ok) {
      if (!ok) return;
      fetch(
        state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/custom-tables/" + encodeURIComponent(name),
        { method: "DELETE", headers: state.headers }
      )
        .then(parseFetchResponse)
        .then(function (result) {
          if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.delete_error")));
          state.activeTable = "bot_globals";
          return loadTables();
        })
        .catch(function (err) { setStatus(err.message, "error"); });
    });
  }

  function openManualModal(row) {
    if (!isInventoryView()) return;
    var modal = el("db-item-modal");
    if (!modal) return;
    state.editingInventoryId = row ? row.id : null;
    el("db-item-modal-title").textContent = row ? tr("database.edit_row") : tr("database.add_row");
    el("db-item-product-id").value = row ? row.product_id || "" : "";
    el("db-item-status").value = row ? row.status || "in_stock" : "in_stock";
    var content = row ? row.content : '{"email":"","pass":""}';
    if (typeof content === "object") content = JSON.stringify(content, null, 2);
    else {
      try { content = JSON.stringify(JSON.parse(String(content)), null, 2); } catch (e) {}
    }
    el("db-item-content").value = content || "{}";
    modal.hidden = false;
  }

  function closeManualModal() {
    var modal = el("db-item-modal");
    if (modal) modal.hidden = true;
    state.editingInventoryId = null;
  }

  function saveManualModal() {
    if (!state.botId) return;
    var productId = (el("db-item-product-id").value || "").trim();
    var status = el("db-item-status").value || "in_stock";
    var contentRaw = el("db-item-content").value || "{}";
    var content;
    try {
      content = JSON.parse(contentRaw);
    } catch (e) {
      setStatus(tr("database.invalid_json"), "error");
      return;
    }
    var promise;
    if (state.editingInventoryId) {
      promise = fetch(state.apiOrigin + "/api/inventory/items/" + state.editingInventoryId, {
        method: "PUT",
        headers: state.headers,
        body: JSON.stringify({ bot_id: parseInt(state.botId, 10), product_id: productId, content: content, status: status }),
      });
    } else {
      promise = fetch(state.apiOrigin + "/api/inventory/items", {
        method: "POST",
        headers: state.headers,
        body: JSON.stringify({ bot_id: parseInt(state.botId, 10), product_id: productId, content: content, status: status }),
      });
    }
    promise
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.save_error")));
        closeManualModal();
        showDbToast(tr("database.saved_ok"), "success");
        return loadTables();
      })
      .catch(function (err) { setStatus(err.message, "error"); });
  }

  function deleteInventoryItems(ids) {
    if (!ids.length) {
      setStatus(tr("database.nothing_selected"), "error");
      return;
    }
    if (!isInventoryView()) return;
    confirmDanger({
      title: tr("common.confirm_delete_title"),
      message: tr("database.delete_confirm"),
      detail: ids.length > 1 ? tr("database.delete_selected") + " (" + ids.length + ")" : "",
    }).then(function (ok) {
      if (!ok) return;
      fetch(state.apiOrigin + "/api/inventory/items", {
        method: "DELETE",
        headers: state.headers,
        body: JSON.stringify({ bot_id: parseInt(state.botId, 10), item_ids: ids }),
      })
        .then(parseFetchResponse)
        .then(function (result) {
          if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.delete_error")));
          state.selectedIds = {};
          return loadTables();
        })
        .catch(function (err) { setStatus(err.message, "error"); });
    });
  }

  function updateDeleteSelectedButton() {
    updateToolbar();
  }

  function deleteSelectedInventory() {
    var ids = Object.keys(state.selectedIds).filter(function (k) { return state.selectedIds[k]; }).map(function (k) { return parseInt(k, 10); });
    deleteInventoryItems(ids);
  }

  function loadProductIdsDatalist() {
    if (!state.botId) return Promise.resolve();
    return fetch(state.apiOrigin + "/api/inventory/product-ids?bot_id=" + encodeURIComponent(state.botId), {
      headers: state.headers,
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) return;
        var list = el("db-product-id-list");
        if (!list) return;
        list.innerHTML = "";
        (result.data.product_ids || []).forEach(function (pid) {
          var opt = document.createElement("option");
          opt.value = pid;
          list.appendChild(opt);
        });
      });
  }

  function openImportModal() {
    if (!state.botId) {
      setStatus(tr("database.select_bot_first"), "error");
      return;
    }
    if (!isInventoryView()) return;
    state.importWizard = { filePath: null, preview: null };
    el("db-import-step-1").hidden = false;
    el("db-import-step-2").hidden = true;
    el("db-import-run-btn").hidden = true;
    el("db-import-result").hidden = true;
    el("db-import-file-label").textContent = "";
    el("db-import-modal").hidden = false;
    loadProductIdsDatalist();
  }

  function closeImportModal() {
    el("db-import-modal").hidden = true;
  }

  function pickImportFile() {
    if (!global.electronAPI || typeof global.electronAPI.selectImportFile !== "function") {
      if (typeof global.electronAPI !== "undefined" && typeof global.electronAPI.selectTextFile === "function") {
        return pickImportFileLegacy();
      }
      setStatus(tr("database.import_desktop_only"), "error");
      return;
    }
    global.electronAPI.selectImportFile().then(function (pick) {
      if (!pick || pick.canceled || !pick.filePath) return;
      state.importWizard.filePath = pick.filePath;
      el("db-import-file-label").textContent = pick.filePath;
      return fetch(state.apiOrigin + "/api/inventory/parse-txt", {
        method: "POST",
        headers: state.headers,
        body: JSON.stringify({ bot_id: parseInt(state.botId, 10), file_path: pick.filePath }),
      }).then(parseFetchResponse);
    }).then(function (result) {
      if (!result) return;
      if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.import_error")));
      state.importWizard.preview = result.data;
      showImportMappingStep(result.data);
    }).catch(function (err) {
      setStatus(err.message, "error");
    });
  }

  function pickImportFileLegacy() {
    global.electronAPI.selectTextFile().then(function (pick) {
      if (!pick || pick.canceled || !pick.filePath) return;
      state.importWizard.filePath = pick.filePath;
      el("db-import-file-label").textContent = pick.filePath;
      return fetch(state.apiOrigin + "/api/inventory/parse-txt", {
        method: "POST",
        headers: state.headers,
        body: JSON.stringify({ bot_id: parseInt(state.botId, 10), file_path: pick.filePath }),
      }).then(parseFetchResponse);
    }).then(function (result) {
      if (!result) return;
      if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.import_error")));
      state.importWizard.preview = result.data;
      showImportMappingStep(result.data);
    }).catch(function (err) {
      setStatus(err.message, "error");
    });
  }

  function showImportMappingStep(preview) {
    el("db-import-step-2").hidden = false;
    el("db-import-run-btn").hidden = false;
    var delimRow = el("db-import-delimiter-row");
    var mapping = el("db-import-mapping");
    if (preview.format === "json") {
      if (delimRow) delimRow.hidden = true;
      mapping.innerHTML =
        "<p class=\"db-field-hint\">" + escapeHtml(tr("database.import_json_hint")) + "</p>";
    } else {
      if (delimRow) delimRow.hidden = false;
      el("db-import-delimiter").value = preview.delimiter || ":";
      mapping.innerHTML = "<h4>" + escapeHtml(tr("database.column_mapping")) + "</h4>";
      (preview.suggested_column_map || []).forEach(function (key, idx) {
        mapping.innerHTML +=
          '<div class="db-map-row"><label>Column ' + (idx + 1) + '</label>' +
          '<input type="text" class="db-field-input db-map-key" data-col="' + idx + '" value="' + escapeHtml(key) + '" /></div>';
      });
    }
    var prev = el("db-import-preview");
    if (preview.format === "json") {
      var sampleJson = (preview.sample_lines || [])
        .map(function (s) {
          return escapeHtml(typeof s.parts === "object" ? JSON.stringify(s.parts) : s.raw);
        })
        .join("<br/>");
      prev.innerHTML = "<strong>" + escapeHtml(tr("database.preview_lines")) + ":</strong><br/>" + sampleJson;
    } else {
      var samples = (preview.sample_lines || []).map(function (s) { return escapeHtml(s.raw); }).join("<br/>");
      prev.innerHTML = "<strong>" + escapeHtml(tr("database.preview_lines")) + ":</strong><br/>" + samples;
    }
  }

  function runTxtImport() {
    var filePath = state.importWizard.filePath;
    if (!filePath) return;
    var productId = (el("db-import-product-id").value || "").trim();
    if (!productId) {
      setStatus(tr("database.product_id_required"), "error");
      return;
    }
    var delimiter = el("db-import-delimiter").value || ":";
    var columnMap = [];
    document.querySelectorAll(".db-map-key").forEach(function (input) {
      columnMap.push((input.value || "").trim());
    });
    if (state.importWizard.preview && state.importWizard.preview.format === "json") {
      columnMap = state.importWizard.preview.suggested_column_map || [];
    }
    var staticFields = {};
    try {
      var rawStatic = (el("db-import-static").value || "").trim();
      if (rawStatic) staticFields = JSON.parse(rawStatic);
    } catch (e) {
      setStatus(tr("database.invalid_json"), "error");
      return;
    }
    el("db-import-run-btn").disabled = true;
    fetch(state.apiOrigin + "/api/inventory/import", {
      method: "POST",
      headers: state.headers,
      body: JSON.stringify({
        bot_id: parseInt(state.botId, 10),
        file_path: filePath,
        product_id: productId,
        delimiter: delimiter,
        column_map: columnMap,
        static_fields: staticFields,
      }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        el("db-import-run-btn").disabled = false;
        if (!result.ok) throw new Error(apiErrorMessage(result, tr("database.import_error")));
        var box = el("db-import-result");
        box.hidden = false;
        box.innerHTML =
          "<pre>" + escapeHtml(JSON.stringify(result.data, null, 2)) + "</pre>";
        return loadTables();
      })
      .catch(function (err) {
        el("db-import-run-btn").disabled = false;
        setStatus(err.message, "error");
      });
  }

  function bindEvents() {
    var botSel = el("db-bot-select");
    if (botSel) botSel.onchange = function () {
      state.activeTable = "inventory_items";
      closeActionsDropdown();
      loadTables();
    };
    el("db-refresh-btn").onclick = loadTables;
    var unifiedAdd = el("db-unified-add-row-btn");
    if (unifiedAdd) unifiedAdd.onclick = handleUnifiedAddRow;
    var importDrop = el("db-import-txt-btn-drop");
    if (importDrop) {
      importDrop.onclick = function () {
        closeActionsDropdown();
        openImportModal();
      };
    }
    var createDrop = el("db-create-table-btn-drop");
    if (createDrop) {
      createDrop.onclick = function () {
        closeActionsDropdown();
        openCreateTableModal();
      };
    }
    var deleteTableDrop = el("db-delete-table-btn-drop");
    if (deleteTableDrop) {
      deleteTableDrop.onclick = function () {
        closeActionsDropdown();
        deleteCustomTable();
      };
    }
    var dropdownBtn = el("db-actions-dropdown-btn");
    if (dropdownBtn) dropdownBtn.onclick = function (e) {
      e.stopPropagation();
      toggleActionsDropdown();
    };
    var delSelected = el("db-delete-selected-btn");
    if (delSelected) delSelected.onclick = deleteSelectedInventory;
    el("db-item-save-btn").onclick = saveManualModal;
    el("db-import-pick-file").onclick = pickImportFile;
    el("db-import-run-btn").onclick = runTxtImport;
    var rowSaveBtn = el("db-row-save-btn");
    if (rowSaveBtn) rowSaveBtn.onclick = saveGenericRowModal;
    var createTableSaveBtn = el("db-create-table-save-btn");
    if (createTableSaveBtn) createTableSaveBtn.onclick = saveCreateTableModal;
    document.querySelectorAll("[data-close-modal]").forEach(function (n) {
      n.onclick = closeManualModal;
    });
    document.querySelectorAll("[data-close-import]").forEach(function (n) {
      n.onclick = closeImportModal;
    });
    document.querySelectorAll("[data-close-row-modal]").forEach(function (n) {
      n.onclick = closeGenericRowModal;
    });
    document.querySelectorAll("[data-close-create-table]").forEach(function (n) {
      n.onclick = closeCreateTableModal;
    });
    document.addEventListener("click", function (e) {
      var dropdown = el("db-actions-dropdown");
      if (!dropdown || dropdown.contains(e.target)) return;
      closeActionsDropdown();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeActionsDropdown();
    });
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    state.headers = authHeaders();
    bindEvents();
    loadBots().then(function () {
      if (selectedBotId()) loadTables();
    });
    document.addEventListener("botbuilder:langchange", function () {
      loadBots().then(function () { if (selectedBotId()) loadTables(); });
    });
  }

  global.DatabaseManagerView = { init: init, reload: loadTables };
})(typeof window !== "undefined" ? window : globalThis);
