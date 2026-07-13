/**
 * PluginManagerView — каталог всех плагинов (встроенные только просмотр).
 */
(function (global) {
  "use strict";

  var state = { root: null, plugins: [], filter: "all" };

  function apiBase() {
    if (typeof global.getApiBase === "function") return global.getApiBase();
    if (global.location && global.location.origin) return global.location.origin + "/api";
    return "http://127.0.0.1:8000/api";
  }

  function pluginUrl(id) {
    if (typeof global.apiUrl === "function") return global.apiUrl("/plugins/" + encodeURIComponent(id));
    return apiBase().replace(/\/$/, "") + "/plugins/" + encodeURIComponent(id);
  }

  function resolveId(plugin) {
    if (typeof global.resolvePluginId === "function") return global.resolvePluginId(plugin);
    return plugin.pluginId || plugin.id || plugin.type || "";
  }

  function isBuiltin(plugin) {
    var id = resolveId(plugin);
    if (typeof global.isBuiltinPluginId === "function") {
      return global.isBuiltinPluginId(id, plugin);
    }
    return !!plugin.builtin;
  }

  function enrichPlugins(list) {
    return (list || []).map(function (p) {
      var copy = Object.assign({}, p);
      copy.pluginId = resolveId(copy);
      copy.builtin = isBuiltin(copy);
      copy.editable = !copy.builtin;
      return copy;
    });
  }

  function openPlugin(plugin) {
    var id = plugin.pluginId || plugin.id;
    if (!id) return;
    if (isBuiltin(plugin)) {
      global.location.href = "/plugin-builder/?view=" + encodeURIComponent(id);
    } else {
      global.location.href = "/plugin-builder/?edit=" + encodeURIComponent(id);
    }
  }

  function renderList() {
    var grid = state.root.querySelector("#plg-grid");
    var status = state.root.querySelector("#plg-status");
    if (!grid) return;

    var list = state.plugins.slice();
    if (state.filter === "builtin") list = list.filter(function (p) { return isBuiltin(p); });
    if (state.filter === "custom") list = list.filter(function (p) { return !isBuiltin(p); });

    grid.innerHTML = "";
    if (!list.length) {
      grid.innerHTML = '<div class="plg-empty">' + (typeof t === "function" ? t("plugins.empty") : "No plugins in this category.") + "</div>";
      return;
    }

    list.forEach(function (plugin) {
      var id = resolveId(plugin);
      var card = document.createElement("a");
      card.className = "plg-card";
      card.href =
        isBuiltin(plugin)
          ? "/plugin-builder/?view=" + encodeURIComponent(id)
          : "/plugin-builder/?edit=" + encodeURIComponent(id);
      var color = plugin.color || "#2563eb";
      var builtin = isBuiltin(plugin);
      var badgeClass = builtin ? "plg-badge-builtin" : "plg-badge-custom";
      var badgeText = builtin
        ? (typeof t === "function" ? t("plugins.badge_builtin") : "Built-in · view only")
        : (typeof t === "function" ? t("plugins.badge_custom") : "Custom · editable");
      card.innerHTML =
        '<div class="plg-card-head">' +
        '<div class="plg-card-icon" style="background:' + color + '">' + (plugin.icon || "🧩") + "</div>" +
        '<span class="plg-badge ' + badgeClass + '">' + badgeText + "</span>" +
        "</div>" +
        "<h3 class=\"plg-card-title\">" + escapeHtml(plugin.name || id) + "</h3>" +
        '<div class="plg-card-meta">id: ' + escapeHtml(id) + " · type: " + escapeHtml(plugin.type || "—") + "</div>" +
        (plugin.description ? '<div class="plg-card-meta" style="margin-top:6px">' + escapeHtml(plugin.description) + "</div>" : "");
      grid.appendChild(card);
    });

    if (status) {
      status.textContent =
        typeof t === "function"
          ? t("plugins.total", { total: state.plugins.length, shown: list.length })
          : "Total: " + state.plugins.length + " · shown: " + list.length;
      status.className = "plg-status";
    }
  }

  function escapeHtml(v) {
    return String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setFilter(filter) {
    state.filter = filter;
    state.root.querySelectorAll(".plg-filter").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-filter") === filter);
    });
    renderList();
  }

  function loadPlugins() {
    var status = state.root.querySelector("#plg-status");
    if (status) {
      status.textContent = typeof t === "function" ? t("loading") : "Loading…";
      status.className = "plg-status";
    }
    fetch(apiBase().replace(/\/$/, "") + "/plugins")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        state.plugins = enrichPlugins(data.plugins || []);
        if (typeof PluginI18n !== "undefined" && PluginI18n.localizePluginRegistry) {
          state.plugins = PluginI18n.localizePluginRegistry(state.plugins);
        }
        renderList();
      })
      .catch(function (err) {
        if (status) {
          var prefix = typeof t === "function" ? t("plugins.load_error") : "Failed to load list";
          status.textContent = prefix + ": " + (err.message || err);
          status.className = "plg-status error";
        }
      });
  }

  function mount(root) {
    root.innerHTML =
      '<div class="dashboard">' +
      '<header class="dashboard-header">' +
      '<a class="header-back" href="/dashboard/index.html" data-i18n-aria="nav.back_home" aria-label="Main menu">←</a>' +
      '<h1 class="page-title" data-i18n="plugins.title">Plugins</h1>' +
      "</header>" +
      '<main class="dashboard-content plg-main">' +
      '<div class="plg-filters">' +
      '<button type="button" class="plg-filter active" data-filter="all" data-i18n="plugins.all">All</button>' +
      '<button type="button" class="plg-filter" data-filter="custom" data-i18n="plugins.custom">Custom</button>' +
      '<button type="button" class="plg-filter" data-filter="builtin" data-i18n="plugins.builtin">Built-in</button>' +
      '<a class="plg-btn plg-btn-primary plg-filters-action" href="/plugin-builder/" data-i18n="plugins.new">+ New component</a>' +
      "</div>" +
      '<div id="plg-grid" class="plg-grid"></div>' +
      '<div id="plg-status" class="plg-status"></div>' +
      "</main></div>";

    if (typeof applyLanguage === "function") {
      applyLanguage(getLang(), { silent: true });
    }

    root.querySelectorAll(".plg-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setFilter(btn.getAttribute("data-filter") || "all");
      });
    });
  }

  function init(options) {
    state.root = (options && options.root) || document.getElementById("plugins-root");
    if (!state.root) return;
    mount(state.root);
    loadPlugins();
    document.addEventListener("botbuilder:langchange", function () {
      mount(state.root);
      loadPlugins();
    });
  }

  global.PluginManagerView = { init: init };
})(typeof window !== "undefined" ? window : globalThis);
