/**
 * DatabaseStudio — SSMS/DBeaver-style explorer + ERD + data grid for bot user_data.db
 */
(function (global) {
  "use strict";

  var TAB_ERD = "__erd__";

  function tr(key, fallback) {
    if (typeof global.t === "function") {
      var v = global.t(key);
      if (v && v !== key) return v;
    }
    return fallback || key;
  }

  function apiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    return (global.location && global.location.origin) || "http://127.0.0.1:8000";
  }

  function authHeaders(json) {
    var h =
      typeof global.jsonApiHeaders === "function"
        ? global.jsonApiHeaders()
        : { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    try {
      var token =
        (global.localStorage &&
          (global.localStorage.getItem("access_token") ||
            global.localStorage.getItem("token"))) ||
        "";
      if (token && !h.Authorization) h.Authorization = "Bearer " + token;
    } catch (e) {}
    return h;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function iconTable() {
    return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18v14H3z"/><path d="M3 10h18M9 5v14"/></svg>';
  }

  function DatabaseStudio(opts) {
    this.botId = String((opts && opts.botId) || global.bot_id || "");
    this.rootEl = null;
    this.schema = null;
    this.tables = [];
    this.features = { core: true };
    this.filter = "";
    this.activeTab = TAB_ERD;
    this.openTabs = [{ id: TAB_ERD, title: tr("ds.tab.erd", "Schema Diagram") }];
    this.gridByTable = {};
    this.gridLimitByTable = {};
    this.defaultGridLimit = 100;
    this.pendingEdits = {};
    this.selectedRows = {};
    this._mounted = false;
    this._onDocClick = this._onDocClick.bind(this);
    this._erdScale = 1;
    this._erdMin = 0.25;
    this._erdMax = 2.5;
    this._erdNaturalW = 640;
    this._erdNaturalH = 480;
  }

  DatabaseStudio.prototype.mount = function (root) {
    var el =
      typeof root === "string" ? document.querySelector(root) : root || document.getElementById("ds-root");
    if (!el) return this;
    this.rootEl = el;
    this._mounted = true;
    el.classList.add("ds-root");
    el.innerHTML = this._shellHtml();
    this._bindShell();
    document.addEventListener("click", this._onDocClick);
    this.reloadSchema();
    return this;
  };

  DatabaseStudio.prototype.destroy = function () {
    this._mounted = false;
    document.removeEventListener("click", this._onDocClick);
    this._hideCtx();
    if (this.rootEl) this.rootEl.innerHTML = "";
  };

  DatabaseStudio.prototype._shellHtml = function () {
    return (
      '<aside class="ds-explorer" id="ds-explorer">' +
      '<div class="ds-explorer-inner">' +
      '<div class="ds-explorer-head">' +
      '<p class="ds-explorer-title">' +
      escapeHtml(tr("ds.explorer", "Database Explorer")) +
      "</p>" +
      '<div class="ds-feature-chips" id="ds-feature-chips" hidden></div>' +
      '<input type="search" class="ds-search" id="ds-search" placeholder="' +
      escapeHtml(tr("ds.search", "Filter tables…")) +
      '" />' +
      "</div>" +
      '<ul class="ds-table-list" id="ds-table-list"></ul>' +
      "</div></aside>" +
      '<section class="ds-main">' +
      '<div class="ds-tabs" id="ds-tabs"></div>' +
      '<div class="ds-workspace" id="ds-workspace"></div>' +
      '<div class="ds-error-bar" id="ds-error-bar" role="alert">' +
      "<div><strong>" +
      escapeHtml(tr("ds.error", "Error")) +
      ':</strong> <span id="ds-error-text"></span></div>' +
      '<button type="button" class="ds-error-dismiss" id="ds-error-dismiss" aria-label="Dismiss">×</button>' +
      "</div></section>" +
      '<div class="ds-ctx" id="ds-ctx" hidden></div>'
    );
  };

  DatabaseStudio.prototype._bindShell = function () {
    var self = this;
    var search = document.getElementById("ds-search");
    if (search) {
      search.addEventListener("input", function () {
        self.filter = search.value || "";
        self._renderExplorer();
      });
    }
    var dismiss = document.getElementById("ds-error-dismiss");
    if (dismiss) {
      dismiss.addEventListener("click", function () {
        self.clearError();
      });
    }
  };

  DatabaseStudio.prototype.showError = function (msg) {
    var bar = document.getElementById("ds-error-bar");
    var text = document.getElementById("ds-error-text");
    if (text) text.textContent = String(msg || tr("ds.unknown_error", "Unknown error"));
    if (bar) bar.classList.add("is-visible");
  };

  DatabaseStudio.prototype.clearError = function () {
    var bar = document.getElementById("ds-error-bar");
    if (bar) bar.classList.remove("is-visible");
  };

  DatabaseStudio.prototype.reloadSchema = function () {
    var self = this;
    if (!this.botId) {
      this.showError(tr("editor.db.no_bot_id", "No bot_id in URL"));
      return Promise.resolve();
    }
    return fetch(apiOrigin() + "/api/projects/" + encodeURIComponent(this.botId) + "/db/schema", {
      headers: authHeaders(),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.showError((res.data && (res.data.detail || res.data.error)) || "Schema load failed");
          return;
        }
        self.schema = res.data;
        self.tables = (res.data && res.data.tables) || [];
        self.features = (res.data && res.data.features) || { core: true };
        self.clearError();
        self._renderFeatureChips();
        self._renderExplorer();
        self._renderTabs();
        self._renderActivePane();
      })
      .catch(function (err) {
        self.showError(err && err.message ? err.message : String(err));
      });
  };

  DatabaseStudio.prototype._renderFeatureChips = function () {
    var el = document.getElementById("ds-feature-chips");
    if (!el) return;
    var f = this.features || {};
    var chips = [];
    chips.push(
      '<span class="ds-chip is-core">' +
        escapeHtml(tr("ds.feature.core", "Core")) +
        "</span>"
    );
    if (f.inventory) {
      chips.push(
        '<span class="ds-chip">' +
          escapeHtml(tr("ds.feature.inventory", "Inventory")) +
          "</span>"
      );
    }
    if (f.appointments) {
      chips.push(
        '<span class="ds-chip">' +
          escapeHtml(tr("ds.feature.appointments", "Appointments")) +
          "</span>"
      );
    }
    if (f.channel_hub) {
      chips.push(
        '<span class="ds-chip">' +
          escapeHtml(tr("ds.feature.channel", "Channel Hub")) +
          "</span>"
      );
    }
    el.innerHTML = chips.join("");
    el.hidden = false;
  };

  DatabaseStudio.prototype._renderExplorer = function () {
    var list = document.getElementById("ds-table-list");
    if (!list) return;
    var self = this;
    var q = (this.filter || "").trim().toLowerCase();
    var rows = this.tables.filter(function (t) {
      if (!q) return true;
      return (
        String(t.name || "").toLowerCase().indexOf(q) >= 0 ||
        String(t.label || "").toLowerCase().indexOf(q) >= 0
      );
    });
    if (!rows.length) {
      list.innerHTML =
        '<li class="ds-empty" style="padding:12px">' +
        escapeHtml(tr("ds.no_tables", "No tables")) +
        "</li>";
      return;
    }
    list.innerHTML = rows
      .map(function (t) {
        var active = self.activeTab === t.name ? " is-active" : "";
        return (
          '<li><button type="button" class="ds-table-item' +
          active +
          '" data-ds-table="' +
          escapeHtml(t.name) +
          '">' +
          iconTable() +
          '<span class="ds-table-name" title="' +
          escapeHtml(t.label || t.name) +
          '">' +
          escapeHtml(t.name) +
          '</span><span class="ds-table-count">' +
          escapeHtml(String(t.row_count != null ? t.row_count : "")) +
          "</span></button></li>"
        );
      })
      .join("");
    list.querySelectorAll("[data-ds-table]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        self.openTable(btn.getAttribute("data-ds-table"));
      });
      btn.addEventListener("contextmenu", function (e) {
        e.preventDefault();
        e.stopPropagation();
        self._showTableCtx(e.clientX, e.clientY, btn.getAttribute("data-ds-table"));
      });
    });
  };

  DatabaseStudio.prototype.openTable = function (name) {
    if (!name) return;
    var exists = this.openTabs.some(function (t) {
      return t.id === name;
    });
    if (!exists) {
      this.openTabs.push({
        id: name,
        title: tr("ds.tab.table", "Table") + ": " + name,
        closable: true,
      });
    }
    this.activeTab = name;
    this._renderExplorer();
    this._renderTabs();
    this._renderActivePane();
  };

  DatabaseStudio.prototype._renderTabs = function () {
    var tabs = document.getElementById("ds-tabs");
    if (!tabs) return;
    var self = this;
    tabs.innerHTML = this.openTabs
      .map(function (t) {
        var active = t.id === self.activeTab ? " is-active" : "";
        var close =
          t.closable
            ? '<button type="button" class="ds-tab-close" data-ds-close="' +
              escapeHtml(t.id) +
              '" aria-label="Close">×</button>'
            : "";
        return (
          '<button type="button" class="ds-tab' +
          active +
          '" data-ds-tab="' +
          escapeHtml(t.id) +
          '"><span>' +
          escapeHtml(t.title) +
          "</span>" +
          close +
          "</button>"
        );
      })
      .join("");
    tabs.querySelectorAll("[data-ds-tab]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        if (e.target && e.target.getAttribute("data-ds-close")) return;
        self.activeTab = btn.getAttribute("data-ds-tab");
        self._renderExplorer();
        self._renderTabs();
        self._renderActivePane();
      });
    });
    tabs.querySelectorAll("[data-ds-close]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = btn.getAttribute("data-ds-close");
        self.openTabs = self.openTabs.filter(function (t) {
          return t.id !== id;
        });
        if (self.activeTab === id) self.activeTab = TAB_ERD;
        self._renderTabs();
        self._renderActivePane();
      });
    });
  };

  DatabaseStudio.prototype._renderActivePane = function () {
    var ws = document.getElementById("ds-workspace");
    if (!ws) return;
    if (this.activeTab === TAB_ERD) {
      ws.innerHTML = '<div class="ds-pane is-active" id="ds-erd-pane"></div>';
      this._renderErd(document.getElementById("ds-erd-pane"));
      return;
    }
    if (String(this.activeTab || "").indexOf("__struct__:") === 0) {
      var structName = String(this.activeTab).slice("__struct__:".length);
      this._openStructure(structName);
      return;
    }
    ws.innerHTML =
      '<div class="ds-pane is-active" id="ds-grid-pane" data-table="' +
      escapeHtml(this.activeTab) +
      '"></div>';
    var cached = this.gridByTable[this.activeTab];
    if (cached) this._renderGrid(document.getElementById("ds-grid-pane"), cached);
    else this._loadGrid(this.activeTab);
  };

  DatabaseStudio.prototype._renderErd = function (pane) {
    if (!pane) return;
    var self = this;
    var tables = this.tables || [];
    if (!tables.length) {
      pane.innerHTML =
        '<div class="ds-empty">' + escapeHtml(tr("ds.erd.empty", "No schema to display")) + "</div>";
      return;
    }

    var cardW = 220;
    var gapX = 56;
    var gapY = 40;
    var headH = 36;
    var rowH = 24;
    var cols = Math.max(1, Math.min(3, Math.ceil(Math.sqrt(tables.length))));
    var positions = {};
    var maxBottom = 0;
    var maxRight = 0;

    tables.forEach(function (t, i) {
      var col = i % cols;
      var row = Math.floor(i / cols);
      var x = 24 + col * (cardW + gapX);
      var y = 24;
      for (var r = 0; r < row; r++) {
        var prevIdx = r * cols + col;
        if (prevIdx < tables.length) {
          var prev = tables[prevIdx];
          var prevH = headH + Math.max(1, (prev.columns || []).length) * rowH + 8;
          y += prevH + gapY;
        }
      }
      var h = headH + Math.max(1, (t.columns || []).length) * rowH + 8;
      positions[t.name] = { x: x, y: y, w: cardW, h: h, columns: t.columns || [] };
      maxBottom = Math.max(maxBottom, y + h);
      maxRight = Math.max(maxRight, x + cardW);
    });

    var rels = (this.schema && this.schema.relations) || [];
    var svgH = Math.max(maxBottom + 40, 480);
    var svgW = Math.max(maxRight + 40, 640);

    function colY(tableName, colName) {
      var p = positions[tableName];
      if (!p) return 0;
      var idx = 0;
      for (var i = 0; i < p.columns.length; i++) {
        if (p.columns[i].name === colName) {
          idx = i;
          break;
        }
      }
      return p.y + headH + idx * rowH + rowH / 2;
    }

    var lines = rels
      .map(function (rel, ri) {
        var a = positions[rel.from_table];
        var b = positions[rel.to_table];
        if (!a || !b) return "";
        var y1 = colY(rel.from_table, rel.from_column);
        var y2 = colY(rel.to_table, rel.to_column);
        var x1 = a.x + a.w;
        var x2 = b.x;
        if (a.x > b.x) {
          x1 = a.x;
          x2 = b.x + b.w;
        }
        var mx = (x1 + x2) / 2;
        return (
          '<path class="ds-erd-line" data-ds-rel="' +
          ri +
          '" data-from-table="' +
          escapeHtml(rel.from_table) +
          '" data-from-col="' +
          escapeHtml(rel.from_column || "") +
          '" data-to-table="' +
          escapeHtml(rel.to_table) +
          '" data-to-col="' +
          escapeHtml(rel.to_column || "") +
          '" d="M' +
          x1 +
          " " +
          y1 +
          " C" +
          mx +
          " " +
          y1 +
          ", " +
          mx +
          " " +
          y2 +
          ", " +
          x2 +
          " " +
          y2 +
          '" />'
        );
      })
      .join("");

    var cards = tables
      .map(function (t) {
        var p = positions[t.name];
        var colsHtml = (t.columns || [])
          .map(function (c) {
            var badges = "";
            if (c.pk) badges += '<span class="ds-badge pk">PK</span>';
            var isFk = rels.some(function (r) {
              return r.from_table === t.name && r.from_column === c.name;
            });
            if (isFk) badges += '<span class="ds-badge fk">FK</span>';
            var tagTable = t.virtual ? "users" : t.name;
            return (
              '<div class="ds-erd-col" data-ds-table-col="' +
              escapeHtml(t.name) +
              "." +
              escapeHtml(c.name) +
              '" data-ds-copy="{{' +
              escapeHtml(tagTable + "." + c.name) +
              '}}" title="' +
              escapeHtml(tr("ds.copy_hint", "Click to copy Mustache tag")) +
              '">' +
              badges +
              '<span class="ds-erd-col-name">' +
              escapeHtml(c.name) +
              '</span><span class="ds-erd-col-type">' +
              escapeHtml(c.type || "TEXT") +
              "</span></div>"
            );
          })
          .join("");
        return (
          '<div class="ds-erd-card" style="left:' +
          p.x +
          "px;top:" +
          p.y +
          'px" data-ds-erd-table="' +
          escapeHtml(t.name) +
          '">' +
          '<div class="ds-erd-card-head"><div>' +
          escapeHtml(t.name) +
          "</div><span>" +
          escapeHtml(String(t.row_count != null ? t.row_count : 0)) +
          "</span></div>" +
          colsHtml +
          "</div>"
        );
      })
      .join("");

    this._erdNaturalW = svgW;
    this._erdNaturalH = svgH;

    pane.innerHTML =
      '<div class="ds-erd-toolbar">' +
      '<div class="ds-erd-zoom">' +
      '<button type="button" class="ds-btn ds-icon-btn" id="ds-erd-zoom-out" title="' +
      escapeHtml(tr("ds.erd.zoom_out", "Zoom out")) +
      '" aria-label="' +
      escapeHtml(tr("ds.erd.zoom_out", "Zoom out")) +
      '">−</button>' +
      '<span class="ds-erd-zoom-label" id="ds-erd-zoom-label">100%</span>' +
      '<button type="button" class="ds-btn ds-icon-btn" id="ds-erd-zoom-in" title="' +
      escapeHtml(tr("ds.erd.zoom_in", "Zoom in")) +
      '" aria-label="' +
      escapeHtml(tr("ds.erd.zoom_in", "Zoom in")) +
      '">+</button></div>' +
      '<button type="button" class="ds-btn" id="ds-erd-fit" title="' +
      escapeHtml(tr("ds.erd.fit", "Fit ERD to View")) +
      '">' +
      '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">' +
      '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>' +
      '<rect x="8" y="8" width="8" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="1.75"/>' +
      "</svg> " +
      escapeHtml(tr("ds.erd.fit", "Fit ERD to View")) +
      "</button></div>" +
      '<div class="ds-erd-wrap" id="ds-erd-wrap"><div class="ds-erd-sizer" id="ds-erd-sizer"><div class="ds-erd-canvas" id="ds-erd-canvas" style="width:' +
      svgW +
      "px;height:" +
      svgH +
      'px">' +
      '<svg class="ds-erd-svg" width="' +
      svgW +
      '" height="' +
      svgH +
      '">' +
      lines +
      "</svg>" +
      cards +
      '<div class="ds-copy-toast" id="ds-copy-toast"></div>' +
      "</div></div></div>";

    var fitBtn = pane.querySelector("#ds-erd-fit");
    if (fitBtn) {
      fitBtn.addEventListener("click", function () {
        self._fitErdToView(pane);
      });
    }
    var zoomIn = pane.querySelector("#ds-erd-zoom-in");
    var zoomOut = pane.querySelector("#ds-erd-zoom-out");
    if (zoomIn) {
      zoomIn.addEventListener("click", function () {
        self._zoomErd(pane, self._erdScale * 1.2);
      });
    }
    if (zoomOut) {
      zoomOut.addEventListener("click", function () {
        self._zoomErd(pane, self._erdScale / 1.2);
      });
    }
    this._bindErdPanZoom(pane);
    this._applyErdTransform(pane);

    pane.querySelectorAll("[data-ds-copy]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.stopPropagation();
        self._copyText(el.getAttribute("data-ds-copy"));
      });
    });
    pane.querySelectorAll("[data-ds-erd-table]").forEach(function (card) {
      card.addEventListener("dblclick", function () {
        self.openTable(card.getAttribute("data-ds-erd-table"));
      });
      card.addEventListener("contextmenu", function (e) {
        e.preventDefault();
        e.stopPropagation();
        self._showTableCtx(
          e.clientX,
          e.clientY,
          card.getAttribute("data-ds-erd-table")
        );
      });
    });
    pane.querySelectorAll(".ds-erd-line").forEach(function (line) {
      line.addEventListener("mouseenter", function () {
        line.classList.add("is-hot");
        var ft = line.getAttribute("data-from-table");
        var fc = line.getAttribute("data-from-col");
        var tt = line.getAttribute("data-to-table");
        var tc = line.getAttribute("data-to-col");
        pane.querySelectorAll(".ds-erd-col").forEach(function (col) {
          var key = col.getAttribute("data-ds-table-col") || "";
          if (key === ft + "." + fc || key === tt + "." + tc) {
            col.classList.add("is-rel-hot");
          }
        });
      });
      line.addEventListener("mouseleave", function () {
        line.classList.remove("is-hot");
        pane.querySelectorAll(".ds-erd-col.is-rel-hot").forEach(function (col) {
          col.classList.remove("is-rel-hot");
        });
      });
    });
  };

  DatabaseStudio.prototype._applyErdTransform = function (pane) {
    pane = pane || document.getElementById("ds-erd-pane");
    var canvas = pane && pane.querySelector("#ds-erd-canvas");
    var sizer = pane && pane.querySelector("#ds-erd-sizer");
    var label = pane && pane.querySelector("#ds-erd-zoom-label");
    if (!canvas) return;
    var scale = this._erdScale;
    var cw = this._erdNaturalW || parseInt(canvas.style.width, 10) || 640;
    var ch = this._erdNaturalH || parseInt(canvas.style.height, 10) || 480;
    canvas.style.transformOrigin = "0 0";
    canvas.style.transform = "scale(" + scale + ")";
    if (sizer) {
      sizer.style.width = Math.max(1, Math.ceil(cw * scale)) + "px";
      sizer.style.height = Math.max(1, Math.ceil(ch * scale)) + "px";
    }
    if (label) label.textContent = Math.round(scale * 100) + "%";
  };

  DatabaseStudio.prototype._zoomErd = function (pane, next, pivot) {
    pane = pane || document.getElementById("ds-erd-pane");
    var wrap = pane && pane.querySelector("#ds-erd-wrap");
    var old = this._erdScale || 1;
    this._erdScale = Math.max(this._erdMin, Math.min(this._erdMax, next));
    if (wrap && pivot && old > 0) {
      var relX = (wrap.scrollLeft + pivot.x) / old;
      var relY = (wrap.scrollTop + pivot.y) / old;
      this._applyErdTransform(pane);
      wrap.scrollLeft = relX * this._erdScale - pivot.x;
      wrap.scrollTop = relY * this._erdScale - pivot.y;
    } else {
      this._applyErdTransform(pane);
    }
  };

  DatabaseStudio.prototype._bindErdPanZoom = function (pane) {
    var self = this;
    var wrap = pane && pane.querySelector("#ds-erd-wrap");
    if (!wrap || wrap._dsZoomBound) return;
    wrap._dsZoomBound = true;
    wrap.addEventListener(
      "wheel",
      function (e) {
        e.preventDefault();
        var factor = e.deltaY > 0 ? 1 / 1.12 : 1.12;
        var rect = wrap.getBoundingClientRect();
        self._zoomErd(pane, self._erdScale * factor, {
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
        });
      },
      { passive: false }
    );
    var drag = null;
    wrap.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 && e.button !== 1) return;
      if (e.target.closest && e.target.closest(".ds-erd-card, button, input")) return;
      drag = {
        x: e.clientX,
        y: e.clientY,
        sl: wrap.scrollLeft,
        st: wrap.scrollTop,
        id: e.pointerId,
      };
      wrap.classList.add("is-panning");
      try {
        wrap.setPointerCapture(e.pointerId);
      } catch (err) {}
    });
    wrap.addEventListener("pointermove", function (e) {
      if (!drag) return;
      wrap.scrollLeft = drag.sl - (e.clientX - drag.x);
      wrap.scrollTop = drag.st - (e.clientY - drag.y);
    });
    function endPan() {
      drag = null;
      wrap.classList.remove("is-panning");
    }
    wrap.addEventListener("pointerup", endPan);
    wrap.addEventListener("pointercancel", endPan);
  };

  DatabaseStudio.prototype._fitErdToView = function (pane) {
    pane = pane || document.getElementById("ds-erd-pane");
    var wrap = pane && pane.querySelector("#ds-erd-wrap");
    if (!wrap) return;
    var cw = this._erdNaturalW || 640;
    var ch = this._erdNaturalH || 480;
    var vw = wrap.clientWidth || 1;
    var vh = wrap.clientHeight || 1;
    var pad = 24;
    var scale = Math.min((vw - pad) / cw, (vh - pad) / ch, this._erdMax);
    this._erdScale = Math.max(this._erdMin, scale);
    this._applyErdTransform(pane);
    wrap.scrollLeft = 0;
    wrap.scrollTop = 0;
  };

  DatabaseStudio.prototype._copyText = function (text) {
    var toast = document.getElementById("ds-copy-toast");
    function show() {
      if (!toast) return;
      toast.textContent = tr("ds.copied", "Copied") + ": " + text;
      toast.classList.add("is-visible");
      global.setTimeout(function () {
        toast.classList.remove("is-visible");
      }, 1600);
    }
    if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
      global.navigator.clipboard.writeText(text).then(show).catch(show);
    } else {
      show();
    }
  };

  DatabaseStudio.prototype._loadGrid = function (table, limitOverride) {
    var self = this;
    var pane = document.getElementById("ds-grid-pane");
    if (pane) {
      pane.innerHTML =
        '<div class="ds-empty">' + escapeHtml(tr("ds.loading", "Loading…")) + "</div>";
    }
    var limit =
      limitOverride != null
        ? limitOverride
        : this.gridLimitByTable[table] != null
          ? this.gridLimitByTable[table]
          : this.defaultGridLimit;
    if (limit === "all" || limit === 0) limit = 10000;
    this.gridLimitByTable[table] = limit > 5000 ? "all" : limit;
    return fetch(
      apiOrigin() +
        "/api/projects/" +
        encodeURIComponent(this.botId) +
        "/db/data?table=" +
        encodeURIComponent(table) +
        "&limit=" +
        encodeURIComponent(limit === "all" ? 10000 : limit),
      { headers: authHeaders() }
    )
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.showError((res.data && (res.data.detail || res.data.error)) || "Load failed");
          return;
        }
        self.gridByTable[table] = res.data;
        self.pendingEdits[table] = {};
        self.selectedRows[table] = {};
        if (self.activeTab === table) {
          var p = document.getElementById("ds-grid-pane");
          if (p) self._renderGrid(p, res.data);
        }
        self.clearError();
      })
      .catch(function (err) {
        self.showError(err && err.message ? err.message : String(err));
      });
  };

  DatabaseStudio.prototype._rowKey = function (meta, row) {
    var pk = (meta && meta.primary_key) || [];
    if (!pk.length) return JSON.stringify(row);
    return pk
      .map(function (k) {
        return k + "=" + (row[k] != null ? row[k] : "");
      })
      .join("|");
  };

  DatabaseStudio.prototype._clientValidate = function (colType, value) {
    var aff = String(colType || "TEXT").toUpperCase();
    if (value == null || value === "") return { ok: true, value: value };
    if (aff === "INTEGER") {
      if (!/^-?\d+$/.test(String(value).trim())) {
        return { ok: false, error: 'TYPE MISMATCH: "' + value + '" is not valid for INTEGER' };
      }
    }
    if (aff === "REAL" || aff === "NUMERIC") {
      if (isNaN(Number(String(value).trim().replace(",", ".")))) {
        return { ok: false, error: 'TYPE MISMATCH: "' + value + '" is not valid for ' + aff };
      }
    }
    if (aff === "BOOLEAN") {
      var s = String(value).trim().toLowerCase();
      if (!/^(0|1|true|false|yes|no|y|n|on|off|-?\d+)$/.test(s)) {
        return { ok: false, error: 'TYPE MISMATCH: "' + value + '" is not valid for BOOLEAN' };
      }
    }
    return { ok: true, value: value };
  };

  DatabaseStudio.prototype._renderGrid = function (pane, data) {
    var self = this;
    var table = data.table;
    var columns = (data.columns || []).filter(function (c) {
      return c !== "rowid";
    });
    var editable = data.editable_columns || [];
    var types = data.column_types || {};
    var rows = data.rows || [];
    var pending = this.pendingEdits[table] || {};
    var selected = this.selectedRows[table] || (this.selectedRows[table] = {});

    var curLimit = this.gridLimitByTable[table];
    if (curLimit == null) curLimit = this.defaultGridLimit;
    var limitOpts = [
      { v: 50, l: "50" },
      { v: 100, l: "100" },
      { v: 500, l: "500" },
      { v: "all", l: tr("ds.limit_all", "All") },
    ]
      .map(function (o) {
        var sel =
          String(curLimit) === String(o.v) ||
          (o.v === "all" && (curLimit === "all" || curLimit >= 10000))
            ? " selected"
            : "";
        return (
          '<option value="' +
          escapeHtml(String(o.v)) +
          '"' +
          sel +
          ">" +
          escapeHtml(o.l) +
          (o.v === "all" ? "" : " " + tr("ds.rows", "rows")) +
          "</option>"
        );
      })
      .join("");

    var toolbar =
      '<div class="ds-grid-toolbar">' +
      '<button type="button" class="ds-btn" id="ds-add-row"' +
      (data.allow_insert ? "" : " disabled") +
      ">" +
      escapeHtml(tr("ds.add_row", "Add Row")) +
      "</button>" +
      '<button type="button" class="ds-btn danger" id="ds-del-rows">' +
      escapeHtml(tr("ds.delete_selected", "Delete Selected")) +
      "</button>" +
      '<button type="button" class="ds-btn" id="ds-refresh">' +
      escapeHtml(tr("ds.refresh", "Refresh")) +
      "</button>" +
      '<button type="button" class="ds-btn primary" id="ds-commit">' +
      escapeHtml(tr("ds.commit", "Commit Changes")) +
      "</button>" +
      '<label class="ds-limit-label">' +
      escapeHtml(tr("ds.limit", "Limit")) +
      ' <select id="ds-limit-select" class="ds-limit-select">' +
      limitOpts +
      "</select></label>" +
      '<span class="ds-grid-meta">' +
      escapeHtml(String(rows.length)) +
      " / " +
      escapeHtml(String(data.total != null ? data.total : rows.length)) +
      " · " +
      escapeHtml(Object.keys(pending).length + " " + tr("ds.pending", "pending")) +
      "</span></div>";

    var head =
      '<th class="ds-check"><input type="checkbox" id="ds-check-all" /></th>' +
      columns
        .map(function (c) {
          return (
            "<th>" +
            escapeHtml(c) +
            ' <span style="font-weight:500;opacity:.7">' +
            escapeHtml(types[c] || "") +
            "</span></th>"
          );
        })
        .join("");

    var body = rows
      .map(function (row) {
        var rk = self._rowKey(data, row);
        var edits = pending[rk] || {};
        var isSel = !!selected[rk];
        var cells = columns
          .map(function (c) {
            var val = edits.hasOwnProperty(c) ? edits[c] : row[c];
            var canEdit = editable.indexOf(c) >= 0;
            return (
              '<td><div class="ds-cell' +
              (canEdit ? " is-editable" : "") +
              '" data-ds-rk="' +
              escapeHtml(rk) +
              '" data-ds-col="' +
              escapeHtml(c) +
              '" title="' +
              escapeHtml(val == null ? "" : String(val)) +
              '">' +
              escapeHtml(val == null ? "" : String(val)) +
              "</div></td>"
            );
          })
          .join("");
        return (
          '<tr class="' +
          (isSel ? "is-selected" : "") +
          '" data-ds-rk="' +
          escapeHtml(rk) +
          '"><td class="ds-check"><input type="checkbox" class="ds-row-check" data-ds-rk="' +
          escapeHtml(rk) +
          '"' +
          (isSel ? " checked" : "") +
          " /></td>" +
          cells +
          "</tr>"
        );
      })
      .join("");

    pane.innerHTML =
      toolbar +
      '<div class="ds-grid-scroll"><table class="ds-grid-table"><thead><tr>' +
      head +
      "</tr></thead><tbody>" +
      (body ||
        '<tr><td colspan="' +
          (columns.length + 1) +
          '"><div class="ds-empty">' +
          escapeHtml(tr("ds.empty_rows", "No rows")) +
          "</div></td></tr>") +
      "</tbody></table></div>";

    var refreshBtn = pane.querySelector("#ds-refresh");
    if (refreshBtn) {
      refreshBtn.onclick = function () {
        self._loadGrid(table);
      };
    }
    var limitSel = pane.querySelector("#ds-limit-select");
    if (limitSel) {
      limitSel.onchange = function () {
        var v = limitSel.value;
        self.gridLimitByTable[table] = v === "all" ? "all" : parseInt(v, 10);
        self._loadGrid(table);
      };
    }
    var commitBtn = pane.querySelector("#ds-commit");
    if (commitBtn) {
      commitBtn.onclick = function () {
        self._commitPending(table);
      };
    }
    var delBtn = pane.querySelector("#ds-del-rows");
    if (delBtn) {
      delBtn.onclick = function () {
        self._deleteSelected(table);
      };
    }
    var addBtn = pane.querySelector("#ds-add-row");
    if (addBtn && !addBtn.disabled) {
      addBtn.onclick = function () {
        self._addRow(table, data);
      };
    }
    pane.querySelectorAll(".ds-row-check").forEach(function (cb) {
      cb.addEventListener("change", function () {
        var rk = cb.getAttribute("data-ds-rk");
        if (cb.checked) selected[rk] = true;
        else delete selected[rk];
        var trEl = pane.querySelector('tr[data-ds-rk="' + rk.replace(/"/g, '\\"') + '"]');
        if (trEl) trEl.classList.toggle("is-selected", cb.checked);
      });
    });
    pane.querySelectorAll(".ds-cell.is-editable").forEach(function (cell) {
      cell.addEventListener("dblclick", function () {
        self._beginEdit(cell, table, data);
      });
    });
  };

  DatabaseStudio.prototype._beginEdit = function (cell, table, data) {
    if (cell.classList.contains("is-editing")) return;
    var self = this;
    var col = cell.getAttribute("data-ds-col");
    var rk = cell.getAttribute("data-ds-rk");
    var types = data.column_types || {};
    var pending = this.pendingEdits[table] || (this.pendingEdits[table] = {});
    var row = (data.rows || []).find(function (r) {
      return self._rowKey(data, r) === rk;
    });
    var current =
      pending[rk] && pending[rk].hasOwnProperty(col)
        ? pending[rk][col]
        : row
          ? row[col]
          : "";
    cell.classList.add("is-editing");
    cell.innerHTML =
      '<input class="ds-cell-input" type="text" value="' +
      escapeHtml(current == null ? "" : String(current)) +
      '" />';
    var input = cell.querySelector("input");
    if (!input) return;
    input.focus();
    input.select();

    var finished = false;
    function finish(commit) {
      if (finished) return;
      finished = true;
      var val = input.value;
      cell.classList.remove("is-editing");
      if (commit) {
        var check = self._clientValidate(types[col], val);
        if (!check.ok) {
          self.showError(check.error);
          cell.textContent = current == null ? "" : String(current);
          return;
        }
        if (!pending[rk]) pending[rk] = {};
        pending[rk][col] = val;
        self.clearError();
      }
      var show =
        pending[rk] && pending[rk].hasOwnProperty(col)
          ? pending[rk][col]
          : current;
      cell.textContent = show == null ? "" : String(show);
      cell.title = cell.textContent;
      var pane = document.getElementById("ds-grid-pane");
      if (pane && self.gridByTable[table]) self._renderGrid(pane, self.gridByTable[table]);
    }

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        finish(true);
      } else if (e.key === "Escape") {
        e.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", function () {
      finish(true);
    });
  };

  DatabaseStudio.prototype._pkFromRowKey = function (meta, rk, row) {
    var pk = {};
    (meta.primary_key || []).forEach(function (k) {
      pk[k] = row[k];
    });
    return pk;
  };

  DatabaseStudio.prototype._commitPending = function (table) {
    var self = this;
    var data = this.gridByTable[table];
    var pending = this.pendingEdits[table] || {};
    var keys = Object.keys(pending);
    if (!keys.length) {
      this.showError(tr("ds.nothing_to_commit", "No pending changes"));
      return;
    }
    var chain = Promise.resolve();
    var failed = null;
    keys.forEach(function (rk) {
      chain = chain.then(function () {
        if (failed) return;
        var row = (data.rows || []).find(function (r) {
          return self._rowKey(data, r) === rk;
        });
        if (!row) return;
        var values = pending[rk];
        // client validate all
        var types = data.column_types || {};
        for (var col in values) {
          if (!values.hasOwnProperty(col)) continue;
          var check = self._clientValidate(types[col], values[col]);
          if (!check.ok) {
            failed = check.error;
            return;
          }
        }
        var body = {
          table: table,
          primary_key: self._pkFromRowKey(data, rk, row),
          values: values,
        };
        return fetch(apiOrigin() + "/api/projects/" + encodeURIComponent(self.botId) + "/db/row", {
          method: "PUT",
          headers: authHeaders(true),
          body: JSON.stringify(body),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { status: r.status, data: d };
            });
          })
          .then(function (res) {
            if (res.data && res.data.success === false) {
              failed = res.data.error || "Update failed";
              return;
            }
            if (res.status >= 400) {
              failed =
                (res.data && (res.data.error || res.data.detail)) ||
                "HTTP " + res.status;
            }
          });
      });
    });
    chain.then(function () {
      if (failed) {
        self.showError(failed);
        return;
      }
      self.pendingEdits[table] = {};
      self.clearError();
      self._loadGrid(table);
      self.reloadSchema();
    });
  };

  DatabaseStudio.prototype._deleteSelected = function (table) {
    var self = this;
    var data = this.gridByTable[table];
    var selected = this.selectedRows[table] || {};
    var keys = Object.keys(selected);
    if (!keys.length) {
      this.showError(tr("ds.none_selected", "No rows selected"));
      return;
    }
    var chain = Promise.resolve();
    var failed = null;
    keys.forEach(function (rk) {
      chain = chain.then(function () {
        if (failed) return;
        var row = (data.rows || []).find(function (r) {
          return self._rowKey(data, r) === rk;
        });
        if (!row) return;
        return fetch(apiOrigin() + "/api/projects/" + encodeURIComponent(self.botId) + "/db/row", {
          method: "DELETE",
          headers: authHeaders(true),
          body: JSON.stringify({
            table: table,
            primary_key: self._pkFromRowKey(data, rk, row),
          }),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              return { status: r.status, data: d };
            });
          })
          .then(function (res) {
            if (res.data && res.data.success === false) {
              failed = res.data.error || "Delete failed";
            } else if (res.status >= 400) {
              failed = (res.data && (res.data.error || res.data.detail)) || "HTTP " + res.status;
            }
          });
      });
    });
    chain.then(function () {
      if (failed) {
        self.showError(failed);
        return;
      }
      self.selectedRows[table] = {};
      self.clearError();
      self._loadGrid(table);
      self.reloadSchema();
    });
  };

  DatabaseStudio.prototype._addRow = function (table, data) {
    var self = this;
    var values = {};
    (data.insert_columns || data.editable_columns || []).forEach(function (c) {
      values[c] = "";
    });
    if (table === "bot_globals") {
      var key = global.prompt(tr("ds.prompt_key", "New key name"), "");
      if (!key) return;
      values = { key: key, value: "" };
    }
    fetch(apiOrigin() + "/api/projects/" + encodeURIComponent(this.botId) + "/db/row", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ table: table, values: values }),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          return { status: r.status, data: d };
        });
      })
      .then(function (res) {
        if (res.data && res.data.success === false) {
          self.showError(res.data.error || "Insert failed");
          return;
        }
        if (res.status >= 400) {
          self.showError((res.data && (res.data.error || res.data.detail)) || "Insert failed");
          return;
        }
        self.clearError();
        self._loadGrid(table);
        self.reloadSchema();
      })
      .catch(function (err) {
        self.showError(err && err.message ? err.message : String(err));
      });
  };

  DatabaseStudio.prototype._onDocClick = function (e) {
    if (e.target && e.target.closest && e.target.closest("#ds-ctx")) return;
    this._hideCtx();
  };

  DatabaseStudio.prototype._hideCtx = function () {
    var menu = document.getElementById("ds-ctx");
    if (menu) {
      menu.hidden = true;
      menu.innerHTML = "";
    }
  };

  DatabaseStudio.prototype._showTableCtx = function (x, y, tableName) {
    var menu = document.getElementById("ds-ctx");
    if (!menu || !tableName) return;
    var self = this;
    var iconSelect =
      '<svg class="ds-ctx-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.25"/><path d="M4 5.5h8M4 8h8M4 10.5h5" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/></svg>';
    var iconSelectMore =
      '<svg class="ds-ctx-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="2" y="2" width="12" height="12" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.25"/><path d="M4 5h8M4 7.5h8M4 10h8M4 12.5h4" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round"/></svg>';
    var iconStruct =
      '<svg class="ds-ctx-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z" fill="none" stroke="currentColor" stroke-width="1.25"/></svg>';
    var iconClear =
      '<svg class="ds-ctx-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3.5 4.5h9M6 4.5V3.5h4v1M5 4.5l.5 8h5l.5-8" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    menu.hidden = false;
    menu.innerHTML =
      '<button type="button" data-ds-act="top100">' +
      iconSelect +
      "<span>" +
      escapeHtml(tr("ds.ctx.top100", "SELECT TOP 100")) +
      "</span></button>" +
      '<button type="button" data-ds-act="top1000">' +
      iconSelectMore +
      "<span>" +
      escapeHtml(tr("ds.ctx.top1000", "SELECT TOP 1000")) +
      "</span></button>" +
      '<button type="button" data-ds-act="structure">' +
      iconStruct +
      "<span>" +
      escapeHtml(tr("ds.ctx.structure", "Structure")) +
      "</span></button>" +
      '<button type="button" data-ds-act="clear" class="is-danger">' +
      iconClear +
      "<span>" +
      escapeHtml(tr("ds.ctx.clear", "Truncate Table")) +
      "</span></button>";
    menu.style.left = Math.min(x, (global.innerWidth || 800) - 220) + "px";
    menu.style.top = Math.min(y, (global.innerHeight || 600) - 180) + "px";
    menu.querySelectorAll("[data-ds-act]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var act = btn.getAttribute("data-ds-act");
        self._hideCtx();
        if (act === "top100") {
          self.gridLimitByTable[tableName] = 100;
          self.openTable(tableName);
          self._loadGrid(tableName, 100);
        } else if (act === "top1000") {
          self.gridLimitByTable[tableName] = 1000;
          self.openTable(tableName);
          self._loadGrid(tableName, 1000);
        } else if (act === "structure") {
          self._openStructure(tableName);
        } else if (act === "clear") {
          self._clearTableData(tableName);
        }
      });
    });
  };

  DatabaseStudio.prototype._openStructure = function (tableName) {
    var t = (this.tables || []).find(function (x) {
      return x.name === tableName;
    });
    var tabId = "__struct__:" + tableName;
    var exists = this.openTabs.some(function (tab) {
      return tab.id === tabId;
    });
    if (!exists) {
      this.openTabs.push({
        id: tabId,
        title: tr("ds.ctx.structure", "Structure") + ": " + tableName,
        closable: true,
      });
    }
    this.activeTab = tabId;
    this._renderTabs();
    var ws = document.getElementById("ds-workspace");
    if (!ws) return;
    if (!t) {
      ws.innerHTML =
        '<div class="ds-pane is-active"><div class="ds-empty">' +
        escapeHtml(tr("ds.no_tables", "No tables")) +
        "</div></div>";
      return;
    }
    var cols = (t.columns || [])
      .map(function (c) {
        return (
          "<tr><td>" +
          escapeHtml(c.name) +
          "</td><td>" +
          escapeHtml(c.type || c.decl_type || "TEXT") +
          "</td><td>" +
          (c.pk ? "PK" : "") +
          (c.notnull ? " NOT NULL" : "") +
          "</td><td>" +
          escapeHtml(c.default != null ? String(c.default) : "") +
          "</td></tr>"
        );
      })
      .join("");
    ws.innerHTML =
      '<div class="ds-pane is-active"><div class="ds-struct">' +
      "<h3>" +
      escapeHtml(tableName) +
      "</h3>" +
      '<p class="ds-struct-meta">' +
      escapeHtml(String(t.row_count != null ? t.row_count : 0)) +
      " " +
      escapeHtml(tr("ds.rows", "rows")) +
      "</p>" +
      '<table class="ds-struct-table"><thead><tr><th>Column</th><th>Type</th><th>Flags</th><th>Default</th></tr></thead><tbody>' +
      cols +
      "</tbody></table></div></div>";
  };

  DatabaseStudio.prototype._clearTableData = function (tableName) {
    var self = this;
    if (
      !global.confirm(
        tr("ds.ctx.clear_confirm", "Delete all rows from this table?") +
          "\n" +
          tableName
      )
    ) {
      return;
    }
    fetch(
      apiOrigin() +
        "/api/projects/" +
        encodeURIComponent(this.botId) +
        "/db/clear",
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({ table: tableName }),
      }
    )
      .then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.showError(
            (res.data && (res.data.detail || res.data.error)) || "Clear failed"
          );
          return;
        }
        self.clearError();
        delete self.gridByTable[tableName];
        if (self.activeTab === tableName) self._loadGrid(tableName);
        self.reloadSchema();
      })
      .catch(function (err) {
        self.showError(err && err.message ? err.message : String(err));
      });
  };

  global.DatabaseStudio = DatabaseStudio;
})(typeof window !== "undefined" ? window : this);
