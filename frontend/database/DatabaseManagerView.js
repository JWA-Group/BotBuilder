/**
 * DatabaseManagerView — CRUD grid for bot user_data.db + import.
 */
(function (global) {
  "use strict";

  var state = {
    apiOrigin: "",
    headers: {},
    botId: "",
    tables: [],
    activeTable: "",
    tableMeta: null,
    rows: [],
    importing: false,
    editingRowId: null,
  };

  function getApiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
  }

  function authHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json", "Accept-Language": "en" };
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

  function setStatus(message, kind) {
    var box = el("db-status");
    if (!box) return;
    if (!message || kind === "success") {
      box.textContent = "";
      box.className = "db-status";
      box.hidden = true;
      return;
    }
    box.textContent = message;
    box.className = "db-status" + (kind ? " db-status-" + kind : "");
    box.hidden = false;
  }

  function setImportLoading(loading) {
    state.importing = loading;
    var btn = el("db-import-btn");
    var spinner = el("db-import-spinner");
    if (btn) btn.disabled = loading;
    if (spinner) spinner.hidden = !loading;
  }

  function selectedBotId() {
    var sel = el("db-bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function rowKey(row) {
    if (!state.tableMeta) return "";
    return state.tableMeta.primary_key
      .map(function (k) {
        return String(row[k]);
      })
      .join("|");
  }

  function primaryKeyFromRow(row) {
    var pk = {};
    (state.tableMeta.primary_key || []).forEach(function (k) {
      pk[k] = row[k];
    });
    return pk;
  }

  function parseFetchResponse(res) {
    return res.text().then(function (text) {
      var data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (e) {
          data = {
            detail:
              res.status === 404
                ? "API базы данных не найден (404). Полностью закройте и снова откройте BotBuilder."
                : "Ответ сервера не JSON (код " + res.status + ")",
          };
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
    if (fromUrl && sel.querySelector('option[value="' + fromUrl + '"]')) {
      sel.value = fromUrl;
      return;
    }
    try {
      var saved = global.sessionStorage && global.sessionStorage.getItem("db_manager_bot_id");
      if (saved && sel.querySelector('option[value="' + saved + '"]')) sel.value = saved;
    } catch (e) {}
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
      })
      .catch(function (err) {
        setStatus(err.message || tr("database.load_bots_error"), "error");
      });
  }

  function loadTables() {
    state.botId = selectedBotId();
    rememberBotId();
    if (!state.botId) {
      state.tables = [];
      state.activeTable = "";
      renderTablesList();
      renderGridPlaceholder(tr("database.pick_bot"));
      setStatus("", "");
      return Promise.resolve();
    }
    setStatus("", "");
    return fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/tables", {
      headers: state.headers,
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) {
          throw new Error(apiErrorMessage(result, tr("database.load_tables_error")));
        }
        state.tables = (result.data && result.data.tables) || [];
        if (!state.activeTable && state.tables.length) {
          state.activeTable = state.tables[0].name;
        } else if (
          state.activeTable &&
          !state.tables.some(function (t) {
            return t.name === state.activeTable;
          })
        ) {
          state.activeTable = state.tables.length ? state.tables[0].name : "";
        }
        renderTablesList();
        if (state.activeTable) return loadTableData();
        renderGridPlaceholder(tr("database.no_managed"));
        setStatus(tr("database.tables_not_found"), "error");
      })
      .catch(function (err) {
        state.tables = [];
        state.activeTable = "";
        renderTablesList();
        renderGridPlaceholder(err.message || tr("database.load_tables_error"));
        setStatus(err.message || tr("database.load_tables_error"), "error");
      });
  }

  function loadTableData() {
    if (!state.botId || !state.activeTable) return Promise.resolve();
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
        if (!result.ok) {
          throw new Error(apiErrorMessage(result, tr("database.load_data_error")));
        }
        state.tableMeta = result.data;
        state.rows = (result.data && result.data.rows) || [];
        state.editingRowId = null;
        renderGrid();
        setStatus("", "");
      })
      .catch(function (err) {
        renderGridPlaceholder(err.message || tr("database.load_data_error"));
        setStatus(err.message || tr("database.load_data_error"), "error");
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
        "<span class=\"db-table-name\">" +
        escapeHtml(table.label || table.name) +
        "</span><span class=\"db-table-count\">" +
        escapeHtml(table.row_count) +
        "</span>";
      btn.onclick = function () {
        state.activeTable = table.name;
        renderTablesList();
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

  function renderGrid() {
    var wrap = el("db-grid-wrap");
    if (!wrap || !state.tableMeta) return;

    var columns = state.tableMeta.columns || [];
    var editable = state.tableMeta.editable_columns || [];
    var rows = state.rows;

    var html = '<div class="db-grid-scroll"><table class="db-grid"><thead><tr>';
    columns.forEach(function (col) {
      html += "<th>" + escapeHtml(col) + "</th>";
    });
    html += '<th class="db-actions-col">' + escapeHtml(tr("common.actions")) + "</th></tr></thead><tbody>";

    if (!rows.length) {
      html += '<tr><td colspan="' + (columns.length + 1) + '" class="db-grid-empty-cell">' + escapeHtml(tr("database.no_records")) + "</td></tr>";
    }

    rows.forEach(function (row) {
      var rk = rowKey(row);
      var isEditing = state.editingRowId === rk;
      html += "<tr data-row-key=\"" + escapeHtml(rk) + "\">";
      columns.forEach(function (col) {
        var val = row[col];
        var canEdit = editable.indexOf(col) >= 0 && state.tableMeta.primary_key.indexOf(col) < 0;
        if (isEditing && canEdit) {
          html +=
            '<td><input class="db-cell-input" data-col="' +
            escapeHtml(col) +
            '" value="' +
            escapeHtml(val == null ? "" : val) +
            '" /></td>';
        } else {
          html += "<td>" + escapeHtml(val == null ? "" : val) + "</td>";
        }
      });
      html += '<td class="db-actions-col">';
      if (isEditing) {
        html +=
          '<button type="button" class="db-row-btn db-row-save" data-action="save">' + escapeHtml(tr("common.save")) + "</button>" +
          '<button type="button" class="db-row-btn" data-action="cancel">' + escapeHtml(tr("common.cancel")) + "</button>";
      } else {
        html +=
          '<button type="button" class="db-row-btn" data-action="edit" title="' + escapeHtml(tr("database.edit_title")) + '">✏️</button>' +
          '<button type="button" class="db-row-btn db-row-delete" data-action="delete" title="' + escapeHtml(tr("database.delete_title")) + '">🗑</button>';
      }
      html += "</td></tr>";
    });

    html += "</tbody></table></div>";
    if (state.tableMeta.total > rows.length) {
      html +=
        '<p class="db-grid-note">' +
        escapeHtml(tr("database.rows_shown", { shown: rows.length, total: state.tableMeta.total })) +
        "</p>";
    }
    wrap.innerHTML = html;

    wrap.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.onclick = function () {
        var tr = btn.closest("tr");
        if (!tr) return;
        var key = tr.getAttribute("data-row-key");
        var row = rows.find(function (r) {
          return rowKey(r) === key;
        });
        if (!row) return;
        var action = btn.getAttribute("data-action");
        if (action === "edit") {
          state.editingRowId = key;
          renderGrid();
        } else if (action === "cancel") {
          state.editingRowId = null;
          renderGrid();
        } else if (action === "save") {
          saveRow(tr, row);
        } else if (action === "delete") {
          deleteRow(row);
        }
      };
    });
  }

  function saveRow(tr, row) {
    var values = {};
    tr.querySelectorAll(".db-cell-input").forEach(function (input) {
      var col = input.getAttribute("data-col");
      if (!col) return;
      values[col] = input.value;
    });
    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/row", {
      method: "PUT",
      headers: state.headers,
      body: JSON.stringify({
        table: state.activeTable,
        primary_key: primaryKeyFromRow(row),
        values: values,
      }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) {
          throw new Error(apiErrorMessage(result, tr("database.save_error")));
        }
        state.editingRowId = null;
        setStatus("", "");
        return loadTables().then(loadTableData);
      })
      .catch(function (err) {
        setStatus(err.message || tr("database.save_error"), "error");
      });
  }

  function deleteRow(row) {
    if (!confirm(tr("database.delete_confirm"))) return;
    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/row", {
      method: "DELETE",
      headers: state.headers,
      body: JSON.stringify({
        table: state.activeTable,
        primary_key: primaryKeyFromRow(row),
      }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) {
          throw new Error(apiErrorMessage(result, tr("database.delete_error")));
        }
        setStatus("", "");
        return loadTables().then(loadTableData);
      })
      .catch(function (err) {
        setStatus(err.message || tr("database.delete_error"), "error");
      });
  }

  function importDatabase() {
    if (state.importing) return;
    if (!state.botId) {
      setStatus(tr("database.select_bot_first"), "error");
      return;
    }
    if (!global.electronAPI || typeof global.electronAPI.selectDatabaseFile !== "function") {
      setStatus(tr("database.import_desktop_only"), "error");
      return;
    }
    global.electronAPI
      .selectDatabaseFile()
      .then(function (pick) {
        if (!pick || pick.canceled || !pick.filePath) {
          setStatus("", "");
          return null;
        }
        setImportLoading(true);
        setStatus("", "");
        return fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(state.botId) + "/db/import", {
          method: "POST",
          headers: state.headers,
          body: JSON.stringify({ file_path: pick.filePath }),
        }).then(parseFetchResponse);
      })
      .then(function (result) {
        setImportLoading(false);
        if (!result) return;
        if (!result.ok) {
          var detail =
            result.data && result.data.detail
              ? typeof result.data.detail === "string"
                ? result.data.detail
                : JSON.stringify(result.data.detail)
              : tr("database.import_error");
          setStatus(detail, "error");
          return;
        }
        setStatus("", "");
        return loadTables().then(loadTableData);
      })
      .catch(function (err) {
        setImportLoading(false);
        setStatus(err.message || tr("database.import_error"), "error");
      });
  }

  function bindEvents() {
    var botSel = el("db-bot-select");
    if (botSel) {
      botSel.onchange = function () {
        state.activeTable = "";
        loadTables();
      };
    }
    var refreshBtn = el("db-refresh-btn");
    if (refreshBtn) refreshBtn.onclick = function () {
      loadTables();
    };
    var importBtn = el("db-import-btn");
    if (importBtn) importBtn.onclick = importDatabase;
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    state.headers = authHeaders();
    bindEvents();
    loadBots().then(function () {
      if (selectedBotId()) loadTables();
    });
    document.addEventListener("botbuilder:langchange", function () {
      loadBots().then(function () {
        if (selectedBotId()) loadTables();
      });
    });
  }

  global.DatabaseManagerView = {
    init: init,
    reload: loadTables,
  };
})(typeof window !== "undefined" ? window : globalThis);
