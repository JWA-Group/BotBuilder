/**
 * TemplateLibraryView — галерея шаблонов с интерактивным превью.
 */
(function (global) {
  "use strict";

  var state = {
    tab: "local",
    search: "",
    tag: "Все",
    local: [],
    marketplace: [],
    selected: null,
    previewViewer: null,
    loading: false,
  };

  function apiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
  }

  function apiBase() {
    if (typeof global.getApiBase === "function") return global.getApiBase();
    return apiOrigin() + "/api";
  }

  function authHeaders() {
    return typeof global.apiHeaders === "function" ? global.apiHeaders() : {};
  }

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function jsonHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json" };
  }

  function userId() {
    return (global.localStorage && global.localStorage.getItem("user_id")) || "1";
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

  function parseResponse(res) {
    var ct = (res.headers.get("content-type") || "").toLowerCase();
    if (ct.indexOf("application/json") >= 0) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    }
    return res.text().then(function (text) {
      return { ok: res.ok, status: res.status, data: text };
    });
  }

  function cardPreviewHtml(item) {
    var scenario = item.scenario || {};
    var blocks = scenario.blocks || [];
    var connections = scenario.connections || [];
    if (!blocks.length && item.block_count) {
      blocks = [{ id: "start", type: "start", x: 40, y: 40, data: {} }];
    }
    if (typeof CanvasView !== "undefined" && CanvasView.captureGraphPreview && blocks.length) {
      var src = CanvasView.captureGraphPreview(blocks, connections, { maxThumbWidth: 360 });
      if (src) {
        return '<img class="tpl-card-img" src="' + escapeHtml(src) + '" alt="" loading="lazy" />';
      }
    }
    return '<div class="tpl-card-img tpl-card-img-fallback"><span>📋</span><small>' + escapeHtml(tr("templates.preview_label")) + "</small></div>";
  }

  function tagBadges(tags) {
    if (!tags || !tags.length) return '<span class="tpl-tag tpl-tag-muted">' + escapeHtml(tr("templates.tag_general")) + "</span>";
    return tags
      .slice(0, 3)
      .map(function (t) {
        return '<span class="tpl-tag">' + escapeHtml(t) + "</span>";
      })
      .join("");
  }

  function sourceBadge(item, inline) {
    var extra = inline ? " tpl-source-inline" : "";
    if (item.source === "local") {
      return '<span class="tpl-source-badge tpl-source-local' + extra + '">' + escapeHtml(tr("templates.source_local")) + "</span>";
    }
    if (item.source === "catalog" || item.source === "marketplace") {
      return '<span class="tpl-source-badge tpl-source-market' + extra + '">' + escapeHtml(tr("templates.source_market")) + "</span>";
    }
    return "";
  }

  function resolveExportSource(item) {
    if (!item) return "";
    if (item.source === "local") return "local";
    if (item.source === "catalog" || (item.source === "marketplace" && item.installable)) return "catalog";
    return "";
  }

  function triggerFileDownload(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      if (a.parentNode) a.parentNode.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  }

  function phantomBadge(item) {
    if (!item.has_missing_plugins) return "";
    var list = (item.missing_plugins || []).slice(0, 2).join(", ");
    var more = (item.missing_plugins || []).length > 2 ? "…" : "";
    return (
      '<span class="tpl-warn-badge" title="Не хватает плагинов: ' +
      escapeHtml((item.missing_plugins || []).join(", ")) +
      '">⚠ ' +
      escapeHtml(list + more) +
      "</span>"
    );
  }

  function listForTab() {
    if (state.tab === "marketplace") {
      return state.marketplace.map(function (item) {
        return Object.assign({}, item, { listSource: "marketplace" });
      });
    }
    return state.local.map(function (item) {
      return Object.assign({}, item, { source: "local", listSource: "local" });
    });
  }

  function normalizeTag(t) {
    return String(t == null ? "" : t).trim();
  }

  function collectAvailableTags() {
    var seen = {};
    var tags = [];
    listForTab().forEach(function (item) {
      (item.tags || []).forEach(function (raw) {
        var tag = normalizeTag(raw);
        if (!tag) return;
        var key = tag.toLowerCase();
        if (seen[key]) return;
        seen[key] = true;
        tags.push(tag);
      });
    });
    tags.sort(function (a, b) {
      return a.localeCompare(b, "ru", { sensitivity: "base" });
    });
    return tags;
  }

  function renderTagFilters() {
    var host = el("tpl-tag-filters");
    if (!host) return;
    var available = collectAvailableTags();
    var active = state.tag || "Все";
    if (active !== "Все") {
      var stillExists = available.some(function (t) {
        return t.toLowerCase() === active.toLowerCase();
      });
      if (!stillExists) {
        active = "Все";
        state.tag = "Все";
      } else {
        // keep canonical casing from available list
        available.some(function (t) {
          if (t.toLowerCase() === active.toLowerCase()) {
            active = t;
            state.tag = t;
            return true;
          }
          return false;
        });
      }
    }

    var html =
      '<button type="button" class="tpl-tag-filter' +
      (active === "Все" ? " tpl-tag-filter-active" : "") +
      '" data-tag="Все">' + escapeHtml(tr("templates.tag_all")) + "</button>";
    available.forEach(function (tag) {
      html +=
        '<button type="button" class="tpl-tag-filter' +
        (tag.toLowerCase() === active.toLowerCase() ? " tpl-tag-filter-active" : "") +
        '" data-tag="' +
        escapeHtml(tag) +
        '">' +
        escapeHtml(tag) +
        "</button>";
    });
    host.innerHTML = html;
    host.hidden = available.length === 0;

    host.querySelectorAll(".tpl-tag-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.tag = btn.getAttribute("data-tag") || "Все";
        host.querySelectorAll(".tpl-tag-filter").forEach(function (b) {
          b.classList.toggle("tpl-tag-filter-active", b === btn);
        });
        renderGrid();
      });
    });
  }

  function filteredList() {
    var list = listForTab();
    var q = state.search.trim().toLowerCase();
    if (q) {
      list = list.filter(function (item) {
        var hay =
          (item.name || "") +
          " " +
          (item.description || "") +
          " " +
          (item.tags || []).join(" ");
        return hay.toLowerCase().indexOf(q) >= 0;
      });
    }
    if (state.tag && state.tag !== "Все") {
      var want = state.tag.toLowerCase();
      list = list.filter(function (item) {
        return (item.tags || []).some(function (t) {
          return normalizeTag(t).toLowerCase() === want;
        });
      });
    }
    return list;
  }

  function updateEmptyState(isEmpty) {
    var empty = el("tpl-empty");
    var title = el("tpl-empty-title");
    var text = el("tpl-empty-text");
    var action = el("tpl-empty-action");
    if (!empty) return;
    if (!isEmpty) {
      empty.hidden = true;
      return;
    }
    empty.hidden = false;
    var hasQuery = state.search || (state.tag && state.tag !== "Все");
    if (state.tab === "marketplace") {
      if (title) title.textContent = tr("templates.market_empty_title");
      if (text) {
        text.textContent = hasQuery
          ? tr("templates.market_empty_search")
          : tr("templates.market_empty_default");
      }
      if (action) {
        action.textContent = tr("templates.market_empty_action");
        action.href = "#";
        action.onclick = function (e) {
          e.preventDefault();
          setTab("local");
        };
      }
    } else {
      if (title) title.textContent = tr("templates.local_empty_title");
      if (text) {
        text.textContent = hasQuery
          ? tr("templates.local_empty_search")
          : tr("templates.local_empty_default");
      }
      if (action) {
        action.textContent = tr("templates.local_empty_action");
        action.href = "/bots/index.html";
        action.onclick = null;
      }
    }
  }

  function setTab(tab) {
    var next = tab === "marketplace" ? "marketplace" : "local";
    state.tab = next;
    document.querySelectorAll(".tpl-tab").forEach(function (btn) {
      var active = btn.getAttribute("data-tab") === next;
      btn.classList.toggle("tpl-tab-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    renderGrid();
  }

  function renderGrid() {
    var grid = el("tpl-grid");
    if (!grid) return;
    renderTagFilters();
    var list = filteredList();
    grid.innerHTML = "";
    if (!list.length) {
      updateEmptyState(true);
      return;
    }
    updateEmptyState(false);

    list.forEach(function (item) {
      var card = document.createElement("article");
      card.className = "tpl-card";
      card.setAttribute("role", "button");
      card.tabIndex = 0;
      var source =
        item.listSource === "local"
          ? "local"
          : item.source === "catalog"
            ? "catalog"
            : "marketplace";
      card.dataset.id = item.id;
      card.dataset.source = source;
      card.innerHTML =
        '<div class="tpl-card-preview">' +
        cardPreviewHtml(item) +
        phantomBadge(item) +
        "</div>" +
        '<div class="tpl-card-body">' +
        "<h3>" +
        escapeHtml(item.name || item.id) +
        "</h3>" +
        '<p class="tpl-card-desc">' +
        escapeHtml(item.description || tr("templates.no_description")) +
        "</p>" +
        '<div class="tpl-card-tags">' +
        tagBadges(item.tags) +
        "</div>" +
        '<div class="tpl-card-meta">' +
        escapeHtml(item.author || "") +
        (item.rating ? " · ★ " + item.rating : "") +
        (item.block_count != null ? " · " + tr("templates.blocks_meta", { n: item.block_count }) : "") +
        "</div>" +
        "</div>";
      card.addEventListener("click", function () {
        openPreviewModal(item.id, card.dataset.source);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openPreviewModal(item.id, card.dataset.source);
        }
      });
      grid.appendChild(card);
    });
  }

  function setStatus(msg, kind) {
    if (kind === "success") {
      msg = "";
      kind = "";
    }
    var node = el("tpl-status");
    if (!node) return;
    if (!msg) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = msg;
    node.className = "tpl-status tpl-status-" + (kind || "info");
  }

  function loadLocal() {
    return fetch(apiBase() + "/templates/local", { headers: authHeaders() })
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("error.load_failed"));
        state.local = (r.data && r.data.templates) || [];
      });
  }

  function loadMarketplace() {
    return fetch(apiBase() + "/templates/marketplace", { headers: authHeaders() })
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("error.load_failed"));
        state.marketplace = (r.data && r.data.templates) || [];
      });
  }

  function loadBotsSelect(selectEl) {
    if (!selectEl) return Promise.resolve();
    return fetch(apiBase() + "/bots/my?user_id=" + encodeURIComponent(userId()), {
      headers: authHeaders(),
    })
      .then(parseResponse)
      .then(function (r) {
        selectEl.innerHTML = '<option value="">' + tr("templates.select_bot") + "</option>";
        if (!r.ok || !Array.isArray(r.data)) return;
        r.data.forEach(function (bot) {
          var opt = document.createElement("option");
          opt.value = String(bot.id);
          opt.textContent = (bot.name || "Bot") + " (#" + bot.id + ")";
          selectEl.appendChild(opt);
        });
      });
  }

  function destroyPreviewViewer() {
    if (state.previewViewer) {
      state.previewViewer.destroy();
      state.previewViewer = null;
    }
  }

  function updateZoomLabel(zoom) {
    var label = el("tpl-zoom-label");
    if (label) label.textContent = Math.round((zoom || 1) * 100) + "%";
  }

  function mountScenarioPreview(item) {
    destroyPreviewViewer();
    var host = el("tpl-preview-graph");
    if (!host || !item) return;
    host.innerHTML = "";
    var scenario = item.scenario || {};
    var blocks = scenario.blocks || [];
    var connections = scenario.connections || [];
    if (!blocks.length) {
      host.innerHTML = '<div class="tpl-preview-empty">' + escapeHtml(tr("templates.graph_empty")) + "</div>";
      updateZoomLabel(1);
      return;
    }
    if (typeof CanvasView !== "undefined" && CanvasView.mountInteractiveGraphPreview) {
      state.previewViewer = CanvasView.mountInteractiveGraphPreview(host, blocks, connections, {
        onZoomChange: updateZoomLabel,
      });
    }
  }

  function openPreviewModal(templateId, source) {
    var modal = el("tpl-preview-modal");
    if (!modal) return;
    fetch(
      apiBase() +
        "/templates/bundle/" +
        encodeURIComponent(templateId) +
        "?source=" +
        encodeURIComponent(source || "local"),
      { headers: authHeaders() }
    )
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("error.load_failed"));
        state.selected = r.data;
        renderPreviewModal();
        modal.hidden = false;
      })
      .catch(function (err) {
        setStatus(err.message || tr("error.load_failed"), "error");
      });
  }

  function renderPreviewModal() {
    var item = state.selected;
    if (!item) return;
    var title = el("tpl-preview-title");
    var desc = el("tpl-preview-desc");
    var steps = el("tpl-preview-steps");
    var warn = el("tpl-preview-warn");
    var installBtn = el("tpl-install-btn");
    var exportBtn = el("tpl-export-btn");
    var deleteBtn = el("tpl-delete-btn");
    var meta = el("tpl-preview-meta");

    if (title) title.textContent = item.name || item.id;
    if (desc) desc.textContent = item.description || "";
    if (meta) {
      meta.innerHTML =
        sourceBadge(item, true) +
        tagBadges(item.tags) +
        '<span class="tpl-meta-pill">' +
        escapeHtml(item.platform || "telegram") +
        "</span>" +
        (item.block_count != null
          ? '<span class="tpl-meta-pill">' + tr("templates.blocks_meta", { n: item.block_count }) + "</span>"
          : "");
    }

    if (steps) {
      var setup = item.setup_steps || [];
      steps.innerHTML = setup.length
        ? "<ol>" +
          setup.map(function (s) {
            return "<li>" + escapeHtml(s) + "</li>";
          }).join("") +
          "</ol>"
        : '<p class="tpl-muted">' + escapeHtml(tr("templates.no_steps")) + "</p>";
    }

    mountScenarioPreview(item);

    if (warn) {
      if (item.has_missing_plugins) {
        warn.hidden = false;
        warn.innerHTML =
          "<strong>" + escapeHtml(tr("templates.missing_plugins")) + "</strong> " +
          escapeHtml((item.missing_plugins || []).join(", ")) +
          " " + escapeHtml(tr("templates.missing_plugins_hint"));
      } else {
        warn.hidden = true;
        warn.textContent = "";
      }
    }

    if (installBtn) {
      var canInstall = item.source !== "marketplace" || item.installable !== false;
      installBtn.disabled = !canInstall;
      installBtn.textContent = canInstall ? tr("templates.install") : tr("templates.install_soon");
    }

    var isLocal = item.source === "local";
    if (exportBtn) exportBtn.hidden = !(isLocal || item.source === "catalog" || (item.source === "marketplace" && item.installable));
    if (deleteBtn) deleteBtn.hidden = !isLocal;

    loadBotsSelect(el("tpl-bot-select"));
  }

  function closePreviewModal() {
    destroyPreviewViewer();
    var modal = el("tpl-preview-modal");
    if (modal) modal.hidden = true;
    state.selected = null;
  }

  function installSelectedTemplate() {
    var item = state.selected;
    var botSel = el("tpl-bot-select");
    if (!item || !botSel) return;
    var botId = botSel.value;
    if (!botId) {
      setStatus(tr("templates.select_bot_install"), "error");
      return;
    }
    var source = item.source === "marketplace" ? "catalog" : item.source || "local";
    setStatus(tr("templates.installing"), "loading");
    fetch(apiBase() + "/templates/import?user_id=" + encodeURIComponent(userId()), {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        template_id: item.id,
        bot_id: parseInt(botId, 10),
        source: source,
      }),
    })
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("templates.install_error"));
        var msg = (r.data && r.data.message) || tr("templates.installed");
        if (r.data && r.data.compilation_warning) {
          msg += " (предупреждение: " + r.data.compilation_warning + ")";
        }
        setStatus(msg, r.data && r.data.phantom_nodes_detected ? "warn" : "success");
        closePreviewModal();
        setTimeout(function () {
          global.location.href =
            "/editor/scenario/index.html?bot_id=" + encodeURIComponent(botId);
        }, 600);
      })
      .catch(function (err) {
        setStatus(err.message || tr("templates.install_error"), "error");
      });
  }

  function exportSelectedTemplate() {
    var item = state.selected;
    if (!item) return;
    var src = resolveExportSource(item);
    if (!src) {
      setStatus(tr("templates.export_error"), "error");
      return;
    }
    setStatus(tr("templates.exporting"), "loading");
    fetch(
      apiBase() +
        "/templates/bundle/" +
        encodeURIComponent(item.id) +
        "?source=" +
        encodeURIComponent(src),
      { headers: authHeaders() }
    )
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("templates.export_error"));
        var data = r.data;
        var bundle = {
          format_version: 1,
          manifest: {
            id: data.id,
            name: data.name || data.id,
            description: data.description || "",
            tags: data.tags || [],
            required_plugins: data.required_plugins || [],
            platform: data.platform || "telegram",
            author: data.author || "BotBuilder",
            created_at: data.created_at || "",
            setup_steps: data.setup_steps || [],
          },
          scenario: data.scenario || {},
          preview_image_base64: data.preview_image_base64 || "",
        };
        var filename = (data.id || "template") + ".bbpack.json";
        var blob = new Blob([JSON.stringify(bundle, null, 2)], {
          type: "application/json;charset=utf-8",
        });
        triggerFileDownload(blob, filename);
        setStatus("", "");
      })
      .catch(function (err) {
        setStatus(err.message || tr("templates.export_error"), "error");
      });
  }

  function deleteSelectedTemplate() {
    var item = state.selected;
    if (!item || item.source !== "local") return;
    if (!global.confirm(tr("templates.delete_confirm", { name: item.name || item.id }))) return;
    fetch(apiBase() + "/templates/local/" + encodeURIComponent(item.id), {
      method: "DELETE",
      headers: authHeaders(),
    })
      .then(parseResponse)
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || tr("templates.delete_error"));
        closePreviewModal();
        return loadLocal();
      })
      .then(function () {
        setTab("local");
        renderGrid();
        setStatus("", "");
      })
      .catch(function (err) {
        setStatus(err.message || tr("templates.delete_error"), "error");
      });
  }

  function importTemplateFile(file) {
    if (!file) return;
    setStatus(tr("templates.importing"), "loading");
    var reader = new FileReader();
    reader.onload = function () {
      var data;
      try {
        data = JSON.parse(String(reader.result || ""));
      } catch (e) {
        setStatus(tr("templates.invalid_json"), "error");
        return;
      }
      fetch(apiBase() + "/templates/upload", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(data),
      })
        .then(parseResponse)
        .then(function (r) {
          if (!r.ok) throw new Error((r.data && r.data.detail) || tr("templates.import_error"));
          return loadLocal();
        })
        .then(function () {
          setTab("local");
          renderGrid();
          setStatus("", "");
        })
        .catch(function (err) {
          setStatus(err.message || tr("templates.import_error"), "error");
        });
    };
    reader.readAsText(file, "UTF-8");
  }

  function refreshAll() {
    state.loading = true;
    return Promise.all([loadLocal(), loadMarketplace()])
      .then(function () {
        renderGrid();
      })
      .catch(function (err) {
        setStatus(err.message || tr("error.load_failed"), "error");
      })
      .finally(function () {
        state.loading = false;
      });
  }

  function bindEvents() {
    document.querySelectorAll(".tpl-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setTab(btn.getAttribute("data-tab") || "local");
      });
    });

    var search = el("tpl-search");
    if (search) {
      search.addEventListener("input", function () {
        state.search = search.value;
        renderGrid();
      });
    }

    el("tpl-refresh-btn") && el("tpl-refresh-btn").addEventListener("click", refreshAll);

    el("tpl-import-btn") &&
      el("tpl-import-btn").addEventListener("click", function () {
        var input = el("tpl-import-file");
        if (input) input.click();
      });

    var importFile = el("tpl-import-file");
    if (importFile) {
      importFile.addEventListener("change", function () {
        if (importFile.files && importFile.files[0]) importTemplateFile(importFile.files[0]);
        importFile.value = "";
      });
    }

    el("tpl-preview-close") && el("tpl-preview-close").addEventListener("click", closePreviewModal);
    document.querySelectorAll("[data-close-tpl-modal]").forEach(function (node) {
      node.addEventListener("click", closePreviewModal);
    });

    el("tpl-install-btn") && el("tpl-install-btn").addEventListener("click", installSelectedTemplate);
    el("tpl-export-btn") && el("tpl-export-btn").addEventListener("click", exportSelectedTemplate);
    el("tpl-delete-btn") && el("tpl-delete-btn").addEventListener("click", deleteSelectedTemplate);

    el("tpl-zoom-in") &&
      el("tpl-zoom-in").addEventListener("click", function () {
        if (state.previewViewer) state.previewViewer.zoomBy(1);
      });
    el("tpl-zoom-out") &&
      el("tpl-zoom-out").addEventListener("click", function () {
        if (state.previewViewer) state.previewViewer.zoomBy(-1);
      });
    el("tpl-zoom-reset") &&
      el("tpl-zoom-reset").addEventListener("click", function () {
        if (state.previewViewer) state.previewViewer.reset();
      });
  }

  function init() {
    if (typeof CanvasView !== "undefined" && CanvasView.loadPlugins) {
      CanvasView.loadPlugins().finally(refreshAll);
    } else {
      refreshAll();
    }
    bindEvents();
    var params = new URLSearchParams(global.location.search || "");
    var tabParam = params.get("tab");
    if (tabParam === "marketplace" || tabParam === "local") {
      setTab(tabParam);
    }
    var highlight = params.get("highlight");
    if (highlight) openPreviewModal(highlight, tabParam === "marketplace" ? "catalog" : "local");

    document.addEventListener("botbuilder:langchange", function () {
      renderGrid();
      if (state.selected) renderPreviewModal();
    });
  }

  global.TemplateLibraryView = {
    init: init,
    refreshAll: refreshAll,
    openPreview: openPreviewModal,
  };
})(typeof window !== "undefined" ? window : globalThis);
