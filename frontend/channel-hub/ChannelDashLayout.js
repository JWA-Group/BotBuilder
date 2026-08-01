/**
 * ChannelDashLayout — drag-and-drop analytics dashboard grid + persistence.
 */
(function (global) {
  "use strict";

  var STORAGE_PREFIX = "ch_dash_layout_v1_";
  var SIZES = {
    sm: { key: "sm", col: 4, labelKey: "channel_hub.dash_size_sm" },
    md: { key: "md", col: 6, labelKey: "channel_hub.dash_size_md" },
    lg: { key: "lg", col: 12, labelKey: "channel_hub.dash_size_lg" },
  };

  var CATALOG = [
    {
      type: "growth",
      icon: "growth",
      titleKey: "channel_hub.dash_w_growth",
      descKey: "channel_hub.dash_w_growth_desc",
      defaultSize: "lg",
      sizes: ["md", "lg"],
    },
    {
      type: "hours",
      icon: "hours",
      titleKey: "channel_hub.dash_w_hours",
      descKey: "channel_hub.dash_w_hours_desc",
      defaultSize: "md",
      sizes: ["sm", "md", "lg"],
    },
    {
      type: "tags",
      icon: "tags",
      titleKey: "channel_hub.dash_w_tags",
      descKey: "channel_hub.dash_w_tags_desc",
      defaultSize: "sm",
      sizes: ["sm", "md", "lg"],
    },
    {
      type: "feed",
      icon: "feed",
      titleKey: "channel_hub.dash_w_feed",
      descKey: "channel_hub.dash_w_feed_desc",
      defaultSize: "lg",
      sizes: ["md", "lg"],
    },
    {
      type: "metrics",
      icon: "metrics",
      titleKey: "channel_hub.dash_w_metrics",
      descKey: "channel_hub.dash_w_metrics_desc",
      defaultSize: "md",
      sizes: ["sm", "md", "lg"],
    },
    {
      type: "warnings",
      icon: "warnings",
      titleKey: "channel_hub.dash_w_warnings",
      descKey: "channel_hub.dash_w_warnings_desc",
      defaultSize: "md",
      sizes: ["sm", "md", "lg"],
    },
    {
      type: "posts",
      icon: "posts",
      titleKey: "channel_hub.dash_w_posts",
      descKey: "channel_hub.dash_w_posts_desc",
      defaultSize: "lg",
      sizes: ["md", "lg"],
    },
    {
      type: "moderation",
      icon: "moderation",
      titleKey: "channel_hub.dash_w_moderation",
      descKey: "channel_hub.dash_w_moderation_desc",
      defaultSize: "sm",
      sizes: ["sm", "md", "lg"],
    },
  ];

  function widgetIconHtml(iconName) {
    if (global.BBIcons && typeof global.BBIcons.renderCardIcon === "function") {
      return global.BBIcons.renderCardIcon(iconName);
    }
    return '<div class="menu-icon-badge menu-icon-theme-blue" aria-hidden="true"></div>';
  }

  var state = {
    layout: [],
    editMode: false,
    botId: "",
    dragId: null,
    dropIndex: null,
    pendingType: null,
    pendingSize: "md",
    onChange: null,
  };

  function tr(key) {
    return typeof global.t === "function" ? global.t(key) : key;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function catalogItem(type) {
    for (var i = 0; i < CATALOG.length; i++) {
      if (CATALOG[i].type === type) return CATALOG[i];
    }
    return null;
  }

  function uid() {
    return "w_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
  }

  function storageKey(botId) {
    return STORAGE_PREFIX + String(botId || "default");
  }

  function normalizeLayout(raw) {
    if (!Array.isArray(raw)) return [];
    return raw
      .filter(function (item) {
        return item && item.id && item.widgetType && catalogItem(item.widgetType);
      })
      .map(function (item, idx) {
        var meta = catalogItem(item.widgetType);
        var size = SIZES[item.size] ? item.size : meta.defaultSize;
        if (meta.sizes.indexOf(size) < 0) size = meta.defaultSize;
        return {
          id: String(item.id),
          widgetType: item.widgetType,
          size: size,
          positionIndex: typeof item.positionIndex === "number" ? item.positionIndex : idx,
          settings: item.settings && typeof item.settings === "object" ? item.settings : {},
        };
      })
      .sort(function (a, b) {
        return a.positionIndex - b.positionIndex;
      })
      .map(function (item, idx) {
        item.positionIndex = idx;
        return item;
      });
  }

  function loadLayout(botId) {
    try {
      var raw = localStorage.getItem(storageKey(botId));
      if (!raw) return [];
      return normalizeLayout(JSON.parse(raw));
    } catch (e) {
      return [];
    }
  }

  function saveLayout() {
    try {
      localStorage.setItem(storageKey(state.botId), JSON.stringify(state.layout));
    } catch (e) {}
  }

  function notifyChange() {
    if (typeof state.onChange === "function") {
      try {
        state.onChange(state.layout.slice());
      } catch (e) {}
    }
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function viewSwitchHtml(switchKey, active) {
    var pieActive = active === "pie" || active === "donut";
    return (
      '<div class="ch-view-switch" data-switch="' +
      escapeHtml(switchKey) +
      '" role="group">' +
      '<button type="button" class="ch-view-btn' +
      (!pieActive ? " ch-view-active" : "") +
      '" data-view="bar" data-i18n="channel_hub.view_bar">Bar</button>' +
      '<button type="button" class="ch-view-btn' +
      (pieActive ? " ch-view-active" : "") +
      '" data-view="pie" data-i18n="channel_hub.view_pie">Pie</button>' +
      "</div>"
    );
  }

  function bodyHtml(type, id) {
    if (type === "growth") {
      return (
        '<div class="an-chart-wrap ch-dash-chart">' +
        '<canvas data-ch-canvas="growth" data-widget-id="' +
        escapeHtml(id) +
        '"></canvas></div>'
      );
    }
    if (type === "hours") {
      return (
        '<div class="ch-dash-widget-tools">' +
        viewSwitchHtml("activity", "bar") +
        "</div>" +
        '<div class="an-chart-wrap ch-dash-chart">' +
        '<canvas data-ch-canvas="hours" data-widget-id="' +
        escapeHtml(id) +
        '"></canvas></div>'
      );
    }
    if (type === "tags") {
      return (
        '<div class="ch-dash-widget-tools">' +
        viewSwitchHtml("tags", "pie") +
        "</div>" +
        '<div class="an-chart-wrap ch-dash-chart">' +
        '<canvas data-ch-canvas="tags" data-widget-id="' +
        escapeHtml(id) +
        '"></canvas></div>'
      );
    }
    if (type === "moderation") {
      return (
        '<div class="ch-dash-widget-tools">' +
        viewSwitchHtml("moderation", "pie") +
        "</div>" +
        '<div class="an-chart-wrap ch-dash-chart">' +
        '<canvas data-ch-canvas="moderation" data-widget-id="' +
        escapeHtml(id) +
        '"></canvas></div>'
      );
    }
    if (type === "metrics") {
      return (
        '<div class="ch-dash-metrics" aria-label="KPI">' +
        '<article class="ch-dash-metric"><p class="an-kpi-label" data-i18n="channel_hub.kpi_subscribers">Subscribers</p>' +
        '<div class="an-kpi-value" data-kpi="subscribers">—</div></article>' +
        '<article class="ch-dash-metric"><p class="an-kpi-label" data-i18n="channel_hub.kpi_joins">Joins today</p>' +
        '<div class="an-kpi-value" data-kpi="joins">—</div></article>' +
        '<article class="ch-dash-metric"><p class="an-kpi-label" data-i18n="channel_hub.kpi_leaves">Leaves today</p>' +
        '<div class="an-kpi-value" data-kpi="leaves">—</div></article>' +
        '<article class="ch-dash-metric"><p class="an-kpi-label" data-i18n="channel_hub.kpi_err">Engagement index</p>' +
        '<div class="an-kpi-value" data-kpi="err">—</div></article>' +
        '<article class="ch-dash-metric"><p class="an-kpi-label" data-i18n="channel_hub.kpi_moderated">Comments moderated</p>' +
        '<div class="an-kpi-value" data-kpi="moderated">—</div></article>' +
        "</div>"
      );
    }
    if (type === "feed") {
      return '<div class="ch-dash-feed-list" data-ch-feed="1" data-widget-id="' + escapeHtml(id) + '"></div>';
    }
    if (type === "warnings") {
      return '<div class="ch-dash-warnings" data-ch-warnings="1" data-widget-id="' + escapeHtml(id) + '"></div>';
    }
    if (type === "posts") {
      return (
        '<div class="ch-dash-posts-toolbar">' +
        '<input type="search" class="db-input ch-posts-search" data-ch-posts-search="1" ' +
        'data-i18n-placeholder="channel_hub.posts_search" placeholder="Search posts…" />' +
        "</div>" +
        '<div class="ch-table-wrap ch-dash-table-wrap">' +
        '<table class="ch-table ch-posts-compact ch-dash-posts-table">' +
        "<thead><tr>" +
        '<th><button type="button" class="ch-sort-btn" data-sort="message_id" data-i18n="channel_hub.col_post_id">Post ID</button></th>' +
        '<th data-i18n="channel_hub.col_link">Link</th>' +
        '<th><button type="button" class="ch-sort-btn" data-sort="views_count" data-i18n="channel_hub.col_views">Views</button></th>' +
        '<th><button type="button" class="ch-sort-btn" data-sort="comments_count" data-i18n="channel_hub.col_comments">Comments</button></th>' +
        '<th><button type="button" class="ch-sort-btn ch-sort-active" data-sort="engagement" data-i18n="channel_hub.col_engagement">Engagement</button></th>' +
        "</tr></thead><tbody></tbody></table></div>"
      );
    }
    return "";
  }

  function sizeOptionsHtml(meta, current) {
    return (meta.sizes || ["sm", "md", "lg"])
      .map(function (sz) {
        return (
          '<option value="' +
          sz +
          '"' +
          (sz === current ? " selected" : "") +
          ">" +
          escapeHtml(tr(SIZES[sz].labelKey)) +
          "</option>"
        );
      })
      .join("");
  }

  function widgetCardHtml(item) {
    var meta = catalogItem(item.widgetType);
    if (!meta) return "";
    var col = SIZES[item.size] ? SIZES[item.size].col : 6;
    return (
      '<article class="ch-dash-widget ch-glass-card an-panel" draggable="false" ' +
      'data-widget-id="' +
      escapeHtml(item.id) +
      '" data-widget-type="' +
      escapeHtml(item.widgetType) +
      '" data-size="' +
      escapeHtml(item.size) +
      '" style="--ch-col-span:' +
      col +
      '">' +
      '<header class="ch-dash-widget-head">' +
      '<div class="ch-dash-widget-title">' +
      '<span class="ch-dash-drag-handle" title="Drag" aria-hidden="true">⠿</span>' +
      '<span class="ch-dash-widget-icon">' +
      widgetIconHtml(meta.icon) +
      "</span>" +
      "<div><h2>" +
      escapeHtml(tr(meta.titleKey)) +
      "</h2>" +
      '<p class="an-panel-sub">' +
      escapeHtml(tr(meta.descKey)) +
      "</p></div></div>" +
      '<div class="ch-dash-widget-actions">' +
      '<label class="ch-dash-resize">' +
      '<span class="ch-dash-action-label" data-i18n="channel_hub.dash_resize">Resize</span>' +
      '<select class="db-input ch-dash-size-select" data-act="resize" aria-label="Resize">' +
      sizeOptionsHtml(meta, item.size) +
      "</select></label>" +
      '<button type="button" class="db-btn-secondary ch-btn-sm" data-act="remove" data-i18n="channel_hub.dash_remove">Remove</button>' +
      "</div></header>" +
      '<div class="ch-dash-widget-body">' +
      bodyHtml(item.widgetType, item.id) +
      "</div></article>"
    );
  }

  function destroyAllWidgetCharts() {
    if (global.ChannelHubView && typeof global.ChannelHubView.destroyDashboardCharts === "function") {
      global.ChannelHubView.destroyDashboardCharts();
    }
  }

  function applyI18nSafe(root) {
    if (typeof global.applyI18n === "function") {
      try {
        global.applyI18n(root || document);
      } catch (e) {}
    }
  }

  function hydrateEmptyIcon() {
    var node = el("ch-dash-empty-icon");
    if (!node || node.getAttribute("data-hydrated") === "1") return;
    if (!global.BBIcons || typeof global.BBIcons.renderCardIcon !== "function") return;
    node.innerHTML = global.BBIcons.renderCardIcon("bot_analytics");
    node.setAttribute("data-hydrated", "1");
  }

  function syncEmptyState() {
    var empty = el("ch-dash-empty");
    var grid = el("ch-dash-grid");
    var has = state.layout.length > 0;
    // Empty onboarding only when there are zero widgets (never under a filled grid).
    if (empty) {
      empty.hidden = has;
      empty.setAttribute("aria-hidden", has ? "true" : "false");
      empty.classList.toggle("is-visible", !has);
      if (!has) hydrateEmptyIcon();
    }
    if (grid) {
      grid.hidden = !has;
      grid.classList.toggle("is-visible", has);
    }
  }

  function syncEditUi() {
    var root = el("ch-dash-workspace");
    var toggle = el("ch-dash-edit-toggle");
    if (root) root.classList.toggle("is-editing", !!state.editMode);
    if (toggle) {
      toggle.classList.toggle("ch-dash-edit-active", !!state.editMode);
      toggle.setAttribute("aria-pressed", state.editMode ? "true" : "false");
    }
    document.querySelectorAll(".ch-dash-widget").forEach(function (card) {
      card.draggable = false;
    });
  }

  function bindWidgetCard(card) {
    var id = card.getAttribute("data-widget-id");
    card.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var act = btn.getAttribute("data-act");
        if (act === "remove") removeWidget(id);
      });
    });
    var sel = card.querySelector(".ch-dash-size-select");
    if (sel) {
      sel.addEventListener("change", function (e) {
        e.stopPropagation();
        resizeWidget(id, sel.value);
      });
      sel.addEventListener("mousedown", function (e) {
        e.stopPropagation();
      });
    }

    var handle = card.querySelector(".ch-dash-drag-handle");
    if (handle) {
      handle.addEventListener("mousedown", function () {
        card.draggable = !!state.editMode;
      });
      handle.addEventListener("mouseup", function () {
        card.draggable = false;
      });
    }
    card.addEventListener("dragstart", function (e) {
      if (!state.editMode) {
        e.preventDefault();
        return;
      }
      state.dragId = id;
      card.classList.add("is-dragging");
      try {
        e.dataTransfer.setData("text/plain", id);
        e.dataTransfer.effectAllowed = "move";
      } catch (err) {}
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("is-dragging");
      card.draggable = false;
      state.dragId = null;
      state.dropIndex = null;
      clearDropHints();
    });
  }

  function clearDropHints() {
    document.querySelectorAll(".ch-dash-widget.is-drop-target").forEach(function (n) {
      n.classList.remove("is-drop-target");
    });
    var ph = el("ch-dash-placeholder");
    if (ph) ph.remove();
  }

  function indexOfWidget(id) {
    for (var i = 0; i < state.layout.length; i++) {
      if (state.layout[i].id === id) return i;
    }
    return -1;
  }

  function moveWidget(fromId, toIndex) {
    var from = indexOfWidget(fromId);
    if (from < 0) return;
    if (toIndex < 0) toIndex = 0;
    if (toIndex > state.layout.length) toIndex = state.layout.length;
    if (from === toIndex || from + 1 === toIndex) return;
    var item = state.layout.splice(from, 1)[0];
    if (toIndex > from) toIndex -= 1;
    state.layout.splice(toIndex, 0, item);
    state.layout.forEach(function (w, i) {
      w.positionIndex = i;
    });
    saveLayout();
    renderGrid();
    notifyChange();
  }

  function bindGridDnD(grid) {
    grid.addEventListener("dragover", function (e) {
      if (!state.editMode || !state.dragId) return;
      e.preventDefault();
      var card = e.target.closest(".ch-dash-widget");
      clearDropHints();
      if (card && card.getAttribute("data-widget-id") !== state.dragId) {
        card.classList.add("is-drop-target");
        state.dropIndex = indexOfWidget(card.getAttribute("data-widget-id"));
      } else if (!card) {
        state.dropIndex = state.layout.length;
        if (!el("ch-dash-placeholder")) {
          var ph = document.createElement("div");
          ph.id = "ch-dash-placeholder";
          ph.className = "ch-dash-placeholder";
          ph.textContent = tr("channel_hub.dash_drop_here");
          grid.appendChild(ph);
        }
      }
    });
    grid.addEventListener("drop", function (e) {
      if (!state.editMode || !state.dragId) return;
      e.preventDefault();
      var targetCard = e.target.closest(".ch-dash-widget");
      var toIndex = state.layout.length;
      if (targetCard) {
        toIndex = indexOfWidget(targetCard.getAttribute("data-widget-id"));
      }
      moveWidget(state.dragId, toIndex);
      clearDropHints();
    });
  }

  function renderGrid() {
    var grid = el("ch-dash-grid");
    if (!grid) return;
    destroyAllWidgetCharts();
    grid.innerHTML = state.layout.map(widgetCardHtml).join("");
    grid.querySelectorAll(".ch-dash-widget").forEach(bindWidgetCard);
    syncEmptyState();
    syncEditUi();
    applyI18nSafe(grid);
    // Re-bind view switches / posts search that live inside widgets
    if (global.ChannelHubView && typeof global.ChannelHubView.bindDashboardWidgets === "function") {
      global.ChannelHubView.bindDashboardWidgets(grid);
    }
  }

  function removeWidget(id) {
    var idx = indexOfWidget(id);
    if (idx < 0) return;
    if (global.ChannelHubView && typeof global.ChannelHubView.destroyWidgetChart === "function") {
      global.ChannelHubView.destroyWidgetChart(id);
    }
    state.layout.splice(idx, 1);
    state.layout.forEach(function (w, i) {
      w.positionIndex = i;
    });
    saveLayout();
    renderGrid();
    notifyChange();
  }

  function resizeWidget(id, size) {
    var idx = indexOfWidget(id);
    if (idx < 0 || !SIZES[size]) return;
    var meta = catalogItem(state.layout[idx].widgetType);
    if (!meta || meta.sizes.indexOf(size) < 0) return;
    state.layout[idx].size = size;
    saveLayout();
    renderGrid();
    notifyChange();
  }

  function setEditMode(on) {
    state.editMode = !!on;
    syncEditUi();
    syncEmptyState();
  }

  function openCatalog() {
    var modal = el("ch-dash-catalog");
    if (!modal) return;
    state.pendingType = null;
    state.pendingSize = "md";
    renderCatalogList();
    renderSizePicker();
    modal.hidden = false;
    applyI18nSafe(modal);
  }

  function closeCatalog() {
    var modal = el("ch-dash-catalog");
    if (modal) modal.hidden = true;
    state.pendingType = null;
  }

  function renderCatalogList() {
    var list = el("ch-dash-catalog-list");
    if (!list) return;
    list.innerHTML = CATALOG.map(function (item) {
      var active = state.pendingType === item.type;
      return (
        '<button type="button" class="ch-dash-catalog-item' +
        (active ? " is-active" : "") +
        '" data-type="' +
        escapeHtml(item.type) +
        '">' +
        '<span class="ch-dash-catalog-icon">' +
        widgetIconHtml(item.icon) +
        "</span>" +
        '<span class="ch-dash-catalog-copy"><strong>' +
        escapeHtml(tr(item.titleKey)) +
        "</strong><span>" +
        escapeHtml(tr(item.descKey)) +
        "</span></span></button>"
      );
    }).join("");
    list.querySelectorAll(".ch-dash-catalog-item").forEach(function (btn) {
      btn.onclick = function () {
        var type = btn.getAttribute("data-type");
        var meta = catalogItem(type);
        state.pendingType = type;
        state.pendingSize = meta ? meta.defaultSize : "md";
        renderCatalogList();
        renderSizePicker();
      };
    });
  }

  function renderSizePicker() {
    var wrap = el("ch-dash-size-picker");
    var addBtn = el("ch-dash-add-confirm");
    if (!wrap) return;
    var meta = catalogItem(state.pendingType);
    if (!meta) {
      wrap.innerHTML = '<p class="ps-hint ch-dash-hint">' + escapeHtml(tr("channel_hub.dash_pick_widget")) + "</p>";
      if (addBtn) addBtn.disabled = true;
      return;
    }
    if (addBtn) addBtn.disabled = false;
    wrap.innerHTML =
      '<p class="ch-dash-size-label" data-i18n="channel_hub.dash_choose_size">Choose size</p>' +
      '<div class="ch-dash-size-options" role="group">' +
      meta.sizes
        .map(function (sz) {
          return (
            '<button type="button" class="ch-dash-size-btn' +
            (state.pendingSize === sz ? " is-active" : "") +
            '" data-size="' +
            sz +
            '">' +
            escapeHtml(tr(SIZES[sz].labelKey)) +
            "</button>"
          );
        })
        .join("") +
      "</div>";
    wrap.querySelectorAll(".ch-dash-size-btn").forEach(function (btn) {
      btn.onclick = function () {
        state.pendingSize = btn.getAttribute("data-size") || meta.defaultSize;
        renderSizePicker();
      };
    });
    applyI18nSafe(wrap);
  }

  function addPendingWidget() {
    var meta = catalogItem(state.pendingType);
    if (!meta) return;
    var size = state.pendingSize;
    if (meta.sizes.indexOf(size) < 0) size = meta.defaultSize;
    state.layout.push({
      id: uid(),
      widgetType: meta.type,
      size: size,
      positionIndex: state.layout.length,
      settings: {},
    });
    saveLayout();
    closeCatalog();
    setEditMode(true);
    renderGrid();
    notifyChange();
  }

  function resetLayout() {
    state.layout = [];
    saveLayout();
    setEditMode(false);
    renderGrid();
    notifyChange();
  }

  function openResetModal() {
    var modal = el("ch-dash-reset-modal");
    if (modal) modal.hidden = false;
  }

  function closeResetModal() {
    var modal = el("ch-dash-reset-modal");
    if (modal) modal.hidden = true;
  }

  function setBotId(botId) {
    var next = String(botId || "");
    if (next === state.botId && state.layout) {
      return;
    }
    state.botId = next;
    state.layout = loadLayout(next);
    renderGrid();
    notifyChange();
  }

  function bind() {
    var addBtn = el("ch-dash-add");
    if (addBtn) addBtn.onclick = openCatalog;
    var emptyAdd = el("ch-dash-empty-add");
    if (emptyAdd) emptyAdd.onclick = openCatalog;
    var editBtn = el("ch-dash-edit-toggle");
    if (editBtn) {
      editBtn.onclick = function () {
        setEditMode(!state.editMode);
      };
    }
    var resetBtn = el("ch-dash-reset");
    if (resetBtn) resetBtn.onclick = openResetModal;
    var grid = el("ch-dash-grid");
    if (grid) bindGridDnD(grid);

    var catalog = el("ch-dash-catalog");
    if (catalog) {
      catalog.querySelectorAll("[data-close-catalog]").forEach(function (n) {
        n.onclick = closeCatalog;
      });
    }
    var confirmAdd = el("ch-dash-add-confirm");
    if (confirmAdd) confirmAdd.onclick = addPendingWidget;

    var resetModal = el("ch-dash-reset-modal");
    if (resetModal) {
      resetModal.querySelectorAll("[data-close-reset]").forEach(function (n) {
        n.onclick = closeResetModal;
      });
    }
    var resetConfirm = el("ch-dash-reset-confirm");
    if (resetConfirm) {
      resetConfirm.onclick = function () {
        closeResetModal();
        resetLayout();
      };
    }

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      closeCatalog();
      closeResetModal();
    });
  }

  function init(opts) {
    opts = opts || {};
    state.onChange = opts.onChange || null;
    state.botId = String(opts.botId || "");
    state.layout = loadLayout(state.botId);
    state.editMode = false;
    bind();
    renderGrid();
    // Module icons may arrive after classic scripts — refresh badges once ready.
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (global.BBIcons || tries > 40) {
        clearInterval(timer);
        if (global.BBIcons && !state.iconsReady) {
          state.iconsReady = true;
          hydrateEmptyIcon();
          renderGrid();
        }
      }
    }, 50);
  }

  global.ChannelDashLayout = {
    init: init,
    setBotId: setBotId,
    getLayout: function () {
      return state.layout.slice();
    },
    isEditMode: function () {
      return !!state.editMode;
    },
    setEditMode: setEditMode,
    render: renderGrid,
    openCatalog: openCatalog,
  };
})(window);
