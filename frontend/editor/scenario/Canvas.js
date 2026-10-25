/**
 * ScenarioCanvas — SVG connection layer, port math, Bezier routing.
 * Loaded before main.js / ScenarioEditor.js.
 */
(function (global) {
  "use strict";

  var WORLD_ORIGIN = 50000;
  var NS = "http://www.w3.org/2000/svg";
  var OUT_OFFSET = 10;
  var IN_OFFSET = 10;
  var DEFAULT_NODE_W = 240;
  var DEFAULT_NODE_H = 120;

  var _opts = null;
  var _raf = null;
  var _selectedConnIdx = null;

  function opts() {
    return _opts || {};
  }

  function getWrapper() {
    var o = opts();
    if (typeof o.getWrapper === "function") return o.getWrapper();
    return (
      document.getElementById("canvas-wrapper") ||
      document.getElementById("canvas-container")
    );
  }

  function getSvg() {
    var o = opts();
    if (typeof o.getSvg === "function") {
      var s = o.getSvg();
      if (s) return s;
    }
    return (
      document.getElementById("connections-layer") ||
      document.querySelector("svg.connections") ||
      document.getElementById("connections")
    );
  }

  function getPanScale() {
    var o = opts();
    var panX = typeof o.getPanX === "function" ? o.getPanX() : 0;
    var panY = typeof o.getPanY === "function" ? o.getPanY() : 0;
    var scale = typeof o.getScale === "function" ? o.getScale() : 1;
    if (!scale || scale < 0.01) scale = 1;
    return { panX: panX, panY: panY, scale: scale };
  }

  function getBlocks() {
    var o = opts();
    return typeof o.getBlocks === "function" ? o.getBlocks() || [] : [];
  }

  function getConnections() {
    var o = opts();
    return typeof o.getConnections === "function" ? o.getConnections() || [] : [];
  }

  function getPending() {
    var o = opts();
    return typeof o.getPending === "function" ? o.getPending() : null;
  }

  function findBlock(nodeId) {
    var list = getBlocks();
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].id === nodeId) return list[i];
    }
    return null;
  }

  function findBlockEl(nodeId) {
    var b = findBlock(nodeId);
    if (b && b.el) return b.el;
    return document.querySelector('[data-id="' + String(nodeId).replace(/"/g, "") + '"]');
  }

  /**
   * Screen → canvas/SVG world space (accounts for -50000 origin + pan/zoom).
   */
  function screenToWorld(screenX, screenY) {
    var wrap = getWrapper();
    if (!wrap) return { x: 0, y: 0 };
    var rect = wrap.getBoundingClientRect();
    var ps = getPanScale();
    return {
      x: (screenX - rect.left + WORLD_ORIGIN - ps.panX) / ps.scale,
      y: (screenY - rect.top + WORLD_ORIGIN - ps.panY) / ps.scale,
    };
  }

  /**
   * Resolve port world coordinates.
   * @param {string} nodeId
   * @param {string|number} portId  data-index / data-port-id
   * @param {boolean} isOutput
   */
  function getPortCoordinates(nodeId, portId, isOutput) {
    var block = findBlock(nodeId);
    var el = findBlockEl(nodeId);
    var portKey = portId != null ? String(portId) : "0";

    // Inputs attach to the left edge of the card (no dedicated input port DOM).
    if (!isOutput) {
      if (el) {
        var br = el.getBoundingClientRect();
        var wIn = screenToWorld(br.left, br.top + br.height / 2);
        wIn.x -= IN_OFFSET;
        return wIn;
      }
      var fx = 0;
      var fy = 0;
      var fh = DEFAULT_NODE_H;
      if (block) {
        fx = block.x != null ? block.x : 0;
        fy = block.y != null ? block.y : 0;
      }
      return { x: fx - IN_OFFSET, y: fy + fh * 0.5 };
    }

    var portEl = null;
    if (el) {
      portEl =
        el.querySelector('.node-port[data-port-id="' + portKey + '"]') ||
        el.querySelector('.output[data-port-id="' + portKey + '"]') ||
        el.querySelector('.output[data-index="' + portKey + '"]') ||
        el.querySelector('.output[data-port="' + portKey + '"]');
    }

    // Binary ports (ok/err/yes/no) are label-free dots — coords from the circle only.
    if (portEl) {
      var r = portEl.getBoundingClientRect();
      var cx = r.left + r.width / 2;
      var cy = r.top + r.height / 2;
      // Multi-button row: attach from block right edge at row center
      if (
        el &&
        portEl.closest &&
        (portEl.closest(".menu-button") || portEl.closest(".inline-btn"))
      ) {
        var blockRect = el.getBoundingClientRect();
        var rowParent = portEl.closest(".menu-button") || portEl.closest(".inline-btn");
        var rowRect = rowParent ? rowParent.getBoundingClientRect() : r;
        cx = blockRect.right;
        cy = rowRect.top + rowRect.height / 2;
      }
      var w = screenToWorld(cx, cy);
      w.x += OUT_OFFSET;
      return w;
    }

    // Fallback: node model bounds (output)
    var x = 0;
    var y = 0;
    var wNode = DEFAULT_NODE_W;
    var hNode = DEFAULT_NODE_H;
    if (el) {
      x = parseFloat(el.style.left) || 0;
      y = parseFloat(el.style.top) || 0;
      wNode = el.offsetWidth || DEFAULT_NODE_W;
      hNode = el.offsetHeight || DEFAULT_NODE_H;
    } else if (block) {
      x = block.x != null ? block.x : 0;
      y = block.y != null ? block.y : 0;
    }
    var idx = parseInt(portKey, 10);
    if (!Number.isFinite(idx)) idx = 0;
    var outCount = 1;
    if (el) {
      var outs = el.querySelectorAll(".output");
      outCount = Math.max(1, outs.length);
    }
    var frac = (idx + 0.5) / outCount;
    return { x: x + wNode + OUT_OFFSET, y: y + hNode * frac };
  }

  /**
   * Cubic Bezier: M x1 y1 C (x1+dx) y1, (x2-dx) y2, x2 y2
   */
  function renderConnectionPath(x1, y1, x2, y2) {
    var dx = Math.max(40, Math.abs(x2 - x1) * 0.4);
    return (
      "M " +
      x1 +
      " " +
      y1 +
      " C " +
      (x1 + dx) +
      " " +
      y1 +
      ", " +
      (x2 - dx) +
      " " +
      y2 +
      ", " +
      x2 +
      " " +
      y2
    );
  }

  function semanticClassAndColor(block, outputIndex) {
    var o = opts();
    var color = "#888";
    if (typeof o.getConnectionColor === "function" && block && block.id) {
      color = o.getConnectionColor(block.id, outputIndex);
    } else if (!block) {
      color = "#888";
    } else {
      var idx = parseInt(String(outputIndex), 10);
      if (!Number.isFinite(idx)) idx = 0;
      var type = String(block.type || "");
      if (
        type === "condition" ||
        type === "app_bridge" ||
        type.indexOf("payment") === 0 ||
        type === "payment_universal"
      ) {
        color = idx === 0 ? "#16a34a" : "#dc2626";
      } else if (block.data && block.data.action === "issue") {
        color = idx === 0 ? "#16a34a" : "#dc2626";
      } else {
        color = "#888";
      }
    }
    if (color === "#16a34a" || color === "#22c55e") {
      return { cls: "conn-success", color: color };
    }
    if (color === "#dc2626" || color === "#ef4444") {
      return { cls: "conn-fail", color: color };
    }
    // Multi-button palette (blue/red/green/…) — keep exact stroke, no forced accent
    if (color && color !== "#888") {
      return { cls: "conn-colored", color: color };
    }
    return { cls: "conn-flow", color: "#888" };
  }

  function ensureLayer() {
    var wrap = getWrapper();
    if (!wrap) return null;
    var svg = getSvg();
    if (!svg) {
      svg = document.createElementNS(NS, "svg");
      svg.setAttribute("id", "connections-layer");
      svg.setAttribute("class", "connections");
      var canvas = document.getElementById("canvas");
      if (canvas && canvas.parentNode === wrap) {
        wrap.insertBefore(svg, canvas);
      } else {
        var grid = document.getElementById("grid-overlay");
        if (grid && grid.nextSibling) wrap.insertBefore(svg, grid.nextSibling);
        else wrap.appendChild(svg);
      }
    } else {
      if (!svg.id || svg.id === "connections") svg.id = "connections-layer";
      if (!svg.classList.contains("connections")) svg.classList.add("connections");
      // Ensure behind #canvas, above grid
      var canvasEl = document.getElementById("canvas");
      if (canvasEl && svg.nextSibling !== canvasEl) {
        wrap.insertBefore(svg, canvasEl);
      }
    }
    return svg;
  }

  function syncSvgTransform() {
    var svg = ensureLayer();
    if (!svg) return;
    var ps = getPanScale();
    var t =
      "translate(" + ps.panX + "px, " + ps.panY + "px) scale(" + ps.scale + ")";
    svg.style.transform = t;
    svg.style.left = "-" + WORLD_ORIGIN + "px";
    svg.style.top = "-" + WORLD_ORIGIN + "px";
    svg.style.width = "200000px";
    svg.style.height = "200000px";
    svg.style.overflow = "visible";
  }

  function ensureDefs(svg, connections) {
    var defs = document.createElementNS(NS, "defs");

    function addMarker(id, fill) {
      var m = document.createElementNS(NS, "marker");
      m.setAttribute("id", id);
      m.setAttribute("viewBox", "0 0 10 10");
      m.setAttribute("refX", "9");
      m.setAttribute("refY", "5");
      m.setAttribute("markerWidth", "7");
      m.setAttribute("markerHeight", "7");
      m.setAttribute("orient", "auto");
      m.setAttribute("markerUnits", "strokeWidth");
      var p = document.createElementNS(NS, "path");
      p.setAttribute("d", "M0,0 L10,5 L0,10 Z");
      p.setAttribute("fill", fill);
      m.appendChild(p);
      defs.appendChild(m);
    }

    addMarker("arrow-head", "#888");
    addMarker("arrow-head-success", "#16a34a");
    addMarker("arrow-head-fail", "#dc2626");
    addMarker("arrow-head-pending", "#555");

    (connections || []).forEach(function (conn, idx) {
      var block = findBlock(conn.from);
      var sem = semanticClassAndColor(
        block,
        conn.outputIndex != null ? conn.outputIndex : "0"
      );
      addMarker("arrow-" + idx, sem.color);
    });

    svg.appendChild(defs);
    return defs;
  }

  function markerForSem(sem, idx) {
    if (sem.cls === "conn-success") return "url(#arrow-head-success)";
    if (sem.cls === "conn-fail") return "url(#arrow-head-fail)";
    if (idx != null) return "url(#arrow-" + idx + ")";
    return "url(#arrow-head)";
  }

  function renderAllConnections() {
    var svg = ensureLayer();
    if (!svg) return;
    syncSvgTransform();

    var connections = getConnections();
    var pending = getPending();
    var o = opts();

    svg.innerHTML = "";
    ensureDefs(svg, connections);

    if (pending && pending.mouseX != null && pending.from) {
      var pOut =
        pending.outputIndex != null ? String(pending.outputIndex) : "0";
      var start = getPortCoordinates(pending.from, pOut, true);
      var end = screenToWorld(pending.mouseX, pending.mouseY);
      if (start && end) {
        var pPath = document.createElementNS(NS, "path");
        pPath.setAttribute("d", renderConnectionPath(start.x, start.y, end.x, end.y));
        pPath.setAttribute("class", "conn-wire conn-pending");
        pPath.setAttribute("stroke-width", "2");
        pPath.setAttribute("marker-end", "url(#arrow-head-pending)");
        svg.appendChild(pPath);
      }
    }

    connections.forEach(function (conn, idx) {
      if (!conn || !conn.from || !conn.to) return;
      var outIdx = conn.outputIndex != null ? String(conn.outputIndex) : "0";
      var fromBlock = findBlock(conn.from);
      var start = getPortCoordinates(conn.from, outIdx, true);
      var end = getPortCoordinates(conn.to, "0", false);
      if (!start || !end) return;

      var sem = semanticClassAndColor(fromBlock, outIdx);
      var path = document.createElementNS(NS, "path");
      path.setAttribute("d", renderConnectionPath(start.x, start.y, end.x, end.y));
      path.setAttribute("class", "conn-wire " + sem.cls);
      path.setAttribute("stroke", sem.color);
      path.setAttribute("stroke-width", "2");
      path.setAttribute("marker-end", markerForSem(sem, idx));
      path.setAttribute("data-connection-index", String(idx));
      path.dataset.connectionIndex = String(idx);
      path.dataset.from = conn.from;
      path.dataset.to = conn.to;
      path.dataset.outputIndex = outIdx;

      if (_selectedConnIdx === idx) path.classList.add("conn-selected");

      path.addEventListener("click", function (ev) {
        ev.stopPropagation();
        _selectedConnIdx = idx;
        if (typeof o.onConnectionClick === "function") {
          o.onConnectionClick(idx, conn, ev);
        } else {
          renderAllConnections();
        }
      });

      svg.appendChild(path);
    });
  }

  function scheduleRender() {
    if (_raf != null) return;
    _raf = global.requestAnimationFrame(function () {
      _raf = null;
      renderAllConnections();
    });
  }

  function bind(options) {
    _opts = options || {};
    ensureLayer();
    syncSvgTransform();
    return api;
  }

  function setSelectedConnection(idx) {
    _selectedConnIdx = idx;
  }

  var api = {
    WORLD_ORIGIN: WORLD_ORIGIN,
    bind: bind,
    ensureLayer: ensureLayer,
    syncSvgTransform: syncSvgTransform,
    getPortCoordinates: getPortCoordinates,
    screenToWorld: screenToWorld,
    renderConnectionPath: renderConnectionPath,
    renderAllConnections: renderAllConnections,
    scheduleRender: scheduleRender,
    semanticClassAndColor: semanticClassAndColor,
    setSelectedConnection: setSelectedConnection,
  };

  global.ScenarioCanvas = api;
  // Alias requested by task naming
  global.Canvas = global.Canvas || api;
})(typeof window !== "undefined" ? window : this);
