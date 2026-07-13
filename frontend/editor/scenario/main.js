var API_BASE = typeof getApiOrigin === "function" ? getApiOrigin() : (typeof window !== "undefined" && window.location && window.location.origin ? window.location.origin : "http://127.0.0.1:8000");

function tr(key, params) {
  return typeof t === "function" ? t(key, params) : key;
}

function blockTitleForType(type) {
  if (typeof CanvasView !== "undefined" && CanvasView.getPluginByType) {
    var plugin = CanvasView.getPluginByType(type, CanvasView.getRegistry());
    if (plugin) {
      var name = plugin.name || type;
      if (plugin.icon) return plugin.icon + " " + name;
      return name;
    }
  }
  return type;
}

function defaultTextForType(type, key, fallback) {
  var pid = type;
  if (type === "message") pid = "send_message";
  else if (type === "menu") pid = "menu_node";
  else if (type === "command") pid = "command_node";
  else if (type === "note") pid = "note_node";
  else if (type === "weather") pid = "weather_node";
  var locKey = "plugin." + pid + ".default." + key;
  var localized = tr(locKey);
  if (localized && localized !== locKey) return localized;
  if (typeof CanvasView !== "undefined" && CanvasView.getPluginByType) {
    var plugin = CanvasView.getPluginByType(type, CanvasView.getRegistry());
    if (plugin && plugin.defaults && plugin.defaults[key]) return plugin.defaults[key];
  }
  return fallback != null ? fallback : "";
}

const canvas = document.getElementById("canvas");
const sidebar = document.getElementById("sidebar");
const sidebarContent = document.getElementById("sidebar-content");
const svg = document.querySelector("svg.connections");

const urlParams = new URLSearchParams(window.location.search);
const bot_id = urlParams.get("bot_id") || "";
const template_id = urlParams.get("template_id") || "";
var user_id = typeof getUserId === "function" ? getUserId() : "1";

var SCENARIO_SAVE_ICON = "💾";
var SCENARIO_SAVE_LOADING_ICON = "⏳";

function showScenarioToast(message) {
  if (!message) return;
  var existing = document.getElementById("scenario-save-toast");
  if (existing) existing.remove();
  var toast = document.createElement("div");
  toast.id = "scenario-save-toast";
  toast.className = "scenario-toast";
  toast.setAttribute("role", "status");
  toast.innerHTML =
    '<span class="scenario-toast-icon" aria-hidden="true">✓</span>' +
    '<span class="scenario-toast-text"></span>';
  toast.querySelector(".scenario-toast-text").textContent = message;
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
  }, 2600);
}

let blocks = [];
let connections = [];
let scenarioTags = [];
/** @type {Set<string>} */
var selectedBlockIds = new Set();
var pendingConnection = null;
var _draggingBlockId = null;

let scale = 1;
let panX = 0;
let panY = 0;

const canvasWrapper = document.getElementById("canvas-wrapper");

function initCanvasView() {
  if (!canvasWrapper) return;
  var rect = canvasWrapper.getBoundingClientRect();
  panX = rect.width / 2 + 50000 - 400;
  panY = rect.height / 2 + 50000 - 300;
  updateTransform();
}

function escapeHtml(s) {
  if (s == null) return "";
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function syncBlockSelectionStyles() {
  blocks.forEach(function (b) {
    if (!b.el) return;
    if (selectedBlockIds.has(b.id)) b.el.classList.add("block-selected");
    else b.el.classList.remove("block-selected");
  });
}

var _drawConnectionsRaf = null;
var _activeDrag = null;
var _sidebarBlockId = null;
var DRAG_THRESHOLD = 4;

var undoStack = [];
var _suppressUndo = false;

function getUndoLimit() {
  if (typeof getUndoSteps === "function") return getUndoSteps();
  if (window.electronAPI && typeof window.electronAPI.getUndoSteps === "function") {
    return window.electronAPI.getUndoSteps();
  }
  return 30;
}

function captureScenarioSnapshot() {
  var requiredPlugins =
    typeof CanvasView !== "undefined" && CanvasView.computeRequiredPlugins
      ? CanvasView.computeRequiredPlugins(blocks)
      : blocks.map(function (b) { return b.type; }).filter(function (t, i, a) { return a.indexOf(t) === i; }).sort();
  return {
    tags: JSON.parse(JSON.stringify(scenarioTags)),
    connections: JSON.parse(JSON.stringify(connections)),
    required_plugins: requiredPlugins,
    blocks: blocks.map(function (b) {
      return {
        id: b.id,
        type: b.type,
        x: parseFloat(b.el.style.left) || 0,
        y: parseFloat(b.el.style.top) || 0,
        data: JSON.parse(JSON.stringify(b.data)),
      };
    }),
    selectedBlockIds: Array.from(selectedBlockIds),
    sidebarBlockId: _sidebarBlockId,
  };
}

function restoreScenarioSnapshot(snapshot) {
  if (!snapshot) return;
  _suppressUndo = true;
  pendingConnection = null;
  selectedBlockIds.clear();
  (snapshot.selectedBlockIds || []).forEach(function (id) {
    selectedBlockIds.add(id);
  });
  scenarioTags = JSON.parse(JSON.stringify(snapshot.tags || []));
  connections = JSON.parse(JSON.stringify(snapshot.connections || []));
  blocks.forEach(function (b) {
    b.el.remove();
  });
  blocks = [];
  (snapshot.blocks || []).forEach(function (block) {
    createBlock(
      block.type,
      block.x,
      block.y,
      Object.assign({}, block.data, { id: block.id, x: block.x, y: block.y })
    );
  });
  drawConnections();
  syncBlockSelectionStyles();
  if (snapshot.sidebarBlockId) {
    var sidebarBlock = blocks.find(function (b) {
      return b.id === snapshot.sidebarBlockId;
    });
    if (sidebarBlock) openSidebar(sidebarBlock);
    else closeSidebar();
  } else {
    closeSidebar();
  }
  _suppressUndo = false;
}

function pushUndoSnapshot() {
  if (_suppressUndo) return;
  undoStack.push(captureScenarioSnapshot());
  var limit = getUndoLimit();
  while (undoStack.length > limit) undoStack.shift();
}

function clearUndoStack() {
  undoStack = [];
}

function undoLastAction() {
  if (!undoStack.length) return false;
  restoreScenarioSnapshot(undoStack.pop());
  return true;
}

function cancelLastUndoSnapshotIfUnused(used) {
  if (!used && undoStack.length) undoStack.pop();
}

function cancelActiveDrag() {
  if (_activeDrag && typeof _activeDrag.stop === "function") {
    _activeDrag.stop();
  }
  _activeDrag = null;
}
function scheduleDrawConnections() {
  if (_drawConnectionsRaf != null) return;
  _drawConnectionsRaf = window.requestAnimationFrame(function () {
    _drawConnectionsRaf = null;
    drawConnections();
  });
}

function createBlock(type, x, y, data) {
  data = data || {};
  const id = data.id || "block-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  const block = document.createElement("div");
  block.className = "block";
  block.style.left = (data.x != null ? data.x : x) + "px";
  block.style.top = (data.y != null ? data.y : y) + "px";
  block.dataset.id = id;
  block.dataset.type = type;

  const blockData = {
    id,
    type,
    data: { ...data },
    el: block,
  };

  if (typeof CanvasView !== "undefined") {
    CanvasView.normalizeData(type, blockData.data, CanvasView.getRegistry());
  } else {
    if (type === "menu" && Array.isArray(blockData.data.buttons)) {
      blockData.data.buttons = blockData.data.buttons.map(function (b) {
        if (typeof b === "string") return { text: b, url: "" };
        var o = { text: b.text || "", url: b.url || "" };
        if (b.request_contact) o.request_contact = true;
        if (b.request_location) o.request_location = true;
        return o;
      });
    }
    if (type === "message" && !blockData.data.media) {
      blockData.data.media = { type: null, files: [] };
    }
    if (type === "message" && !Array.isArray(blockData.data.inlineButtons)) {
      blockData.data.inlineButtons = [];
    }
    if (type === "command" && !blockData.data.command) blockData.data.command = "/help";
    if (type === "data") {
      if (!blockData.data.action) blockData.data.action = "set";
      if (!blockData.data.fieldType) blockData.data.fieldType = "string";
    }
    if (type === "condition" && !blockData.data.operator) blockData.data.operator = "eq";
  }

  var pluginMeta = typeof CanvasView !== "undefined" ? CanvasView.getPluginByType(type, CanvasView.getRegistry()) : null;
  var isPhantom =
    typeof CanvasView !== "undefined" &&
    CanvasView.isPhantomType &&
    CanvasView.isPhantomType(type, CanvasView.getRegistry());
  if (isPhantom) {
    block.classList.add("block-phantom");
    block.dataset.phantom = "1";
  }

  blocks.push(blockData);
  renderBlock(blockData);
  canvas.appendChild(block);
  return id;
}

window.applyScenarioPayload = function (data) {
  if (!data || typeof data !== "object") return;
  if (data.graph && typeof data.graph === "object") {
    data = Object.assign({}, data, {
      blocks: data.graph.blocks || data.blocks,
      connections: data.graph.connections || data.connections,
      tags: data.graph.tags || data.tags,
    });
  }
  selectedBlockIds.clear();
  scenarioTags = data.tags || [];
  connections = (data.connections || []).slice();
  blocks.forEach(function (b) {
    b.el.remove();
  });
  blocks = [];
  (data.blocks || []).forEach(function (block) {
    var d = Object.assign({}, block.data || {});
    delete d.el;
    createBlock(block.type, block.x || 0, block.y || 0, Object.assign({}, d, { id: block.id, x: block.x, y: block.y }));
  });
  if (!blocks.some(function (b) {
    return b.type === "start";
  })) {
    createBlock("start", 50, 100, {});
  }
  drawConnections();
  initCanvasView();
  syncBlockSelectionStyles();
  clearUndoStack();
};

function dismissAiScenarioOffer() {
  if (bot_id) {
    try {
      localStorage.setItem("scenario_ai_dismiss_" + bot_id, "1");
    } catch (e) {}
  }
  closeAiScenarioModal();
}

function openAiScenarioModal(isAuto) {
  var m = document.getElementById("ai-scenario-modal");
  if (!m) return;
  var intro = document.getElementById("ai-scenario-modal-intro");
  if (intro) {
    intro.style.display = "";
    intro.textContent = isAuto ? tr("editor.ai_intro_auto") : tr("editor.ai_intro");
  }
  var errEl = document.getElementById("ai-scenario-error");
  if (errEl) {
    errEl.style.display = "none";
    errEl.textContent = "";
  }
  var br = document.getElementById("ai-scenario-brief");
  if (br) {
    br.style.display = "none";
    br.textContent = "";
  }
  var inp = document.getElementById("ai-scenario-input");
  if (inp) inp.value = "";
  m.style.display = "flex";
}

function closeAiScenarioModal() {
  var m = document.getElementById("ai-scenario-modal");
  if (m) m.style.display = "none";
}

function maybeSuggestAiScenario() {
  if (template_id || !bot_id) return;
  try {
    if (localStorage.getItem("scenario_ai_dismiss_" + bot_id)) return;
  } catch (e) {}
  if (connections.length > 0) return;
  if (blocks.length !== 1) return;
  if (!blocks[0] || blocks[0].type !== "start") return;
  openAiScenarioModal(true);
}

function renderBlock(blockData) {
  const id = blockData.id;
  const type = blockData.type;
  const data = blockData.data;
  const el = blockData.el;

  let html = "";
  var registry = typeof CanvasView !== "undefined" ? CanvasView.getRegistry() : [];
  var phantom =
    typeof CanvasView !== "undefined" &&
    CanvasView.isPhantomType &&
    CanvasView.isPhantomType(type, registry);

  if (phantom) {
    el.classList.add("block-phantom");
    el.dataset.phantom = "1";
    el.style.removeProperty("--block-accent");
    html = CanvasView.renderPhantomBlockHtml(type, escapeHtml);
  } else {
    el.classList.remove("block-phantom");
    delete el.dataset.phantom;

  if (type === "start") {
    html = '<div class="title">' + escapeHtml(blockTitleForType("start")) + '</div><div class="preview-text">/start</div><div class="output" data-index="0"></div>';
  } else if (type === "message") {
    const text = data.text || defaultTextForType("message", "text", tr("plugin.send_message.default.text"));
    html = '<div class="title">' + escapeHtml(blockTitleForType("message")) + '</div><div class="preview-text">' + escapeHtml(text) + '</div>';
    const inlines = data.inlineButtons || [];
    if (!Array.isArray(data.inlineButtonRowBreaks) || data.inlineButtonRowBreaks.length === 0) data.inlineButtonRowBreaks = [0];
    const msgRowBreaks = getRowBreaks(blockData);
    var maxMsgRow = 0;
    if (inlines.length) {
      for (var mr = 0; mr < msgRowBreaks.length; mr++) {
        var start = msgRowBreaks[mr];
        var end = msgRowBreaks[mr + 1] != null ? msgRowBreaks[mr + 1] : inlines.length;
        var rowLen = Math.max(0, Math.min(end, inlines.length) - start);
        if (rowLen === 0) continue;
        if (rowLen > maxMsgRow) maxMsgRow = rowLen;
        var layoutKind = rowLen === 1 ? "column" : "row";
        html += '<div class="menu-buttons menu-buttons-row row-n-' + rowLen + ' layout-' + layoutKind + '" data-row-index="' + mr + '" data-row-start="' + start + '" data-layout="' + layoutKind + '">';
        html += '<div class="row-drop-zone" data-dnd-mode="into-row" data-row-index="' + mr + '" data-offset="0" data-insert-at="' + start + '"></div>';
        for (var mi = start; mi < end && mi < inlines.length; mi++) {
          var b = inlines[mi];
          var t = (b.text || "").slice(0, 25) || tr("editor.preview_empty");
          var off = mi - start;
          html += '<div class="menu-button inline-btn" draggable="true" data-btn-index="' + mi + '" data-row-index="' + mr + '" data-offset="' + off + '"><span class="inline-btn-text">' + escapeHtml(t) + '</span><div class="output" data-index="' + mi + '"></div></div>';
          html += '<div class="row-drop-zone" data-dnd-mode="into-row" data-row-index="' + mr + '" data-offset="' + (off + 1) + '" data-insert-at="' + (mi + 1) + '"></div>';
        }
        html += '</div>';
        if (mr + 1 < msgRowBreaks.length) {
          html += '<div class="row-between-drop-zone inline-row-between" data-dnd-mode="new-row" data-before-row="' + (mr + 1) + '" data-insert-at="' + msgRowBreaks[mr + 1] + '"></div>';
        }
      }
      html += '<div class="row-between-drop-zone inline-row-between row-end-drop-zone" data-dnd-mode="new-row" data-before-row="' + msgRowBreaks.length + '" data-insert-at="' + inlines.length + '"></div>';
      if (maxMsgRow >= 3) el.dataset.maxButtonsInRow = maxMsgRow; else delete el.dataset.maxButtonsInRow;
    } else {
      delete el.dataset.maxButtonsInRow;
      html += '<div class="output" data-index="0"></div>';
    }
  } else if (type === "command") {
    const cmd = (data.command || "/help").slice(0, 20);
    html = '<div class="title">' + escapeHtml(blockTitleForType("command")) + '</div><div class="preview-text">' + escapeHtml(cmd || tr("editor.preview_command_fallback")) + '</div><div class="output" data-index="0"></div>';
  } else if (type === "data") {
    var actionLabels = {
      get: tr("editor.data_action_get"),
      set: tr("editor.data_action_set"),
      add: tr("editor.data_action_add"),
      subtract: tr("editor.data_action_subtract"),
    };
    var action = actionLabels[data.action] || tr("editor.data_configure");
    var field = (data.fieldName || tr("editor.data_field_default")).slice(0, 30);
    var typeLabel = data.fieldType === "number" ? tr("editor.data_number_suffix") : "";
    html = '<div class="title">' + escapeHtml(blockTitleForType("data")) + '</div><div class="preview-text">' + escapeHtml(action) + ': ' + escapeHtml(field || "...") + typeLabel + '</div><div class="output" data-index="0"></div>';
  } else if (type === "condition") {
    const cond = (data.fieldName || tr("editor.preview_condition_if")).slice(0, 25);
    html = '<div class="title">' + escapeHtml(blockTitleForType("condition")) + '</div><div class="preview-text">' + escapeHtml(cond || tr("editor.preview_condition_if")) + '</div><div class="condition-outputs"><div class="output condition-yes" data-index="0" title="' + escapeHtml(tr("editor.condition_yes")) + '"></div><div class="output condition-no" data-index="1" title="' + escapeHtml(tr("editor.condition_no")) + '"></div></div>';
  } else if (type === "note") {
    const noteText = (data.text || "").slice(0, 60);
    html = '<div class="title">' + escapeHtml(blockTitleForType("note")) + '</div><div class="preview-text note-preview">' + escapeHtml(noteText || tr("editor.preview_note_default")) + '</div>';
  } else if (type === "menu") {
    const name = data.name || defaultTextForType("menu", "name", tr("plugin.menu_node.default.name"));
    const tagLabel = getBlockTagLabel(blockData);
    html = '<div class="title">' + escapeHtml(name) + '</div><div class="tag-label">' + escapeHtml(tagLabel) + '</div><div class="preview-text">' + escapeHtml((data.text || "").slice(0, 50) || "...") + '</div>';
    const menuBtns = data.buttons || [];
    if (!Array.isArray(data.buttonRowBreaks) || data.buttonRowBreaks.length === 0) data.buttonRowBreaks = menuBtns.length ? [0] : [];
    if (menuBtns.length === 0) { html += '<div class="output" data-index="0"></div>'; delete el.dataset.maxButtonsInRow; } else {
      const menuRowBreaks = getRowBreaks(blockData);
      var maxMenuRow = 0;
      for (var r = 0; r < menuRowBreaks.length; r++) {
        var start = menuRowBreaks[r];
        var end = menuRowBreaks[r + 1] != null ? menuRowBreaks[r + 1] : menuBtns.length;
        var rowLen = Math.max(0, Math.min(end, menuBtns.length) - start);
        if (rowLen === 0) continue;
        if (rowLen > maxMenuRow) maxMenuRow = rowLen;
        var menuLayout = rowLen === 1 ? "column" : "row";
        html += '<div class="menu-buttons menu-buttons-row row-n-' + rowLen + ' layout-' + menuLayout + '" data-row-index="' + r + '" data-row-start="' + start + '" data-layout="' + menuLayout + '">';
        html += '<div class="row-drop-zone" data-dnd-mode="into-row" data-row-index="' + r + '" data-offset="0" data-insert-at="' + start + '"></div>';
        for (var i = start; i < end && i < menuBtns.length; i++) {
          var btn = menuBtns[i];
          var txt = typeof btn === "string" ? btn : (btn.text || "");
          var spec = "";
          if (btn && typeof btn === "object") {
            if (btn.request_contact) {
              spec += ' <span class="menu-spec-badge" title="' + escapeHtml(tr("editor.contact_badge")) + '">' + escapeHtml(tr("editor.contact_badge")) + "</span>";
            }
            if (btn.request_location) {
              spec += ' <span class="menu-spec-badge" title="' + escapeHtml(tr("editor.location_badge")) + '">' + escapeHtml(tr("editor.location_badge")) + "</span>";
            }
          }
          var mOff = i - start;
          html += '<div class="menu-button" draggable="true" data-btn-index="' + i + '" data-row-index="' + r + '" data-offset="' + mOff + '"><span>' + escapeHtml(txt || tr("editor.preview_empty")) + spec + '</span><div class="output" data-index="' + i + '"></div></div>';
          html += '<div class="row-drop-zone" data-dnd-mode="into-row" data-row-index="' + r + '" data-offset="' + (mOff + 1) + '" data-insert-at="' + (i + 1) + '"></div>';
        }
        html += '</div>';
        if (r + 1 < menuRowBreaks.length) {
          html += '<div class="row-between-drop-zone" data-dnd-mode="new-row" data-before-row="' + (r + 1) + '" data-insert-at="' + menuRowBreaks[r + 1] + '"></div>';
        }
      }
      html += '<div class="row-between-drop-zone row-end-drop-zone" data-dnd-mode="new-row" data-before-row="' + menuRowBreaks.length + '" data-insert-at="' + menuBtns.length + '"></div>';
      if (maxMenuRow >= 3) el.dataset.maxButtonsInRow = maxMenuRow; else delete el.dataset.maxButtonsInRow;
    }
  } else if (typeof CanvasView !== "undefined") {
    var pluginPreview = CanvasView.getPluginByType(type, registry);
    if (pluginPreview) {
      var previewText = (data.text || data.inputPrompt || pluginPreview.description || "").slice(0, 60);
      html =
        '<div class="title">' + escapeHtml(pluginPreview.name || type) +
        '</div><div class="preview-text">' + escapeHtml(previewText || pluginPreview.name || type) +
        '</div><div class="output" data-index="0"></div>';
    }
  }

  }

  if (!html && phantom) {
    html = CanvasView.renderPhantomBlockHtml(type, escapeHtml);
  }

  el.innerHTML = html;

  if (type !== "start") {
    const tb = document.createElement("div");
    tb.className = "block-toolbar";
    const dup = document.createElement("button");
    dup.textContent = "📄";
    dup.title = tr("editor.duplicate_block");
    dup.onclick = function (e) { e.stopPropagation(); duplicateBlock(blockData); };
    const del = document.createElement("button");
    del.textContent = "🗑";
    del.title = tr("common.delete");
    del.onclick = function (e) { e.stopPropagation(); deleteBlock(blockData); };
    tb.appendChild(dup);
    tb.appendChild(del);
    el.appendChild(tb);
  }

  el.onmousedown = function (e) {
    if (e.button !== 0) return;
    if (e.target.closest(".menu-button") || e.target.classList.contains("output") || e.target.closest(".block-toolbar")) return;
    e.preventDefault();
    try {
      if (window.getSelection && window.getSelection().removeAllRanges) window.getSelection().removeAllRanges();
    } catch (err) {}
    if (e.ctrlKey || e.metaKey) {
      if (selectedBlockIds.has(blockData.id)) selectedBlockIds.delete(blockData.id);
      else selectedBlockIds.add(blockData.id);
      syncBlockSelectionStyles();
      return;
    }
    if (!selectedBlockIds.has(blockData.id)) {
      selectedBlockIds.clear();
      selectedBlockIds.add(blockData.id);
      syncBlockSelectionStyles();
    }
    startDrag(e, el, blockData);
  };

  if (type !== "start") {
    el.onclick = function (e) {
      if (e.target.classList.contains("output")) return;
      if (e.target.closest(".block-toolbar")) return;
      if (blockData._dragMoved) {
        blockData._dragMoved = false;
        return;
      }
      e.stopPropagation();
      openSidebar(blockData);
    };
  }

  el.querySelectorAll(".output").forEach(function (out) {
    out.style.cursor = "crosshair";
    out.onmousedown = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (pendingConnection && pendingConnection._upHandler) {
        pendingConnection._upHandler();
      }
      pendingConnection = {
        from: id,
        outputIndex: out.dataset.index || "0",
        mouseX: e.clientX,
        mouseY: e.clientY
      };
      var moveHandler = function (ev) {
        if (pendingConnection) {
          pendingConnection.mouseX = ev.clientX;
          pendingConnection.mouseY = ev.clientY;
          scheduleDrawConnections();
        }
      };
      var upHandler = function () {
        window.removeEventListener("mousemove", moveHandler);
        window.removeEventListener("mouseup", upHandler);
        if (pendingConnection) {
          pendingConnection._moveHandler = null;
          pendingConnection._upHandler = null;
          pendingConnection = null;
          drawConnections();
        }
      };
      pendingConnection._moveHandler = moveHandler;
      pendingConnection._upHandler = upHandler;
      window.addEventListener("mousemove", moveHandler);
      window.addEventListener("mouseup", upHandler);
      drawConnections();
    };
  });

  if (type === "menu") {
    setupMenuButtonDrag(blockData, true);
  }
  if (type === "message" && (blockData.data.inlineButtons || []).length) {
    setupInlinePreviewDrag(blockData);
  }

  if (typeof CanvasView !== "undefined" && CanvasView.applyBlockAccent) {
    var accentPlugin = CanvasView.getPluginByType(type, registry);
    CanvasView.applyBlockAccent(el, blockData, accentPlugin);
  }

  el.querySelectorAll(".output").forEach(function (out) {
    var idx = out.dataset.index != null ? out.dataset.index : "0";
    var color = getOutputColor(id, idx);
    out.style.background = color;
  });
}

function remapOutputIndexes(blockId, fromIndex, toIndex) {
  connections.forEach(function (c) {
    if (c.from !== blockId) return;
    var out = parseInt(c.outputIndex, 10);
    if (out === fromIndex) c.outputIndex = toIndex;
    else if (fromIndex < toIndex && out > fromIndex && out <= toIndex) c.outputIndex = out - 1;
    else if (fromIndex > toIndex && out >= toIndex && out < fromIndex) c.outputIndex = out + 1;
  });
}

function remapOutputSwap(blockId, i, j) {
  var swapMap = {};
  swapMap[i] = j;
  swapMap[j] = i;
  connections.forEach(function (c) {
    if (c.from !== blockId) return;
    var out = parseInt(c.outputIndex, 10);
    if (swapMap[out] !== undefined) c.outputIndex = swapMap[out];
  });
}

function normalizeBreaksList(breaks, len) {
  if (!len) return [];
  var b = Array.isArray(breaks) ? breaks.slice() : [0];
  b = b.filter(function (x) { return typeof x === "number" && x >= 0 && x < len; }).sort(function (a, c) { return a - c; });
  if (!b.length || b[0] !== 0) b.unshift(0);
  var out = [];
  for (var i = 0; i < b.length; i++) {
    if (i === 0 || b[i] !== out[out.length - 1]) out.push(b[i]);
  }
  return out;
}

function buildButtonRows(arr, breaks) {
  var rows = [];
  var b = normalizeBreaksList(breaks, arr.length);
  for (var i = 0; i < b.length; i++) {
    var start = b[i];
    var end = i + 1 < b.length ? b[i + 1] : arr.length;
    if (end > start) rows.push(arr.slice(start, end));
  }
  if (!rows.length && arr.length) rows.push(arr.slice());
  return rows;
}

function flattenButtonRows(rows) {
  var arr = [];
  var breaks = [];
  rows.forEach(function (row) {
    if (!row || !row.length) return;
    breaks.push(arr.length);
    for (var i = 0; i < row.length; i++) arr.push(row[i]);
  });
  return { arr: arr, breaks: breaks.length ? breaks : (arr.length ? [0] : []) };
}

/** dest: { kind:'into-row', rowIndex, offset } | { kind:'new-row', beforeRowIndex } */
function relocateCardButton(arr, breaks, fromIndex, dest) {
  if (!arr || !arr.length || fromIndex < 0 || fromIndex >= arr.length) return null;
  var rows = buildButtonRows(arr, breaks);
  var item = null;
  var fromRow = -1;
  var fromOff = -1;
  var flat = 0;
  for (var r = 0; r < rows.length; r++) {
    for (var c = 0; c < rows[r].length; c++) {
      if (flat === fromIndex) {
        item = rows[r][c];
        fromRow = r;
        fromOff = c;
        break;
      }
      flat++;
    }
    if (item !== null && fromRow >= 0) break;
  }
  if (fromRow < 0) return null;

  rows[fromRow].splice(fromOff, 1);

  var placedRow = -1;
  var placedOff = -1;

  if (dest.kind === "into-row") {
    var tr = dest.rowIndex;
    var off = dest.offset;
    if (fromRow === tr && fromOff < off) off -= 1;
    if (rows[fromRow].length === 0) {
      rows.splice(fromRow, 1);
      if (tr > fromRow) tr -= 1;
    }
    if (tr < 0) tr = 0;
    if (tr >= rows.length) {
      rows.push([item]);
      placedRow = rows.length - 1;
      placedOff = 0;
    } else {
      if (off < 0) off = 0;
      if (off > rows[tr].length) off = rows[tr].length;
      rows[tr].splice(off, 0, item);
      placedRow = tr;
      placedOff = off;
    }
  } else if (dest.kind === "new-row") {
    var before = dest.beforeRowIndex;
    if (rows[fromRow].length === 0) {
      rows.splice(fromRow, 1);
      if (before > fromRow) before -= 1;
    }
    if (before < 0) before = 0;
    if (before > rows.length) before = rows.length;
    rows.splice(before, 0, [item]);
    placedRow = before;
    placedOff = 0;
  } else {
    return null;
  }

  var flatResult = flattenButtonRows(rows);
  var newIndex = 0;
  for (var pr = 0; pr < placedRow; pr++) newIndex += rows[pr].length;
  newIndex += placedOff;
  flatResult.fromIndex = fromIndex;
  flatResult.toIndex = newIndex;
  return flatResult;
}

function getCardButtonsState(blockData) {
  if (blockData.type === "message") {
    return {
      arr: (blockData.data.inlineButtons || []).slice(),
      breaks: blockData.data.inlineButtonRowBreaks || [0],
      set: function (arr, breaks) {
        blockData.data.inlineButtons = arr;
        blockData.data.inlineButtonRowBreaks = breaks;
      },
      btnSelector: ".menu-button.inline-btn",
    };
  }
  return {
    arr: (blockData.data.buttons || []).slice(),
    breaks: blockData.data.buttonRowBreaks || [0],
    set: function (arr, breaks) {
      blockData.data.buttons = arr;
      blockData.data.buttonRowBreaks = breaks;
    },
    btnSelector: ".menu-button",
  };
}

function applyCardButtonLayout(blockData, result) {
  if (!result) return;
  var state = getCardButtonsState(blockData);
  var len = state.arr.length;
  state.set(result.arr, result.breaks);
  if (result.fromIndex != null && result.toIndex != null && result.fromIndex !== result.toIndex) {
    remapOutputIndexes(blockData.id, result.fromIndex, result.toIndex);
  }
  var indexMap = null;
  if (result.fromIndex != null && result.toIndex != null) {
    indexMap = buildNewToOldIndexMap(result.fromIndex, result.toIndex, len);
  }
  animateCardButtonsFlip(blockData.el, function () {
    renderBlock(blockData);
    drawConnections();
  }, indexMap);
}

function buildNewToOldIndexMap(fromIndex, toIndex, len) {
  var map = {};
  for (var old = 0; old < len; old++) {
    var neu = old;
    if (old === fromIndex) neu = toIndex;
    else if (fromIndex < toIndex && old > fromIndex && old <= toIndex) neu = old - 1;
    else if (fromIndex > toIndex && old >= toIndex && old < fromIndex) neu = old + 1;
    map[String(neu)] = String(old);
  }
  return map;
}

function animateCardButtonsFlip(blockEl, mutateFn, newToOldMap) {
  if (!blockEl || typeof mutateFn !== "function") {
    if (typeof mutateFn === "function") mutateFn();
    return;
  }
  var before = {};
  blockEl.querySelectorAll(".menu-button[data-btn-index]").forEach(function (btn) {
    var key = btn.getAttribute("data-btn-index");
    if (key == null) return;
    var r = btn.getBoundingClientRect();
    before[key] = { left: r.left, top: r.top };
  });
  mutateFn();
  var afterBtns = blockEl.querySelectorAll(".menu-button[data-btn-index]");
  if (!afterBtns.length || !Object.keys(before).length) return;
  blockEl.classList.add("card-dnd-animating");
  afterBtns.forEach(function (btn) {
    var newKey = btn.getAttribute("data-btn-index");
    var oldKey = newToOldMap && newToOldMap[newKey] != null ? newToOldMap[newKey] : newKey;
    var prev = before[oldKey];
    if (!prev) return;
    var next = btn.getBoundingClientRect();
    var dx = prev.left - next.left;
    var dy = prev.top - next.top;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
    btn.style.transition = "none";
    btn.style.transform = "translate(" + dx + "px," + dy + "px)";
    void btn.offsetWidth;
    btn.style.transition = "transform 0.22s cubic-bezier(0.2, 0, 0, 1)";
    btn.style.transform = "";
  });
  window.setTimeout(function () {
    afterBtns.forEach(function (btn) {
      btn.style.transition = "";
      btn.style.transform = "";
    });
    blockEl.classList.remove("card-dnd-animating");
  }, 240);
}

function swapCardButtons(blockData, i, j) {
  var state = getCardButtonsState(blockData);
  var arr = state.arr;
  if (i === j || i < 0 || j < 0 || i >= arr.length || j >= arr.length) return;
  pushUndoSnapshot();
  var t = arr[i];
  arr[i] = arr[j];
  arr[j] = t;
  state.set(arr, normalizeBreaksList(state.breaks, arr.length));
  remapOutputSwap(blockData.id, i, j);
  var map = {};
  for (var k = 0; k < arr.length; k++) map[String(k)] = String(k);
  map[String(i)] = String(j);
  map[String(j)] = String(i);
  animateCardButtonsFlip(blockData.el, function () {
    renderBlock(blockData);
    drawConnections();
  }, map);
}

function moveCardButton(blockData, fromIndex, dest) {
  var state = getCardButtonsState(blockData);
  var result = relocateCardButton(state.arr, state.breaks, fromIndex, dest);
  if (!result) return;
  if (result.fromIndex === result.toIndex) {
    // layout (breaks) may still change when extracting/joining
    var sameArr = result.arr.length === state.arr.length;
    var breaksChanged = JSON.stringify(result.breaks) !== JSON.stringify(normalizeBreaksList(state.breaks, state.arr.length));
    if (sameArr && !breaksChanged) return;
  }
  pushUndoSnapshot();
  applyCardButtonLayout(blockData, result);
}

function fixRowBreaksAfterRemove(breaks, fromIndex) {
  var b = (breaks || []).slice();
  b = b.map(function (x) { return x > fromIndex ? x - 1 : x; }).filter(function (x) { return x >= 0; }).sort(function (a, c) { return a - c; });
  if (b.length && b[0] !== 0) b.unshift(0);
  var out = [];
  for (var i = 0; i < b.length; i++) { if (i === 0 || b[i] !== out[out.length - 1]) out.push(b[i]); }
  return out;
}

function clearCardDnDHints(el, opts) {
  if (!el) return;
  opts = opts || {};
  el.querySelectorAll(".menu-drop-placeholder, .inline-drop-placeholder, .dnd-insert-line").forEach(function (ph) { ph.remove(); });
  el.querySelectorAll(".menu-buttons-row.drag-over-row").forEach(function (n) { n.classList.remove("drag-over-row"); });
  el.querySelectorAll(".row-drop-zone.drag-over-zone, .row-between-drop-zone.drag-over-zone").forEach(function (n) { n.classList.remove("drag-over-zone"); });
  el.querySelectorAll(".menu-button.drag-over").forEach(function (n) { n.classList.remove("drag-over"); });
  if (opts.endDrag) {
    el.querySelectorAll(".menu-button.dragging").forEach(function (n) { n.classList.remove("dragging"); });
    el.classList.remove("card-dnd-active");
  }
}

function getOrCreateInsertLine(host, vertical) {
  var line = host.querySelector(":scope > .dnd-insert-line");
  if (!line) {
    line = document.createElement("div");
    line.className = "dnd-insert-line";
    line.setAttribute("aria-hidden", "true");
    host.appendChild(line);
  }
  line.classList.toggle("dnd-insert-line-vertical", !!vertical);
  line.classList.toggle("dnd-insert-line-horizontal", !vertical);
  return line;
}

function setCardDragGhost(e, btnEl) {
  try {
    var label = "";
    var textNode = btnEl.querySelector(".inline-btn-text, span");
    if (textNode) label = (textNode.textContent || "").trim();
    if (!label) label = tr("editor.btn_inline_default");

    var ghost = document.createElement("div");
    ghost.className = "menu-button-drag-ghost";
    ghost.textContent = label;

    var cs = window.getComputedStyle(document.documentElement);
    var isDark = document.documentElement.classList.contains("theme-dark");
    var bg = isDark ? "#27272a" : (cs.getPropertyValue("--bg-elevated").trim() || "#ffffff");
    var fg = isDark ? "#f4f4f5" : (cs.getPropertyValue("--text-main").trim() || "#18181b");
    var accent = cs.getPropertyValue("--accent-ui").trim() || "#2563eb";
    ghost.style.background = bg;
    ghost.style.color = fg;
    ghost.style.borderColor = accent;

    document.body.appendChild(ghost);
    var rect = btnEl.getBoundingClientRect();
    ghost.style.width = Math.max(72, Math.min(220, rect.width)) + "px";
    e.dataTransfer.setDragImage(ghost, Math.min(rect.width / 2, 36), Math.min(rect.height / 2, 14));
    window.setTimeout(function () {
      if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
    }, 40);
  } catch (err) { /* setDragImage not supported */ }
}

function isInButtonCenter(btnEl, clientX, clientY) {
  var r = btnEl.getBoundingClientRect();
  var cx = r.left + r.width / 2;
  var cy = r.top + r.height / 2;
  return Math.abs(clientX - cx) < r.width * 0.28 && Math.abs(clientY - cy) < r.height * 0.35;
}

function setupCardButtonDrag(blockData) {
  var el = blockData.el;
  if (!el) return;
  var state = getCardButtonsState(blockData);
  var pending = null;
  var hintKey = "";
  var rafId = 0;
  var queued = null;
  var btnSelector = state.btnSelector;

  function applyHint(next) {
    if (!next) return;
    var key = next.key;
    if (key === hintKey) {
      pending = next.pending;
      return;
    }
    hintKey = key;
    pending = next.pending;

    el.querySelectorAll(".menu-buttons-row.drag-over-row").forEach(function (n) { n.classList.remove("drag-over-row"); });
    el.querySelectorAll(".row-drop-zone.drag-over-zone, .row-between-drop-zone.drag-over-zone").forEach(function (n) { n.classList.remove("drag-over-zone"); });
    el.querySelectorAll(".menu-button.drag-over").forEach(function (n) { n.classList.remove("drag-over"); });
    el.querySelectorAll(".dnd-insert-line").forEach(function (n) { n.remove(); });

    el.classList.add("card-dnd-active");

    if (next.kind === "swap") {
      if (next.btnEl) next.btnEl.classList.add("drag-over");
      return;
    }
    if (next.kind === "into-row") {
      if (next.rowEl) next.rowEl.classList.add("drag-over-row");
      if (next.zoneEl) {
        next.zoneEl.classList.add("drag-over-zone");
        getOrCreateInsertLine(next.zoneEl, true);
      }
      return;
    }
    if (next.kind === "new-row") {
      if (next.zoneEl) {
        next.zoneEl.classList.add("drag-over-zone");
        getOrCreateInsertLine(next.zoneEl, false);
      }
    }
  }

  function queueHint(next) {
    queued = next;
    if (rafId) return;
    rafId = window.requestAnimationFrame(function () {
      rafId = 0;
      var job = queued;
      queued = null;
      if (job) applyHint(job);
    });
  }

  el.querySelectorAll(btnSelector).forEach(function (btnEl) {
    var btnIndex = parseInt(btnEl.getAttribute("data-btn-index"), 10);
    if (isNaN(btnIndex)) return;
    btnEl.draggable = true;
    btnEl.ondragstart = function (e) {
      if (e.target.closest && e.target.closest(".output")) {
        e.preventDefault();
        return;
      }
      _draggingBlockId = blockData.id;
      hintKey = "";
      pending = null;
      e.dataTransfer.setData("index", String(btnIndex));
      e.dataTransfer.setData("blockId", blockData.id);
      e.dataTransfer.effectAllowed = "move";
      btnEl.classList.add("dragging");
      el.classList.add("card-dnd-active");
      setCardDragGhost(e, btnEl);
    };
    btnEl.ondragend = function () {
      _draggingBlockId = null;
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
      queued = null;
      hintKey = "";
      pending = null;
      clearCardDnDHints(el, { endDrag: true });
    };
    btnEl.ondragover = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (_draggingBlockId !== blockData.id) return;
      e.dataTransfer.dropEffect = "move";
      var rowEl = btnEl.closest(".menu-buttons-row");
      if (!rowEl) return;
      var rowIndex = parseInt(rowEl.getAttribute("data-row-index"), 10);
      var offsetInRow = parseInt(btnEl.getAttribute("data-offset"), 10);
      if (isNaN(rowIndex) || isNaN(offsetInRow)) return;

      if (isInButtonCenter(btnEl, e.clientX, e.clientY)) {
        queueHint({
          key: "swap:" + btnIndex,
          kind: "swap",
          btnEl: btnEl,
          pending: { kind: "swap", targetIndex: btnIndex },
        });
        return;
      }

      var rect = btnEl.getBoundingClientRect();
      var insertOffset = e.clientX < rect.left + rect.width / 2 ? offsetInRow : offsetInRow + 1;
      var zoneEl = rowEl.querySelector('.row-drop-zone[data-offset="' + insertOffset + '"]');
      queueHint({
        key: "row:" + rowIndex + ":" + insertOffset,
        kind: "into-row",
        rowEl: rowEl,
        zoneEl: zoneEl,
        pending: { kind: "into-row", rowIndex: rowIndex, offset: insertOffset },
      });
    };
    btnEl.ondragleave = function (e) {
      if (!btnEl.contains(e.relatedTarget)) btnEl.classList.remove("drag-over");
    };
    btnEl.ondrop = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer.getData("blockId") !== blockData.id) return;
      var from = parseInt(e.dataTransfer.getData("index"), 10);
      var dest = pending;
      clearCardDnDHints(el, { endDrag: true });
      pending = null;
      hintKey = "";
      if (isNaN(from) || !dest) return;
      if (dest.kind === "swap") {
        if (from !== dest.targetIndex) swapCardButtons(blockData, from, dest.targetIndex);
      } else {
        moveCardButton(blockData, from, dest);
      }
    };
  });

  el.querySelectorAll(".row-drop-zone").forEach(function (zoneEl) {
    zoneEl.ondragover = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (_draggingBlockId !== blockData.id) return;
      e.dataTransfer.dropEffect = "move";
      var rowEl = zoneEl.closest(".menu-buttons-row");
      if (!rowEl) return;
      var offset = parseInt(zoneEl.getAttribute("data-offset"), 10);
      if (isNaN(offset)) offset = 0;
      var rowIndex = parseInt(rowEl.getAttribute("data-row-index"), 10);
      queueHint({
        key: "row:" + rowIndex + ":" + offset,
        kind: "into-row",
        rowEl: rowEl,
        zoneEl: zoneEl,
        pending: { kind: "into-row", rowIndex: rowIndex, offset: offset },
      });
    };
    zoneEl.ondrop = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer.getData("blockId") !== blockData.id) return;
      var from = parseInt(e.dataTransfer.getData("index"), 10);
      var dest = pending;
      clearCardDnDHints(el, { endDrag: true });
      pending = null;
      hintKey = "";
      if (isNaN(from)) return;
      if (!dest || dest.kind !== "into-row") {
        var rowEl = zoneEl.closest(".menu-buttons-row");
        var offset = parseInt(zoneEl.getAttribute("data-offset"), 10);
        var rowIndex = rowEl ? parseInt(rowEl.getAttribute("data-row-index"), 10) : 0;
        dest = { kind: "into-row", rowIndex: rowIndex, offset: isNaN(offset) ? 0 : offset };
      }
      moveCardButton(blockData, from, dest);
    };
  });

  el.querySelectorAll(".row-between-drop-zone").forEach(function (zoneEl) {
    zoneEl.ondragover = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (_draggingBlockId !== blockData.id) return;
      e.dataTransfer.dropEffect = "move";
      var before = parseInt(zoneEl.getAttribute("data-before-row"), 10);
      if (isNaN(before)) before = 0;
      queueHint({
        key: "new:" + before,
        kind: "new-row",
        zoneEl: zoneEl,
        pending: { kind: "new-row", beforeRowIndex: before },
      });
    };
    zoneEl.ondrop = function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (e.dataTransfer.getData("blockId") !== blockData.id) return;
      var from = parseInt(e.dataTransfer.getData("index"), 10);
      var dest = pending;
      clearCardDnDHints(el, { endDrag: true });
      pending = null;
      hintKey = "";
      if (isNaN(from)) return;
      if (!dest || dest.kind !== "new-row") {
        var before = parseInt(zoneEl.getAttribute("data-before-row"), 10);
        dest = { kind: "new-row", beforeRowIndex: isNaN(before) ? 0 : before };
      }
      moveCardButton(blockData, from, dest);
    };
  });
}

function setupMenuButtonDrag(blockData, enable) {
  if (!enable) return;
  setupCardButtonDrag(blockData);
}

function setupInlinePreviewDrag(blockData) {
  setupCardButtonDrag(blockData);
}

var OUTPUT_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04", "#9333ea", "#0891b2", "#ea580c", "#be185d", "#4f46e5", "#0d9488", "#b45309", "#7c3aed"];

function getRowBreaks(block) {
  if (block.type === "message") {
    var breaks = block.data.inlineButtonRowBreaks;
    if (!Array.isArray(breaks) || breaks.length === 0) return [0];
    if (breaks[0] !== 0) return [0].concat(breaks);
    return breaks;
  }
  if (block.type === "menu") {
    var breaks = block.data.buttonRowBreaks;
    if (!Array.isArray(breaks) || breaks.length === 0) return [0];
    if (breaks[0] !== 0) return [0].concat(breaks);
    return breaks;
  }
  if (block.type === "condition") return [0, 1];
  return [0];
}

function getRowForIndex(index, rowBreaks, totalLen) {
  var rowIndex = 0;
  for (var r = 0; r < rowBreaks.length - 1; r++) {
    if (index >= rowBreaks[r] && index < rowBreaks[r + 1]) { rowIndex = r; break; }
    if (index >= rowBreaks[r]) rowIndex = r;
  }
  if (index >= rowBreaks[rowBreaks.length - 1]) rowIndex = rowBreaks.length - 1;
  var rowStart = rowBreaks[rowIndex];
  var rowEnd = rowBreaks[rowIndex + 1] != null ? rowBreaks[rowIndex + 1] : totalLen;
  return { rowIndex: rowIndex, rowStart: rowStart, rowLen: rowEnd - rowStart };
}

function getOutputColor(blockId, outputIndex) {
  var block = blocks.find(function (b) { return b.id === blockId; });
  if (!block) return "#888";
  var outIdx = parseInt(String(outputIndex), 10);
  if (block.type === "condition") return outIdx === 0 ? "#16a34a" : "#dc2626";
  var btns = block.type === "message" ? (block.data.inlineButtons || []) : (block.data.buttons || []);
  if (btns.length === 0) return "#888";
  var rowBreaks = getRowBreaks(block);
  var row = getRowForIndex(outIdx, rowBreaks, btns.length);
  if (row.rowLen > 1) return OUTPUT_COLORS[outIdx % OUTPUT_COLORS.length];
  return "#888";
}

function getConnectionStart(blockId, outputIndex) {
  var blockEl = document.querySelector("[data-id=\"" + blockId + "\"]");
  var block = blocks.find(function (b) { return b.id === blockId; });
  var outEl = blockEl ? blockEl.querySelector(".output[data-index=\"" + outputIndex + "\"]") : null;
  if (!outEl) return null;
  var outIdx = parseInt(String(outputIndex), 10);
  var btns = block && block.type === "message" ? (block.data.inlineButtons || []) : (block && block.type === "menu" ? (block.data.buttons || []) : []);
  if (btns.length && block) {
    var rowBreaks = getRowBreaks(block);
    var row = getRowForIndex(outIdx, rowBreaks, btns.length);
    if (row.rowLen > 1) {
      var blockRect = blockEl.getBoundingClientRect();
      var firstInRow = blockEl.querySelector(".output[data-index=\"" + row.rowStart + "\"]");
      var rowCenterY = firstInRow ? (firstInRow.getBoundingClientRect().top + firstInRow.getBoundingClientRect().bottom) / 2 : blockRect.top + blockRect.height / 2;
      return { x: blockRect.right, y: rowCenterY };
    }
  }
  var r = outEl.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

function getBlockTagLabel(block) {
  var tagId = block.data.tagId || block.data.tag;
  if (tagId && scenarioTags && scenarioTags.length) {
    var t = scenarioTags.find(function (x) { return x.id === tagId; });
    if (t) return "#" + (t.name || tagId);
  }
  if (block.data.tag && String(block.data.tag).indexOf("tag_") !== 0) return "#" + block.data.tag;
  return block.data.name || block.id;
}

function startDrag(e, el, blockData) {
  if (e.button !== 0) return;
  cancelActiveDrag();
  pushUndoSnapshot();
  const startX = e.clientX;
  const startY = e.clientY;
  var toMove = [];
  if (selectedBlockIds.size > 0 && selectedBlockIds.has(blockData.id)) {
    toMove = Array.from(selectedBlockIds).map(function (id) {
      return blocks.find(function (b) { return b.id === id; });
    }).filter(Boolean);
  } else {
    toMove = [blockData];
  }
  var starts = toMove.map(function (b) {
    return {
      b: b,
      left: parseFloat(b.el.style.left) || 0,
      top: parseFloat(b.el.style.top) || 0,
    };
  });
  toMove.forEach(function (b) { b._dragMoved = false; });

  function move(ev) {
    const rawDx = ev.clientX - startX;
    const rawDy = ev.clientY - startY;
    if (!toMove[0]._dragMoved && Math.abs(rawDx) < DRAG_THRESHOLD && Math.abs(rawDy) < DRAG_THRESHOLD) return;
    toMove.forEach(function (b) { b._dragMoved = true; });
    const dx = rawDx / scale;
    const dy = rawDy / scale;
    starts.forEach(function (s) {
      s.b.el.style.left = (s.left + dx) + "px";
      s.b.el.style.top = (s.top + dy) + "px";
    });
    scheduleDrawConnections();
  }

  function stop() {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", stop);
    if (_activeDrag && _activeDrag.stop === stop) _activeDrag = null;
    cancelLastUndoSnapshotIfUnused(toMove[0]._dragMoved);
    drawConnections();
  }

  _activeDrag = { stop: stop };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", stop);
}

function drawConnections() {
  if (!svg) return;
  var wrapperRect = canvasWrapper.getBoundingClientRect();
  var ns = "http://www.w3.org/2000/svg";
  var defs = document.createElementNS(ns, "defs");
  var mPending = document.createElementNS(ns, "marker");
  mPending.setAttribute("id", "arrow-pending");
  mPending.setAttribute("viewBox", "0 0 10 10");
  mPending.setAttribute("refX", "9");
  mPending.setAttribute("refY", "5");
  mPending.setAttribute("markerWidth", "6");
  mPending.setAttribute("markerHeight", "6");
  mPending.setAttribute("orient", "auto");
  var pPending = document.createElementNS(ns, "path");
  pPending.setAttribute("d", "M0,0 L10,5 L0,10 Z");
  pPending.setAttribute("fill", "#555");
  mPending.appendChild(pPending);
  defs.appendChild(mPending);
  connections.forEach(function (conn, idx) {
    var color = getOutputColor(conn.from, conn.outputIndex != null ? conn.outputIndex : "0");
    var m = document.createElementNS(ns, "marker");
    m.setAttribute("id", "arrow-" + idx);
    m.setAttribute("viewBox", "0 0 10 10");
    m.setAttribute("refX", "9");
    m.setAttribute("refY", "5");
    m.setAttribute("markerWidth", "6");
    m.setAttribute("markerHeight", "6");
    m.setAttribute("orient", "auto");
    var p = document.createElementNS(ns, "path");
    p.setAttribute("d", "M0,0 L10,5 L0,10 Z");
    p.setAttribute("fill", color);
    m.appendChild(p);
    defs.appendChild(m);
  });
  svg.innerHTML = "";
  svg.appendChild(defs);

  var offsetX = 50000;
  var offsetY = 50000;
  function toSvg(x, y) {
    return {
      x: (x - wrapperRect.left + offsetX - panX) / scale,
      y: (y - wrapperRect.top + offsetY - panY) / scale
    };
  }

  if (pendingConnection && pendingConnection.mouseX != null) {
    var outIdx = pendingConnection.outputIndex != null ? String(pendingConnection.outputIndex) : "0";
    var start = getConnectionStart(pendingConnection.from, outIdx);
    if (start) {
      var x1 = (start.x - wrapperRect.left + offsetX - panX) / scale;
      var y1 = (start.y - wrapperRect.top + offsetY - panY) / scale;
      var p2 = toSvg(pendingConnection.mouseX, pendingConnection.mouseY);
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M" + x1 + "," + y1 + " C" + (x1 + 50) + "," + y1 + " " + (p2.x - 50) + "," + p2.y + " " + p2.x + "," + p2.y);
      path.setAttribute("stroke", "#555");
      path.setAttribute("stroke-width", "2");
      path.setAttribute("stroke-dasharray", "6 4");
      path.setAttribute("fill", "none");
      path.setAttribute("marker-end", "url(#arrow-pending)");
      path.style.pointerEvents = "none";
      svg.appendChild(path);
    }
  }

  connections.forEach(function (conn, idx) {
    var outIdx = conn.outputIndex != null ? String(conn.outputIndex) : "0";
    var color = getOutputColor(conn.from, outIdx);
    var start = getConnectionStart(conn.from, outIdx);
    const toEl = document.querySelector("[data-id=\"" + conn.to + "\"]");
    if (!start || !toEl) return;
    const tr = toEl.getBoundingClientRect();
    const x1 = (start.x - wrapperRect.left + offsetX - panX) / scale;
    const y1 = (start.y - wrapperRect.top + offsetY - panY) / scale;
    const x2 = (tr.left - 6 - wrapperRect.left + offsetX - panX) / scale;
    const y2 = (tr.top + tr.height / 2 - wrapperRect.top + offsetY - panY) / scale;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M" + x1 + "," + y1 + " C" + (x1 + 50) + "," + y1 + " " + (x2 - 50) + "," + y2 + " " + x2 + "," + y2);
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "2");
    path.setAttribute("fill", "none");
    path.setAttribute("marker-end", "url(#arrow-" + idx + ")");
    path.dataset.connectionIndex = idx;
    path.style.cursor = "pointer";
    path.onclick = function (ev) {
      ev.stopPropagation();
      pushUndoSnapshot();
      connections.splice(idx, 1);
      drawConnections();
    };
    svg.appendChild(path);
  });
}

function openSidebar(blockData) {
  if (!blockData || !sidebar || !sidebarContent) return;
  _sidebarBlockId = blockData.id;
  if (!selectedBlockIds.has(blockData.id)) {
    selectedBlockIds.clear();
    selectedBlockIds.add(blockData.id);
    syncBlockSelectionStyles();
  }

  var registry = typeof CanvasView !== "undefined" ? CanvasView.getRegistry() : [];
  var phantom =
    typeof CanvasView !== "undefined" &&
    CanvasView.isPhantomType &&
    CanvasView.isPhantomType(blockData.type, registry);

  if (phantom) {
    CanvasView.renderPhantomPropertiesPanel(sidebarContent, blockData, {
      escapeHtml: escapeHtml,
    });
  } else {
    var plugin = typeof CanvasView !== "undefined"
      ? CanvasView.getPluginByType(blockData.type, registry)
      : null;

    if (plugin && typeof CanvasView !== "undefined") {
      CanvasView.renderPropertiesPanel(sidebarContent, blockData, plugin, {
        escapeHtml: escapeHtml,
        scenarioTags: scenarioTags,
        blocks: blocks,
        connections: connections,
        renderBlock: renderBlock,
        onUpdate: function () {
          renderBlock(blockData);
          drawConnections();
        },
        refreshPanel: function (bd) {
          openSidebar(bd || blockData);
        },
        setupMessageMediaEditor: setupMessageMediaEditor,
        renderInlineEditor: renderInlineEditor,
        renderMenuButtonsEditor: renderMenuButtonsEditor,
        setupFieldNameAutocomplete: setupFieldNameAutocomplete,
        addInlineButton: window.addInlineButton,
        addButton: window.addButton,
        updateBlockTagId: window.updateBlockTagId,
        updateCommandTagId: window.updateCommandTagId,
        createTagFromBlock: window.createTagFromBlock,
        editTagFromBlock: window.editTagFromBlock,
        deleteTagFromBlock: window.deleteTagFromBlock,
      });
    } else {
      sidebarContent.innerHTML = '<p class="editor-hint">' + escapeHtml(tr("editor.block_unknown", { type: blockData.type })) + "</p>";
    }
  }

  sidebar.style.display = "flex";
  sidebar.classList.add("sidebar-visible");
  sidebar.setAttribute("aria-hidden", "false");
}

function applyConnectionFromOutput(fromBlockId, outputIndex, toBlockId) {
  connections = connections.filter(function (c) {
    return !(c.from === fromBlockId && String(c.outputIndex) === String(outputIndex));
  });
  if (toBlockId) connections.push({ from: fromBlockId, outputIndex: outputIndex, to: toBlockId });
  drawConnections();
}

function setConnectionFromOutput(fromBlockId, outputIndex, toBlockId) {
  pushUndoSnapshot();
  applyConnectionFromOutput(fromBlockId, outputIndex, toBlockId);
}

function setupMessageMediaEditor(blockId) {
  const block = blocks.find(function (b) { return b.id === blockId; });
  if (!block || block.type !== "message") return;
  const typeSelect = document.getElementById("msg-media-type-" + blockId);
  const zone = document.getElementById("msg-media-zone-" + blockId);
  const fileInput = document.getElementById("msg-media-input-" + blockId);
  const filesList = document.getElementById("msg-media-files-" + blockId);
  if (!block.data.media) block.data.media = { type: null, files: [] };

  function updateMediaVisibility() {
    const t = typeSelect ? typeSelect.value : "";
    if (zone) zone.style.display = t ? "flex" : "none";
    if (fileInput) {
      if (t === "photo") fileInput.accept = "image/*";
      else if (t === "video") fileInput.accept = "video/*";
      else if (t === "audio") fileInput.accept = "audio/*";
      else if (t === "document") fileInput.accept = "*";
      else fileInput.accept = "";
      fileInput.multiple = t === "document";
    }
    block.data.media.type = t || null;
    if (t && t !== "document") {
      var max = 1;
      if (block.data.media.files && block.data.media.files.length > max) block.data.media.files = block.data.media.files.slice(0, max);
    }
    renderMediaFilesList(blockId);
    renderBlock(block);
  }

  if (typeSelect) typeSelect.onchange = updateMediaVisibility;
  updateMediaVisibility();

  function renderMediaFilesList(bid) {
    if (!filesList) return;
    const m = block.data.media;
    const fl = (m && m.files) || [];
    if (fl.length === 0) { filesList.innerHTML = ""; return; }
    filesList.innerHTML = fl.map(function (f, i) {
      return '<div class="media-file-item"><span>' + escapeHtml(f.name || f.path || tr("editor.file_fallback")) + '</span><button type="button" class="media-file-remove" onclick="removeMediaFile(\'' + bid + '\',' + i + ')" aria-label="' + escapeHtml(tr("editor.remove_file")) + '">×</button></div>';
    }).join("");
  }

  function doUpload(file) {
    if (!bot_id) { alert("Загрузка доступна при редактировании бота (укажите bot_id в URL)."); return; }
    const fd = new FormData();
    fd.append("file", file);
    var token = localStorage.getItem("access_token");
    var headers = {};
    if (token) headers["Authorization"] = "Bearer " + token;
    fetch(API_BASE + "/api/bots/upload/" + bot_id, { method: "POST", headers: headers, body: fd })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "Ошибка загрузки"); });
        return r.json();
      })
      .then(function (res) {
        if (!block.data.media.files) block.data.media.files = [];
        var maxFiles = block.data.media.type === "document" ? 10 : 1;
        if (block.data.media.files.length >= maxFiles) { alert("Максимум " + maxFiles + " файл(ов)."); return; }
        block.data.media.files.push({ path: res.path, name: file.name || res.filename });
        renderMediaFilesList(blockId);
        renderBlock(block);
      })
      .catch(function (e) { alert(e.message || "Ошибка загрузки"); });
  }

  if (fileInput) {
    fileInput.onchange = function () {
      var files = this.files;
      if (!files || !files.length) return;
      pushUndoSnapshot();
      for (var i = 0; i < files.length; i++) doUpload(files[i]);
      this.value = "";
    };
  }
  if (zone) {
    zone.onclick = function () { if (fileInput) fileInput.click(); };
    zone.ondragover = function (e) { e.preventDefault(); zone.classList.add("drag-over"); };
    zone.ondragleave = function () { zone.classList.remove("drag-over"); };
    zone.ondrop = function (e) {
      e.preventDefault();
      zone.classList.remove("drag-over");
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) {
        pushUndoSnapshot();
        for (var i = 0; i < files.length; i++) doUpload(files[i]);
      }
    };
  }
}

window.removeMediaFile = function (blockId, index) {
  const block = blocks.find(function (b) { return b.id === blockId; });
  if (!block || !block.data.media || !block.data.media.files) return;
  pushUndoSnapshot();
  block.data.media.files.splice(index, 1);
  var fl = document.getElementById("msg-media-files-" + blockId);
  if (fl) {
    const m = block.data.media;
    const files = m.files || [];
    fl.innerHTML = files.map(function (f, i) {
      return '<div class="media-file-item"><span>' + escapeHtml(f.name || f.path || tr("editor.file_fallback")) + '</span><button type="button" class="media-file-remove" onclick="removeMediaFile(\'' + blockId + '\',' + i + ')" aria-label="' + escapeHtml(tr("editor.remove_file")) + '">×</button></div>';
    }).join("");
  }
  renderBlock(block);
};

function renderInlineEditor(blockId) {
  const container = document.getElementById("msg-inline-" + blockId);
  if (!container) return;
  const block = blocks.find(function (b) { return b.id === blockId; });
  if (!block) return;
  const btns = block.data.inlineButtons || [];
  var blocksWithTag = blocks.filter(function (b) { return b.id !== blockId && b.type !== "start" && b.type !== "note" && (b.data.tag || b.data.tagId || b.data.name || b.type); });
  container.innerHTML = "";
  container.className = "inline-buttons-list btn-editor-list";
  btns.forEach(function (btn, i) {
    const item = document.createElement("div");
    item.className = "btn-editor-item";
    var connTo = (connections.find(function (c) { return c.from === blockId && String(c.outputIndex) === String(i); }) || {}).to;
    const mainRow = document.createElement("div");
    mainRow.className = "btn-editor-main-row";
    const textInput = document.createElement("input");
    textInput.type = "text";
    textInput.className = "btn-editor-text";
    textInput.placeholder = tr("editor.btn_name_ph_inline");
    textInput.value = (btn.text || "").slice(0, 20);
    textInput.maxLength = 21;
    textInput.oninput = function () { block.data.inlineButtons[i].text = this.value.slice(0, 20); renderBlock(block); };
    const tagSelect = document.createElement("select");
    tagSelect.className = "btn-editor-connection-select";
    tagSelect.title = tr("editor.btn_connection");
    tagSelect.innerHTML = '<option value="">' + escapeHtml(tr("editor.btn_connection")) + "</option>" + blocksWithTag.map(function (b) {
      var label = getBlockTagLabel(b);
      return '<option value="' + escapeHtml(b.id) + '"' + (connTo === b.id ? " selected" : "") + '>' + escapeHtml(label) + '</option>';
    }).join("");
    tagSelect.onchange = function () { setConnectionFromOutput(blockId, i, this.value || null); };
    const linkBtn = document.createElement("button");
    linkBtn.type = "button";
    linkBtn.className = "btn-editor-link-btn" + (btn.url ? " has-link" : "");
    linkBtn.title = tr("editor.btn_link_title");
    linkBtn.textContent = tr("editor.btn_url_label");
    linkBtn.onclick = function () {
      var wrap = item.querySelector(".btn-editor-url-wrap");
      wrap.classList.add("visible");
      wrap.querySelector("input").focus();
    };
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn-editor-del";
    delBtn.title = tr("common.delete");
    delBtn.setAttribute("aria-label", tr("common.delete"));
    delBtn.textContent = "×";
    delBtn.onclick = function (ev) {
      ev.stopPropagation();
      pushUndoSnapshot();
      applyConnectionFromOutput(blockId, i, null);
      block.data.inlineButtons.splice(i, 1);
      connections.forEach(function (c) {
        if (c.from !== blockId) return;
        var out = parseInt(c.outputIndex, 10);
        if (out > i) c.outputIndex = out - 1;
      });
      block.data.inlineButtonRowBreaks = fixRowBreaksAfterRemove(block.data.inlineButtonRowBreaks, i);
      renderBlock(block);
      openSidebar(block);
      drawConnections();
    };
    mainRow.appendChild(textInput);
    mainRow.appendChild(tagSelect);
    mainRow.appendChild(linkBtn);
    mainRow.appendChild(delBtn);
    const urlWrap = document.createElement("div");
    urlWrap.className = "btn-editor-url-wrap" + (btn.url ? " visible" : "");
    const urlRow = document.createElement("div");
    urlRow.className = "btn-editor-url-row";
    const urlInput = document.createElement("input");
    urlInput.type = "url";
    urlInput.placeholder = "https://…";
    urlInput.value = btn.url || "";
    urlInput.oninput = function () {
      block.data.inlineButtons[i].url = this.value;
      if (this.value) { linkBtn.classList.add("has-link"); urlWrap.classList.add("visible"); } else { linkBtn.classList.remove("has-link"); }
    };
    const removeLinkBtn = document.createElement("button");
    removeLinkBtn.type = "button";
    removeLinkBtn.className = "btn-editor-remove-link";
    removeLinkBtn.title = tr("editor.btn_remove_link");
    removeLinkBtn.setAttribute("aria-label", tr("editor.btn_remove_link"));
    removeLinkBtn.textContent = "×";
    removeLinkBtn.onclick = function () {
      block.data.inlineButtons[i].url = "";
      urlInput.value = "";
      linkBtn.classList.remove("has-link");
      urlWrap.classList.remove("visible");
    };
    urlRow.appendChild(urlInput);
    urlRow.appendChild(removeLinkBtn);
    urlWrap.appendChild(urlRow);
    item.appendChild(mainRow);
    item.appendChild(urlWrap);
    container.appendChild(item);
  });
}

function renderMenuButtonsEditor(blockId) {
  const container = document.getElementById("menu-btns-" + blockId);
  if (!container) return;
  const block = blocks.find(function (b) { return b.id === blockId; });
  if (!block) return;
  const btns = (block.data.buttons || []).map(function (b) {
    if (typeof b === "string") return { text: b, url: "" };
    var o = { text: b.text || "", url: b.url || "" };
    if (b.request_contact) o.request_contact = true;
    if (b.request_location) o.request_location = true;
    return o;
  });
  block.data.buttons = btns;
  container.innerHTML = "";
  container.className = "btn-editor-list";
  var blocksWithTag = blocks.filter(function (b) { return b.id !== blockId && b.type !== "start" && b.type !== "note" && (b.data.tag || b.data.tagId || b.data.name || b.type); });
  btns.forEach(function (btn, i) {
    const item = document.createElement("div");
    item.className = "btn-editor-item";
    var connTo = (connections.find(function (c) { return c.from === blockId && String(c.outputIndex) === String(i); }) || {}).to;
    const mainRow = document.createElement("div");
    mainRow.className = "btn-editor-main-row";
    const textInput = document.createElement("input");
    textInput.type = "text";
    textInput.className = "btn-editor-text";
    textInput.placeholder = tr("editor.btn_name_ph_menu");
    textInput.value = (btn.text || "").slice(0, 25);
    textInput.maxLength = 26;
    textInput.oninput = function () { block.data.buttons[i].text = this.value.slice(0, 25); renderBlock(block); };
    const tagSelect = document.createElement("select");
    tagSelect.className = "btn-editor-connection-select";
    tagSelect.title = tr("editor.btn_connection");
    tagSelect.innerHTML = '<option value="">' + escapeHtml(tr("editor.btn_connection")) + "</option>" + blocksWithTag.map(function (b) {
      var label = getBlockTagLabel(b);
      return '<option value="' + escapeHtml(b.id) + '"' + (connTo === b.id ? " selected" : "") + '>' + escapeHtml(label) + '</option>';
    }).join("");
    tagSelect.onchange = function () { setConnectionFromOutput(blockId, i, this.value || null); };
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn-editor-del";
    delBtn.title = tr("common.delete");
    delBtn.setAttribute("aria-label", tr("common.delete"));
    delBtn.textContent = "×";
    delBtn.onclick = function () {
      pushUndoSnapshot();
      applyConnectionFromOutput(blockId, i, null);
      block.data.buttons.splice(i, 1);
      connections.forEach(function (c) {
        if (c.from !== blockId) return;
        var out = parseInt(c.outputIndex, 10);
        if (out > i) c.outputIndex = out - 1;
      });
      block.data.buttonRowBreaks = fixRowBreaksAfterRemove(block.data.buttonRowBreaks, i);
      renderBlock(block);
      openSidebar(block);
      drawConnections();
    };
    mainRow.appendChild(textInput);
    mainRow.appendChild(tagSelect);
    mainRow.appendChild(delBtn);
    var specRow = document.createElement("div");
    specRow.className = "btn-editor-menu-special";
    var cLab = document.createElement("label");
    cLab.className = "btn-editor-check";
    var cIn = document.createElement("input");
    cIn.type = "checkbox";
    cIn.checked = !!block.data.buttons[i].request_contact;
    cIn.onchange = function () {
      if (this.checked) block.data.buttons[i].request_location = false;
      block.data.buttons[i].request_contact = this.checked;
      renderBlock(block);
      openSidebar(block);
    };
    cLab.appendChild(cIn);
    cLab.appendChild(document.createTextNode(" " + tr("editor.btn_contact")));
    var lLab = document.createElement("label");
    lLab.className = "btn-editor-check";
    var lIn = document.createElement("input");
    lIn.type = "checkbox";
    lIn.checked = !!block.data.buttons[i].request_location;
    lIn.onchange = function () {
      if (this.checked) block.data.buttons[i].request_contact = false;
      block.data.buttons[i].request_location = this.checked;
      renderBlock(block);
      openSidebar(block);
    };
    lLab.appendChild(lIn);
    lLab.appendChild(document.createTextNode(" " + tr("editor.btn_location")));
    specRow.appendChild(cLab);
    specRow.appendChild(lLab);
    item.appendChild(mainRow);
    item.appendChild(specRow);
    container.appendChild(item);
  });
}

window.addInlineButton = function (id) {
  const block = blocks.find(function (b) { return b.id === id; });
  if (!block) return;
  if (!block.data.inlineButtons) block.data.inlineButtons = [];
  if (!Array.isArray(block.data.inlineButtonRowBreaks)) block.data.inlineButtonRowBreaks = [0];
  if (block.data.inlineButtons.length >= 40) { alert(tr("editor.inline_max_alert")); return; }
  pushUndoSnapshot();
  block.data.inlineButtonRowBreaks.push(block.data.inlineButtons.length);
  block.data.inlineButtons.push({ text: tr("editor.btn_inline_default"), url: "" });
  renderBlock(block);
  openSidebar(block);
};

window.addButton = function (id) {
  const block = blocks.find(function (b) { return b.id === id; });
  if (!block) return;
  if (!block.data.buttons) block.data.buttons = [];
  if (!Array.isArray(block.data.buttonRowBreaks)) block.data.buttonRowBreaks = [0];
  if (block.data.buttons.length >= 25) { alert(tr("editor.menu_max_alert")); return; }
  pushUndoSnapshot();
  block.data.buttonRowBreaks.push(block.data.buttons.length);
  block.data.buttons.push({ text: tr("editor.btn_new"), url: "" });
  renderBlock(block);
  openSidebar(block);
  drawConnections();
};

window.updateBlockTagId = function (id, val) {
  const b = blocks.find(function (x) { return x.id === id; });
  if (b) { b.data.tagId = val || ""; b.data.tag = val || ""; renderBlock(b); drawConnections(); }
};

window.updateMessageTagId = function (id, val) { updateBlockTagId(id, val); };

window.updateMessageHidePreview = function (id, checked) {
  const b = blocks.find(function (x) { return x.id === id; });
  if (b) { b.data.disableWebPagePreview = !!checked; renderBlock(b); }
};

window.updateMenuTagId = function (id, val) {
  const b = blocks.find(function (x) { return x.id === id; });
  if (b) { b.data.tagId = val || ""; b.data.tag = val || ""; renderBlock(b); drawConnections(); }
};

window.updateCommandTagId = function (id, val) {
  const b = blocks.find(function (x) { return x.id === id; });
  if (!b) return;
  b.data.tagId = val || "";
  var toBlockId = null;
  if (val) {
    var target = blocks.find(function (x) { return x.id !== id && (x.data.tagId === val || x.data.tag === val); });
    if (target) toBlockId = target.id;
  }
  setConnectionFromOutput(id, 0, toBlockId);
  renderBlock(b);
  drawConnections();
};

window.updateMenuHidePreview = function (id, checked) {
  const b = blocks.find(function (x) { return x.id === id; });
  if (b) { b.data.disableWebPagePreview = !!checked; renderBlock(b); }
};

window.createTagFromBlock = function (blockId) {
  var name = prompt("Имя тэга:");
  if (!name || !name.trim()) return;
  pushUndoSnapshot();
  var tagId = "tag_" + Date.now();
  scenarioTags.push({ id: tagId, name: name.trim() });
  var b = blocks.find(function (x) { return x.id === blockId; });
  if (b) { b.data.tagId = tagId; b.data.tag = tagId; renderBlock(b); }
  openSidebar(b);
};

window.editTagFromBlock = function (blockId) {
  var b = blocks.find(function (x) { return x.id === blockId; });
  var tagId = (b && (b.data.tagId || b.data.tag)) || "";
  var tag = scenarioTags.find(function (t) { return t.id === tagId; });
  if (!tag) { alert("Выберите тэг."); return; }
  var name = prompt("Новое имя тэга:", tag.name);
  if (name != null && name.trim()) {
    pushUndoSnapshot();
    tag.name = name.trim();
    renderBlock(b);
    openSidebar(b);
  }
};

window.deleteTagFromBlock = function (blockId) {
  var b = blocks.find(function (x) { return x.id === blockId; });
  var tagId = (b && (b.data.tagId || b.data.tag)) || "";
  var tag = scenarioTags.find(function (t) { return t.id === tagId; });
  if (!tag) { alert(tr("editor.select_tag")); return; }
  if (!confirm(tr("editor.delete_tag_confirm", { name: tag.name }))) return;
  pushUndoSnapshot();
  scenarioTags = scenarioTags.filter(function (t) { return t.id !== tag.id; });
  blocks.forEach(function (bl) {
    if (bl.data.tagId === tag.id || bl.data.tag === tag.id) { bl.data.tagId = ""; bl.data.tag = ""; renderBlock(bl); }
  });
  openSidebar(b);
};

window.createTagFromMenu = function (blockId) { createTagFromBlock(blockId); };
window.editTagFromMenu = function (blockId) { editTagFromBlock(blockId); };
window.deleteTagFromMenu = function (blockId) { deleteTagFromBlock(blockId); }

function getScenarioFieldsFromBlocks() {
  var fields = {};
  var system = ["tg_user_id", "tg_user_name", "tg_user_date"];
  system.forEach(function (f) { fields[f] = 1; });
  blocks.forEach(function (b) {
    if (b.type === "data" && b.data.fieldName) fields[b.data.fieldName] = (fields[b.data.fieldName] || 0) + 1;
    if (b.type === "condition" && b.data.fieldName) fields[b.data.fieldName] = (fields[b.data.fieldName] || 0) + 1;
  });
  return Object.keys(fields);
}

function getScenarioFieldsWithTypes() {
  var types = {};
  var system = { tg_user_id: "число", tg_user_name: "строка", tg_user_date: "строка" };
  Object.keys(system).forEach(function (f) { types[f] = system[f]; });
  blocks.forEach(function (b) {
    if (b.type === "data" && b.data.fieldName) {
      types[b.data.fieldName] = b.data.fieldType === "number" ? "число" : "строка";
    }
    if (b.type === "condition" && b.data.fieldName && !types[b.data.fieldName]) {
      types[b.data.fieldName] = "строка";
    }
  });
  return types;
}

var _cachedBotFields = [];
var _cachedBotFieldsTime = 0;

function fetchBotFieldsForAutocomplete(callback) {
  if (!bot_id) { callback([]); return; }
  var now = Date.now();
  if (_cachedBotFields.length && (now - _cachedBotFieldsTime) < 60000) {
    callback(_cachedBotFields);
    return;
  }
  var token = localStorage.getItem("access_token");
  var headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  fetch(API_BASE + "/api/analytics/" + bot_id + "/user-data-schema", { headers: headers })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      _cachedBotFields = (data.fields || []);
      _cachedBotFieldsTime = now;
      callback(_cachedBotFields);
    })
    .catch(function () { callback([]); });
}

function getMatchingFields(query, allFields) {
  var q = (query || "").toLowerCase().trim();
  if (!q) return allFields.slice(0, 15);
  return allFields.filter(function (f) {
    return f.toLowerCase().indexOf(q) >= 0;
  }).slice(0, 15);
}

function setupFieldNameAutocomplete(blockId, inputPrefix, dropdownPrefix, fieldKey) {
  inputPrefix = inputPrefix || "data-field";
  dropdownPrefix = dropdownPrefix || "data-field-dropdown";
  fieldKey = fieldKey || "fieldName";
  var input = document.getElementById(inputPrefix + "-" + blockId);
  var dropdown = document.getElementById(dropdownPrefix + "-" + blockId);
  var block = blocks.find(function (b) { return b.id === blockId; });
  if (!input || !dropdown || !block) return;

  function getAllFields(cb) {
    var scenarioFields = getScenarioFieldsFromBlocks();
    fetchBotFieldsForAutocomplete(function (apiFields) {
      var seen = {};
      var combined = [];
      scenarioFields.concat(apiFields).forEach(function (f) {
        if (!seen[f]) { seen[f] = true; combined.push(f); }
      });
      cb(combined);
    });
  }

  function showDropdown(matches) {
    if (!matches || matches.length === 0) {
      dropdown.innerHTML = "";
      dropdown.classList.remove("visible");
      return;
    }
    dropdown.innerHTML = matches.map(function (f) {
      return '<div class="field-name-option" data-value="' + escapeHtml(f) + '">' + escapeHtml(f) + "</div>";
    }).join("");
    dropdown.classList.add("visible");
    dropdown.querySelectorAll(".field-name-option").forEach(function (opt) {
      opt.onclick = function () {
        block.data[fieldKey] = opt.dataset.value;
        input.value = opt.dataset.value;
        dropdown.classList.remove("visible");
        renderBlock(block);
      };
    });
  }

  var debounceTimer;
  input.oninput = function () {
    block.data[fieldKey] = this.value;
    renderBlock(block);
    clearTimeout(debounceTimer);
    var q = this.value;
    debounceTimer = setTimeout(function () {
      getAllFields(function (all) {
        var matches = getMatchingFields(q, all);
        showDropdown(matches);
      });
    }, 150);
  };
  input.onfocus = function () {
    getAllFields(function (all) {
      var matches = getMatchingFields(input.value, all);
      showDropdown(matches);
    });
  };
  input.onblur = function () {
    setTimeout(function () {
      var active = document.activeElement;
      if (active && (active === input || dropdown.contains(active))) return;
      dropdown.classList.remove("visible");
    }, 150);
  };
}

function bindFieldAutocompleteDismiss() {
  if (window._fieldAutocompleteClickBound) return;
  window._fieldAutocompleteClickBound = true;
  document.addEventListener("click", function (ev) {
    document.querySelectorAll(".field-name-dropdown.visible").forEach(function (dropdown) {
      var wrap = dropdown.closest(".field-name-autocomplete-wrap");
      if (wrap && !wrap.contains(ev.target)) dropdown.classList.remove("visible");
    });
  });
}

window.openDatabaseTool = function () {
  var modal = document.getElementById("help-modal");
  var bodyEl = document.getElementById("help-modal-body");
  var titleEl = document.getElementById("help-modal-title");
  if (!modal || !bodyEl) return;
  if (titleEl) titleEl.textContent = "База данных";

  var scenarioFields = getScenarioFieldsFromBlocks();
  var fieldTypes = getScenarioFieldsWithTypes();
  var usageByField = {};

  blocks.forEach(function (b) {
    if ((b.type === "data" || b.type === "condition") && b.data.fieldName) {
      var f = b.data.fieldName;
      if (!usageByField[f]) usageByField[f] = [];
      usageByField[f].push({ id: b.id, type: b.type });
    }
  });

  var html = "";
  html += "<h4>База данных сценария</h4>";
  html += "<p class='editor-hint'>Поля, которые используются в блоках Данные и Условие, и где именно.</p>";

  html += "<h4>Быстрое добавление поля</h4>";
  html += "<p class='editor-hint'>Создаёт новый блок Данные с выбранным полем и типом.</p>";
  html += "<div class='db-quick-add'>";
  html += "<input class='editor-field' type='text' id='db-new-field-name' placeholder='role, balance, email' autocomplete='off'/>";
  html += "<select class='editor-field' id='db-new-field-type'><option value='string'>Строка</option><option value='number'>Число</option></select>";
  html += "<button type='button' class='editor-btn' id='db-add-field-btn'>Создать блок</button>";
  html += "</div>";

  html += "<h4>Поля сценария</h4>";
  if (!scenarioFields.length) {
    html += "<p class='editor-hint'><em>Пока нет полей. Добавьте блок Данные или создайте поле выше.</em></p>";
  } else {
    html += "<table class='help-table'><tr><th>Поле</th><th>Тип</th><th>Подстановка</th><th>Где используется</th></tr>";
    scenarioFields.sort().forEach(function (f) {
      var t = fieldTypes[f] || "строка";
      var uses = usageByField[f] || [];
      var useLinks = uses.map(function (u) {
        var label = u.type === "data" ? "Данные" : "Условие";
        return "<button type='button' class='editor-btn tiny db-jump-to-block' data-block-id='" + escapeHtml(u.id) + "'>" + escapeHtml(label) + "</button>";
      }).join(" ");
      html += "<tr><td><code>" + escapeHtml(f) + "</code></td><td>" + escapeHtml(t) + "</td><td><code>{{" + escapeHtml(f) + "}}</code></td><td>" + useLinks + "</td></tr>";
    });
    html += "</table>";
  }

  html += "<h4>Поля в БД бота</h4>";
  html += "<div id='db-bot-schema'><p class='editor-hint'>Загрузка...</p></div>";

  bodyEl.innerHTML = html;
  modal.style.display = "flex";

  var addBtn = document.getElementById("db-add-field-btn");
  if (addBtn) {
    addBtn.onclick = function () {
      var nameInput = document.getElementById("db-new-field-name");
      var typeSelect = document.getElementById("db-new-field-type");
      if (!nameInput || !typeSelect) return;
      var name = (nameInput.value || "").trim();
      var type = typeSelect.value || "string";
      if (!name) {
        nameInput.focus();
        return;
      }
      pushUndoSnapshot();
      var x = panX + 100;
      var y = panY + 100;
      createBlock("data", x, y, {
        action: "set",
        fieldType: type,
        fieldName: name,
        valueSource: "const",
        fieldValue: ""
      });
      closeHelpModal();
    };
  }

  bodyEl.querySelectorAll(".db-jump-to-block").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.dataset.blockId;
      if (!id) return;
      var block = blocks.find(function (b) { return b.id === id; });
      if (!block) return;
      closeHelpModal();
      openSidebar(block);
      if (block.el) {
        block.el.classList.add("block-highlight");
        setTimeout(function () {
          block.el.classList.remove("block-highlight");
        }, 1200);
      }
    });
  });

  var schemaEl = document.getElementById("db-bot-schema");
  if (schemaEl) {
    if (!bot_id) {
      schemaEl.innerHTML = "<p class='help-hint'>Откройте редактор с bot_id в URL, чтобы увидеть данные бота.</p>";
    } else {
      var token = localStorage.getItem("access_token");
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      fetch(API_BASE + "/api/analytics/" + bot_id + "/user-data-schema", { headers: headers })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var fl = data.fields || [];
          if (!fl.length) {
            schemaEl.innerHTML = "<p><em>Нет записанных полей</em></p>";
            return;
          }
          var html2 = "<table class='help-table'><tr><th>Поле</th><th>Тип</th><th>Примеры значений</th></tr>";
          fl.forEach(function (f) {
            var ft = (data.fieldTypes && data.fieldTypes[f]) || "строка";
            var samples = (data.sample && data.sample[f]) || [];
            html2 += "<tr><td><code>" + escapeHtml(f) + "</code></td><td>" + escapeHtml(ft) + "</td><td>" + escapeHtml(samples.slice(0, 5).join(", ") || "—") + "</td></tr>";
          });
          html2 += "</table>";
          schemaEl.innerHTML = html2;
        })
        .catch(function () {
          schemaEl.innerHTML = "<p class='help-error'>Ошибка загрузки данных бота.</p>";
        });
    }
  }
};

window.openHelpModal = function () {
  var modal = document.getElementById("help-modal");
  var body = document.getElementById("help-modal-body");
  if (!modal || !body) return;
  modal.style.display = "flex";
  var scenarioFields = getScenarioFieldsFromBlocks();
  var fieldTypes = getScenarioFieldsWithTypes();
  var html = "<h4>Поля из сценария</h4><p>Блоки Данные и Условие используют:</p><table class='help-table'><tr><th>Поле</th><th>Тип</th><th>Подстановка</th></tr>";
  if (scenarioFields.length === 0) {
    html += "<tr><td colspan='3'><em>Нет полей в сценарии</em></td></tr>";
  } else {
    scenarioFields.forEach(function (f) {
      var t = fieldTypes[f] || "строка";
      html += "<tr><td><code>" + escapeHtml(f) + "</code></td><td>" + escapeHtml(t) + "</td><td><code>{{" + escapeHtml(f) + "}}</code></td></tr>";
    });
  }
  html += "</table>";
  if (!bot_id) {
    html += "<p class='help-hint'>Откройте редактор с bot_id в URL, чтобы увидеть записанные данные бота.</p>";
    body.innerHTML = html;
    return;
  }
  var token = localStorage.getItem("access_token");
  var headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  fetch(API_BASE + "/api/analytics/" + bot_id + "/user-data-schema", { headers: headers })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      html += "<h4>Записанные данные бота</h4>";
      var fl = data.fields || [];
      if (fl.length === 0) {
        html += "<p><em>Нет записанных полей</em></p>";
      } else {
        html += "<p>Поля в БД бота: " + fl.map(function (f) { return "<code>" + escapeHtml(f) + "</code>"; }).join(", ") + "</p>";
        html += "<table class='help-table'><tr><th>Поле</th><th>Тип</th><th>Примеры значений</th></tr>";
        fl.forEach(function (f) {
          var samples = (data.sample && data.sample[f]) || [];
          var ft = (data.fieldTypes && data.fieldTypes[f]) || "строка";
          html += "<tr><td><code>" + escapeHtml(f) + "</code></td><td>" + escapeHtml(ft) + "</td><td>" + escapeHtml(samples.slice(0, 5).join(", ") || "—") + "</td></tr>";
        });
        html += "</table>";
      }
      body.innerHTML = html;
    })
    .catch(function () {
      body.innerHTML = html + "<p class='help-error'>Ошибка загрузки данных бота.</p>";
    });
};

window.closeHelpModal = function () {
  var modal = document.getElementById("help-modal");
  if (modal) modal.style.display = "none";
};

function duplicateBlock(blockData) {
  pushUndoSnapshot();
  var d = JSON.parse(JSON.stringify(blockData.data));
  d.id = undefined;
  d.x = (parseFloat(blockData.el.style.left) || 0) + 20;
  d.y = (parseFloat(blockData.el.style.top) || 0) + 20;
  createBlock(blockData.type, d.x, d.y, d);
}

function deleteBlock(blockData) {
  var i = blocks.indexOf(blockData);
  if (i !== -1) {
    pushUndoSnapshot();
    selectedBlockIds.delete(blockData.id);
    syncBlockSelectionStyles();
    blocks.splice(i, 1);
    blockData.el.remove();
    connections = connections.filter(function (c) { return c.from !== blockData.id && c.to !== blockData.id; });
    drawConnections();
    closeSidebar();
  }
}

window.collectScenarioPayload = function () {
  var requiredPlugins =
    typeof CanvasView !== "undefined" && CanvasView.computeRequiredPlugins
      ? CanvasView.computeRequiredPlugins(blocks)
      : blocks.map(function (b) { return b.type; }).filter(function (t, i, a) { return a.indexOf(t) === i; }).sort();
  return {
    tags: scenarioTags,
    required_plugins: requiredPlugins,
    blocks: blocks.map(function (b) {
      return {
        id: b.id,
        type: b.type,
        x: parseInt(b.el.style.left, 10) || 0,
        y: parseInt(b.el.style.top, 10) || 0,
        data: b.data,
      };
    }),
    connections: connections,
  };
};

window.captureCanvasPreviewDataUrl = function () {
  var payload = window.collectScenarioPayload();
  if (typeof CanvasView !== "undefined" && CanvasView.captureGraphPreview) {
    return CanvasView.captureGraphPreview(payload.blocks, payload.connections, {
      width: 640,
      height: 360,
    });
  }
  var canvasEl = document.createElement("canvas");
  canvasEl.width = 640;
  canvasEl.height = 360;
  return canvasEl.toDataURL("image/png");
};

function openSaveTemplateModal() {
  if (template_id) {
    alert("Редактирование DB-шаблона: используйте кнопку «Сохранить». «Сохранить в библиотеку» доступно из сценария бота.");
    return;
  }
  if (!blocks.length) {
    alert("Добавьте блоки на холст перед экспортом шаблона.");
    return;
  }
  var modal = document.getElementById("save-template-modal");
  var nameInput = document.getElementById("save-template-name");
  if (!modal) return;
  if (nameInput && !nameInput.value.trim()) {
    nameInput.value = "Bot scenario " + (bot_id || "");
  }
  modal.style.display = "flex";
  if (nameInput) nameInput.focus();
}

function closeSaveTemplateModal() {
  var modal = document.getElementById("save-template-modal");
  if (modal) modal.style.display = "none";
  var err = document.getElementById("save-template-error");
  if (err) err.style.display = "none";
}

window.exportScenarioAsTemplate = function () {
  var nameInput = document.getElementById("save-template-name");
  var descInput = document.getElementById("save-template-desc");
  var tagsInput = document.getElementById("save-template-tags");
  var err = document.getElementById("save-template-error");
  var submitBtn = document.getElementById("save-template-submit");
  var name = nameInput ? nameInput.value.trim() : "";
  if (!name) {
    if (err) {
      err.style.display = "block";
      err.textContent = "Укажите название шаблона.";
    }
    return;
  }
  var tags = (tagsInput && tagsInput.value ? tagsInput.value : "")
    .split(",")
    .map(function (t) { return t.trim(); })
    .filter(Boolean);
  var payload = window.collectScenarioPayload();
  var preview = window.captureCanvasPreviewDataUrl();
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Сохранение…";
  }
  var headers = { "Content-Type": "application/json" };
  var token = localStorage.getItem("access_token");
  if (token) headers["Authorization"] = "Bearer " + token;
  fetch(API_BASE + "/api/templates/export", {
    method: "POST",
    headers: headers,
    body: JSON.stringify({
      name: name,
      description: descInput ? descInput.value.trim() : "",
      tags: tags,
      scenario: payload,
      preview_image_base64: preview,
      platform: "telegram",
    }),
  })
    .then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; });
    })
    .then(function (r) {
      if (!r.ok) throw new Error((r.data && r.data.detail) || "Export failed");
      closeSaveTemplateModal();
    })
    .catch(function (e) {
      if (err) {
        err.style.display = "block";
        err.textContent = e.message || "Не удалось экспортировать шаблон";
      }
    })
    .finally(function () {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Сохранить в библиотеку";
      }
    });
};

window.saveScenario = function () {
  try {
    if (!bot_id && !template_id) {
      alert("Укажите bot_id или template_id в URL. Пример: ?bot_id=1 или ?template_id=1");
      return;
    }
    var payload = window.collectScenarioPayload();
    var saveBtn = document.getElementById("save-scenario-btn");
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = SCENARIO_SAVE_LOADING_ICON;
    }
    var url, method;
    if (template_id) {
      url = API_BASE + "/api/templates/" + encodeURIComponent(template_id) + "?user_id=" + encodeURIComponent(user_id);
      method = "PUT";
    } else {
      url = API_BASE + "/api/scenario/save/" + encodeURIComponent(bot_id) + "?user_id=" + encodeURIComponent(user_id);
      method = "POST";
    }
    if (typeof console !== "undefined" && console.log) console.log("Сохранение:", url, payload);
    var headers = { "Content-Type": "application/json" };
    var token = localStorage.getItem("access_token");
    if (token) headers["Authorization"] = "Bearer " + token;
    fetch(url, {
      method: method,
      headers: headers,
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        var ct = (res.headers.get("content-type") || "").toLowerCase();
        if (ct.indexOf("application/json") !== -1) {
          return res.json().then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
        }
        return res.text().then(function (text) { return { ok: false, status: res.status, data: text }; });
      })
      .then(function (r) {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = SCENARIO_SAVE_ICON;
        }
        if (r.ok) {
          showScenarioToast(
            template_id ? "Шаблон сохранён" : "Сценарий сохранён"
          );
          if (!template_id && typeof TimelineBar !== "undefined" && TimelineBar.isActive()) {
            TimelineBar.refresh();
          }
        } else if (r.status === 422) {
          var compileMsg =
            r.data && r.data.detail
              ? r.data.detail
              : "Компиляция заблокирована: отсутствует плагин для одного или нескольких блоков.";
          alert(
            "Сценарий сохранён, но main.py не обновлён.\n\n" +
              compileMsg +
              "\n\nУстановите недостающий плагин или удалите phantom-блок."
          );
        } else if (r.status === 403) {
          alert("Нет доступа. Только владелец может сохранять.");
          if (template_id) window.location.href = "/templates/"; else window.location.href = "/bots/index.html";
        } else {
          alert("Ошибка " + r.status + ": " + (typeof r.data === "string" ? r.data.slice(0, 200) : (r.data && r.data.detail ? r.data.detail : JSON.stringify(r.data))));
        }
      })
      .catch(function (err) {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = SCENARIO_SAVE_ICON;
        }
        alert("Ошибка: " + (err && err.message ? err.message : "нет связи с сервером. Запустите backend (например uvicorn)."));
      });
  } catch (e) {
    alert("Ошибка: " + (e && e.message ? e.message : String(e)));
  }
};

window.addNode = function (type) {
  pushUndoSnapshot();
  var x = 100 + blocks.length * 40;
  var y = 100 + blocks.length * 40;
  var defaults = typeof CanvasView !== "undefined"
    ? CanvasView.applyDefaults(type, {}, CanvasView.getRegistry())
    : {};
  createBlock(type, x, y, defaults);
};

function updateTransform() {
  var t = "translate(" + panX + "px, " + panY + "px) scale(" + scale + ")";
  if (canvas) canvas.style.transform = t;
  if (svg) {
    svg.style.transform = t;
    svg.style.left = "-50000px";
    svg.style.top = "-50000px";
    svg.style.width = 200000 / scale + "px";
    svg.style.height = 200000 / scale + "px";
  }
  var gridOverlay = document.getElementById("grid-overlay");
  if (gridOverlay && canvasWrapper && canvasWrapper.classList.contains("grid-on")) {
    gridOverlay.style.setProperty("--grid-x", panX + "px");
    gridOverlay.style.setProperty("--grid-y", panY + "px");
  }
}

canvasWrapper.addEventListener("wheel", function (e) {
  e.preventDefault();
  var rect = canvasWrapper.getBoundingClientRect();
  var centerX = rect.left + rect.width / 2;
  var centerY = rect.top + rect.height / 2;
  var worldX = (centerX - rect.left + 50000 - panX) / scale;
  var worldY = (centerY - rect.top + 50000 - panY) / scale;
  var delta = e.deltaY > 0 ? -0.1 : 0.1;
  scale = Math.max(0.2, Math.min(2, scale * (1 + delta)));
  panX = centerX - rect.left + 50000 - worldX * scale;
  panY = centerY - rect.top + 50000 - worldY * scale;
  updateTransform();
  scheduleDrawConnections();
});

var panning = false;
var panStartX, panStartY;
canvasWrapper.addEventListener("mousedown", function (e) {
  if (e.button === 0 && !e.target.closest(".block")) {
    selectedBlockIds.clear();
    syncBlockSelectionStyles();
  }
  if (e.button === 1) {
    if (e.target.closest("input") || e.target.closest("textarea") || e.target.closest("select")) return;
    e.preventDefault();
    panning = true;
    panStartX = e.clientX - panX;
    panStartY = e.clientY - panY;
    canvasWrapper.style.cursor = "grabbing";
    closeSidebar();
  }
});
window.addEventListener("mousemove", function (e) {
  if (panning) {
    panX = e.clientX - panStartX;
    panY = e.clientY - panStartY;
    updateTransform();
    scheduleDrawConnections();
  }
});
window.addEventListener("mouseup", function (e) {
  if (panning) {
    canvasWrapper.style.cursor = "";
    panning = false;
  }
});

if (canvasWrapper) {
  canvasWrapper.addEventListener("click", function (e) {
    if (!e.target.closest(".block")) {
      closeSidebar();
    }
  });
  canvasWrapper.addEventListener("mouseup", function (e) {
    if (!pendingConnection) return;
    var toBlock = e.target.closest(".block");
    if (!toBlock || toBlock.dataset.id === pendingConnection.from) return;
    if (toBlock.dataset.type === "note") return;
    if (pendingConnection._moveHandler) window.removeEventListener("mousemove", pendingConnection._moveHandler);
    if (pendingConnection._upHandler) window.removeEventListener("mouseup", pendingConnection._upHandler);
    pushUndoSnapshot();
    connections = connections.filter(function (c) { return !(c.from === pendingConnection.from && c.outputIndex === pendingConnection.outputIndex); });
    connections.push({ from: pendingConnection.from, outputIndex: pendingConnection.outputIndex, to: toBlock.dataset.id });
    pendingConnection = null;
    drawConnections();
  });
}

function closeSidebar() {
  if (!sidebar) return;
  sidebar.style.display = "none";
  sidebar.classList.remove("sidebar-visible");
  sidebar.setAttribute("aria-hidden", "true");
  _sidebarBlockId = null;
}

var _sidebarUndoField = null;
if (sidebarContent) {
  sidebarContent.addEventListener("focusin", function (ev) {
    var target = ev.target;
    if (!target || !target.matches("input, textarea, select")) return;
    if (_sidebarUndoField === target) return;
    _sidebarUndoField = target;
    pushUndoSnapshot();
  });
  sidebarContent.addEventListener(
    "focusout",
    function (ev) {
      if (ev.target === _sidebarUndoField) _sidebarUndoField = null;
    },
    true
  );
}

document.addEventListener("keydown", function (ev) {
  var tag = ev.target && ev.target.tagName ? ev.target.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && (ev.key === "z" || ev.key === "Z")) {
    ev.preventDefault();
    undoLastAction();
  }
});

function showScenarioLoading(message) {
  var el = document.getElementById("scenario-loading");
  if (!el) return;
  var text = el.querySelector(".scenario-loading-text");
  if (text && message) text.textContent = message;
  el.classList.add("visible");
  el.setAttribute("aria-hidden", "false");
}

function hideScenarioLoading() {
  var el = document.getElementById("scenario-loading");
  if (!el) return;
  el.classList.remove("visible");
  el.setAttribute("aria-hidden", "true");
}

function syncHistoryModeBtn(on) {
  var btn = document.getElementById("history-mode-btn");
  if (!btn) return;
  btn.classList.toggle("is-active", !!on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
}

function bindHistoryBannerActions() {
  var restoreBtn = document.getElementById("history-ghost-restore");
  var applyBtn = document.getElementById("history-ghost-apply");
  var exitBtn = document.getElementById("history-ghost-exit");
  if (applyBtn && !applyBtn._historyBound) {
    applyBtn._historyBound = true;
    applyBtn.addEventListener("click", function (e) {
      e.preventDefault();
      applyHistoryPreview();
    });
  }
  if (restoreBtn && !restoreBtn._historyBound) {
    restoreBtn._historyBound = true;
    restoreBtn.addEventListener("click", function (e) {
      e.preventDefault();
      restoreHistoryVersion();
    });
  }
  if (exitBtn && !exitBtn._historyBound) {
    exitBtn._historyBound = true;
    exitBtn.addEventListener("click", function (e) {
      e.preventDefault();
      exitHistoryMode();
    });
  }
}

function updateHistoryGhostBanner(ts) {
  var label;
  if (ts && typeof TimelineBar !== "undefined") {
    label = tr("editor.history_viewing", {
      absolute: TimelineBar.formatAbsolute(ts),
      relative: TimelineBar.formatRelative(ts),
    });
  } else {
    label = tr("editor.history_hint_empty");
  }
  if (typeof CanvasView !== "undefined" && CanvasView.setHistoryGhostMode) {
    CanvasView.setHistoryGhostMode(true, { label: label });
  }
  var restoreBtn = document.getElementById("history-ghost-restore");
  var applyBtn = document.getElementById("history-ghost-apply");
  if (restoreBtn) {
    restoreBtn.disabled = !ts;
    restoreBtn.textContent = tr("editor.history_restore");
  }
  if (applyBtn) applyBtn.disabled = !ts;
  bindHistoryBannerActions();
}

function applyHistoryPreview() {
  if (typeof TimelineBar !== "undefined") TimelineBar.close();
  if (typeof CanvasView !== "undefined" && CanvasView.setHistoryGhostMode) {
    CanvasView.setHistoryGhostMode(false);
  }
  syncHistoryModeBtn(false);
  drawConnections();
  initCanvasView();
}

function exitHistoryMode() {
  if (typeof TimelineBar !== "undefined") TimelineBar.close();
  if (typeof CanvasView !== "undefined" && CanvasView.setHistoryGhostMode) {
    CanvasView.setHistoryGhostMode(false);
  }
  syncHistoryModeBtn(false);
  if (bot_id || template_id) loadScenario();
}

function restoreHistoryVersion() {
  if (!bot_id || typeof TimelineBar === "undefined") return;
  var ts = TimelineBar.getPreviewTimestamp();
  if (!ts) return;
  var restoreBtn = document.getElementById("history-ghost-restore");
  if (restoreBtn) {
    restoreBtn.disabled = true;
    restoreBtn.textContent = tr("editor.history_restoring");
  }
  var url =
    API_BASE +
    "/api/scenario/history/" +
    encodeURIComponent(bot_id) +
    "/" +
    encodeURIComponent(ts) +
    "/restore?user_id=" +
    encodeURIComponent(user_id);
  var headers = { "Content-Type": "application/json" };
  var token = localStorage.getItem("access_token");
  if (token) headers.Authorization = "Bearer " + token;
  fetch(url, { method: "POST", headers: headers })
    .then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    })
    .then(function (r) {
      if (restoreBtn) {
        restoreBtn.disabled = false;
        restoreBtn.textContent = tr("editor.history_restore");
      }
      if (!r.ok) {
        var msg =
          r.data && r.data.detail
            ? r.data.detail
            : tr("editor.history_restore_fail", { status: r.status });
        alert(msg);
        return;
      }
      if (r.data && r.data.scenario) {
        window.applyScenarioPayload(r.data.scenario);
      }
      var newTs = r.data && r.data.timestamp;
      syncHistoryModeBtn(true);
      if (typeof CanvasView !== "undefined" && CanvasView.setHistoryGhostMode) {
        CanvasView.setHistoryGhostMode(false);
      }
      if (typeof TimelineBar !== "undefined" && TimelineBar.isActive()) {
        return TimelineBar.refresh().then(function () {
          if (newTs) return TimelineBar.jumpToVersion(newTs);
        });
      }
      showScenarioToast(tr("editor.history_restored_toast"));
    })
    .catch(function (err) {
      if (restoreBtn) {
        restoreBtn.disabled = false;
        restoreBtn.textContent = tr("editor.history_restore");
      }
      alert(tr("editor.history_restore_error", { message: err && err.message ? err.message : String(err) }));
    });
}

function toggleHistoryMode() {
  if (!bot_id) {
    alert(tr("editor.history_bots_only"));
    return;
  }
  if (typeof TimelineBar === "undefined") {
    alert(tr("editor.history_module_missing"));
    return;
  }
  if (TimelineBar.isActive()) {
    exitHistoryMode();
    return;
  }
  TimelineBar.open(bot_id, {
    onPreview: function (payload, ts) {
      window.applyScenarioPayload(payload);
      updateHistoryGhostBanner(ts);
    },
    onEmpty: function () {
      updateHistoryGhostBanner(null);
    },
    onApply: function () {
      applyHistoryPreview();
    },
    onClose: function () {
      exitHistoryMode();
    },
  });
  syncHistoryModeBtn(true);
  updateHistoryGhostBanner(null);
  setSubLoading();
}

function setSubLoading() {
  if (typeof CanvasView !== "undefined" && CanvasView.setHistoryGhostMode) {
    CanvasView.setHistoryGhostMode(true, { label: tr("editor.history_loading_versions") });
  }
  bindHistoryBannerActions();
}

function startHistoryAutosnapshot() {
  if (!bot_id || template_id) return;
  setInterval(function () {
    if (!bot_id || template_id) return;
    if (typeof TimelineBar !== "undefined" && TimelineBar.isActive()) return;
    if (typeof window.collectScenarioPayload !== "function") return;
    var url =
      API_BASE +
      "/api/scenario/history/" +
      encodeURIComponent(bot_id) +
      "/snapshot?user_id=" +
      encodeURIComponent(user_id);
    var headers = { "Content-Type": "application/json" };
    var token = localStorage.getItem("access_token");
    if (token) headers.Authorization = "Bearer " + token;
    fetch(url, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(window.collectScenarioPayload()),
    }).catch(function () {});
  }, 180000);
}

function loadScenario() {
  showScenarioLoading("Загрузка сценария…");
  selectedBlockIds.clear();
  syncBlockSelectionStyles();
  var headers = {};

  if (template_id) {
    var url = API_BASE + "/api/templates/" + encodeURIComponent(template_id) + "?user_id=" + encodeURIComponent(user_id);
    fetch(url, { headers: headers })
      .then(function (res) {
        if (res.status === 403 || res.status === 404) {
          return res.json().then(function (body) {
            throw { status: res.status, detail: body && body.detail ? body.detail : "Нет доступа" };
          });
        }
        return res.json().then(function (data) { return data; });
      })
      .then(function (data) {
        scenarioTags = data.tags || [];
        connections = data.connections || [];
        blocks.forEach(function (b) { b.el.remove(); });
        blocks = [];
        (data.blocks || []).forEach(function (block) {
          createBlock(block.type, block.x || 0, block.y || 0, Object.assign({}, block.data, { id: block.id, x: block.x, y: block.y }));
        });
        if (!blocks.some(function (b) { return b.type === "start"; })) {
          createBlock("start", 50, 100, {});
        }
        drawConnections();
        initCanvasView();
        hideScenarioLoading();
        clearUndoStack();
      })
      .catch(function (err) {
        hideScenarioLoading();
        if (err && err.status) {
          alert(err.detail || "Нет доступа к шаблону.");
          window.location.href = "/templates/";
          return;
        }
        createBlock("start", 50, 100, {});
      });
    return;
  }

  if (!bot_id) {
    createBlock("start", 50, 100, {});
    hideScenarioLoading();
    clearUndoStack();
    return;
  }
  var loadUrl = API_BASE + "/api/scenario/load/" + encodeURIComponent(bot_id) + "?user_id=" + encodeURIComponent(user_id);
  fetch(loadUrl, { headers: headers })
    .then(function (res) {
      if (res.status === 403) {
        return res.json().then(function (body) {
          throw { status: 403, detail: body && body.detail ? body.detail : "Нет доступа" };
        });
      }
      return res.json().then(function (data) { return data; });
    })
    .then(function (data) {
      scenarioTags = data.tags || [];
      connections = data.connections || [];
      blocks.forEach(function (b) { b.el.remove(); });
      blocks = [];
      (data.blocks || []).forEach(function (block) {
        createBlock(block.type, block.x || 0, block.y || 0, Object.assign({}, block.data, { id: block.id, x: block.x, y: block.y }));
      });
      if (!blocks.some(function (b) { return b.type === "start"; })) {
        createBlock("start", 50, 100, {});
      }
      drawConnections();
      initCanvasView();
      maybeSuggestAiScenario();
      hideScenarioLoading();
      clearUndoStack();
    })
    .catch(function (err) {
      hideScenarioLoading();
      if (err && err.status === 403) {
        alert(err.detail || "Нет доступа к этому боту. Только владелец может открывать сценарий.");
        window.location.href = "/bots/index.html";
        return;
      }
      createBlock("start", 50, 100, {});
    });
}

function initScenarioEditorPlugins() {
  if (typeof CanvasView === "undefined") {
    if (bot_id || template_id) loadScenario();
    else { createBlock("start", 50, 100, {}); }
    return;
  }

  var CUSTOM_PLUGINS_LS_KEY = "scenario_show_custom_plugins";

  function isCustomPluginsVisible() {
    return localStorage.getItem(CUSTOM_PLUGINS_LS_KEY) === "1";
  }

  function setCustomPluginsVisible(on) {
    localStorage.setItem(CUSTOM_PLUGINS_LS_KEY, on ? "1" : "0");
  }

  function syncCustomToggleBtn() {
    var btn = document.getElementById("custom-plugins-toggle");
    if (!btn) return;
    var on = isCustomPluginsVisible();
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.removeAttribute("title");
    var label = btn.querySelector(".tool-label");
    if (label) label.textContent = tr("editor.plugins");
  }

  function rebuildScenarioPalette() {
    var toolbar = document.getElementById("toolbar-tools");
    if (!toolbar || typeof CanvasView.buildPalette !== "function") return;
    CanvasView.buildPalette(toolbar, CanvasView.getRegistry(), window.addNode, {
      onDatabaseTool: window.openDatabaseTool,
      preserveSelectors: ["#ai-scenario-btn", "#custom-plugins-toggle", "#history-mode-btn"],
      showCustomPlugins: isCustomPluginsVisible(),
    });
    syncCustomToggleBtn();
    if (typeof window.__resetToolbarScrollClamp === "function") {
      window.__resetToolbarScrollClamp();
    }
  }

  window.rebuildScenarioPalette = rebuildScenarioPalette;

  CanvasView.loadPlugins().then(function () {
    rebuildScenarioPalette();
    var toggle = document.getElementById("custom-plugins-toggle");
    if (toggle && !toggle._boundCustomToggle) {
      toggle._boundCustomToggle = true;
      toggle.addEventListener("click", function () {
        setCustomPluginsVisible(!isCustomPluginsVisible());
        rebuildScenarioPalette();
      });
    }
    var historyBtn = document.getElementById("history-mode-btn");
    if (historyBtn && !historyBtn._boundHistoryToggle) {
      historyBtn._boundHistoryToggle = true;
      historyBtn.addEventListener("click", function () {
        toggleHistoryMode();
      });
    }
    if (bot_id) startHistoryAutosnapshot();
    if (bot_id || template_id) loadScenario();
    else createBlock("start", 50, 100, {});
  });

  document.addEventListener("botbuilder:langchange", function () {
    if (typeof CanvasView !== "undefined" && CanvasView.refreshPluginLocales) {
      CanvasView.refreshPluginLocales();
    }
    rebuildScenarioPalette();
    blocks.forEach(function (block) {
      renderBlock(block);
    });
    drawConnections();
    if (_sidebarBlockId) {
      var activeBlock = blocks.find(function (b) {
        return b.id === _sidebarBlockId;
      });
      if (activeBlock) openSidebar(activeBlock);
    }
    if (typeof TimelineBar !== "undefined" && TimelineBar.refreshLabels) {
      TimelineBar.refreshLabels();
    }
    syncCustomToggleBtn();
  });
}

initScenarioEditorPlugins();

setTimeout(function () {
  initCanvasView();
  drawConnections();
}, 100);

(function () {
  function onSaveClick(e) {
    e.preventDefault();
    if (typeof window.saveScenario === "function") window.saveScenario();
    else alert(tr("editor.editor_not_loaded"));
  }
  var saveBtnEl = document.getElementById("save-scenario-btn");
  if (saveBtnEl) {
    saveBtnEl.addEventListener("click", onSaveClick);
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      var el = document.getElementById("save-scenario-btn");
      if (el) el.addEventListener("click", onSaveClick);
    });
  }

  var saveTemplateBtn = document.getElementById("save-template-btn");
  if (saveTemplateBtn) {
    saveTemplateBtn.addEventListener("click", function (e) {
      e.preventDefault();
      openSaveTemplateModal();
    });
  }
  var saveTemplateSubmit = document.getElementById("save-template-submit");
  if (saveTemplateSubmit) saveTemplateSubmit.addEventListener("click", window.exportScenarioAsTemplate);
  var saveTemplateCancel = document.getElementById("save-template-cancel");
  if (saveTemplateCancel) saveTemplateCancel.addEventListener("click", closeSaveTemplateModal);
  var saveTemplateClose = document.getElementById("save-template-modal-close");
  if (saveTemplateClose) saveTemplateClose.addEventListener("click", closeSaveTemplateModal);
  var saveTemplateBackdrop = document.getElementById("save-template-modal-backdrop");
  if (saveTemplateBackdrop) saveTemplateBackdrop.addEventListener("click", closeSaveTemplateModal);
  if (template_id) {
    var backLink = document.getElementById("scenario-back-link");
    if (backLink) {
      backLink.href = "/templates/";
      backLink.textContent = tr("editor.back_to_templates");
    }
  }
  var scrollEl = document.getElementById("toolbar-scroll");
  var toolsEl = document.getElementById("toolbar-tools");
  if (scrollEl && toolsEl) {
    var toolbarScrollVel = 0;
    var toolbarScrollRaf = 0;
    var toolbarScrollPos = 0;

    function toolbarScrollMax() {
      // Full tools height vs visible viewport (scroll area has no padding now)
      return Math.max(0, toolsEl.scrollHeight - scrollEl.clientHeight);
    }

    function applyToolbarScrollPos() {
      var max = toolbarScrollMax();
      if (toolbarScrollPos < 0) toolbarScrollPos = 0;
      if (toolbarScrollPos > max) toolbarScrollPos = max;
      toolsEl.style.transform = "translate3d(0, " + -toolbarScrollPos + "px, 0)";
    }

    function tickToolbarScroll() {
      toolbarScrollRaf = 0;
      if (Math.abs(toolbarScrollVel) < 0.08) {
        toolbarScrollVel = 0;
        applyToolbarScrollPos();
        return;
      }

      toolbarScrollPos += toolbarScrollVel;
      var max = toolbarScrollMax();
      if (toolbarScrollPos < 0) {
        toolbarScrollPos = 0;
        toolbarScrollVel = 0;
      } else if (toolbarScrollPos > max) {
        toolbarScrollPos = max;
        toolbarScrollVel = 0;
      }

      applyToolbarScrollPos();
      toolbarScrollVel *= 0.92;

      if (Math.abs(toolbarScrollVel) >= 0.08) {
        toolbarScrollRaf = requestAnimationFrame(tickToolbarScroll);
      } else {
        toolbarScrollVel = 0;
      }
    }

    scrollEl.addEventListener(
      "wheel",
      function (e) {
        e.preventDefault();
        var raw = e.deltaY || e.detail || 0;
        if (e.deltaMode === 1) raw *= 18;
        else if (e.deltaMode === 2) raw *= scrollEl.clientHeight * 0.35;

        toolbarScrollVel += raw * 0.28;
        toolbarScrollVel = Math.max(-48, Math.min(48, toolbarScrollVel));

        if (!toolbarScrollRaf) {
          toolbarScrollRaf = requestAnimationFrame(tickToolbarScroll);
        }
      },
      { passive: false }
    );

    window.__resetToolbarScrollClamp = function () {
      applyToolbarScrollPos();
    };
  }

  var gridToggle = document.getElementById("grid-toggle");
  var themeToggle = document.getElementById("theme-toggle");
  var cw = document.getElementById("canvas-wrapper");
  if (gridToggle && cw) {
    var stored = localStorage.getItem("scenario_grid");
    if (stored === "1") {
      cw.classList.add("grid-on");
      gridToggle.classList.add("active");
    }
    gridToggle.addEventListener("click", function () {
      cw.classList.toggle("grid-on");
      gridToggle.classList.toggle("active", cw.classList.contains("grid-on"));
      localStorage.setItem("scenario_grid", cw.classList.contains("grid-on") ? "1" : "0");
      updateTransform();
    });
  }
  if (themeToggle && typeof AppTheme !== "undefined") {
    themeToggle.addEventListener("click", function () {
      AppTheme.toggle();
    });
    document.addEventListener("appthemechange", function () {
      themeToggle.setAttribute(
        "title",
        AppTheme.get() === "dark" ? "Светлая тема" : "Тёмная тема"
      );
    });
    themeToggle.setAttribute(
      "title",
      AppTheme.get() === "dark" ? "Светлая тема" : "Тёмная тема"
    );
  }

  function collectAiScenarioContextFromBlocks() {
    var fields = [];
    var cmds = [];
    var seenF = {};
    var seenC = {};
    blocks.forEach(function (b) {
      if (b.type === "data" && b.data && b.data.fieldName) {
        var fn = String(b.data.fieldName).trim();
        if (fn && !seenF[fn]) {
          seenF[fn] = true;
          fields.push(fn);
        }
      }
      if (b.type === "command" && b.data && b.data.command) {
        var c = String(b.data.command).trim();
        if (c && !seenC[c]) {
          seenC[c] = true;
          cmds.push(c);
        }
      }
    });
    return { known_field_names: fields, existing_commands: cmds };
  }

  (function wireAiScenarioModal() {
    var m = document.getElementById("ai-scenario-modal");
    if (!m) return;
    var bd = document.getElementById("ai-scenario-modal-backdrop");
    var cls = document.getElementById("ai-scenario-modal-close");
    var later = document.getElementById("ai-scenario-later");
    var sub = document.getElementById("ai-scenario-submit");
    var inp = document.getElementById("ai-scenario-input");
    var errEl = document.getElementById("ai-scenario-error");
    if (bd) bd.onclick = function () {
      closeAiScenarioModal();
    };
    if (cls) cls.onclick = function () {
      closeAiScenarioModal();
    };
    if (later) later.onclick = function () {
      dismissAiScenarioOffer();
    };
    if (sub) sub.onclick = function () {
      var text = (inp && inp.value || "").trim();
      if (text.length < 5) {
        if (errEl) {
          errEl.textContent = "Минимум 5 символов в описании.";
          errEl.style.display = "block";
        }
        return;
      }
      if (!bot_id) {
        alert("ИИ-сценарий доступен при редактировании бота (параметр bot_id в URL).");
        return;
      }
      sub.disabled = true;
      sub.textContent = "…";
      if (errEl) errEl.style.display = "none";
      var headers = { "Content-Type": "application/json" };
      var token = localStorage.getItem("access_token");
      if (token) headers["Authorization"] = "Bearer " + token;
      fetch(API_BASE + "/api/scenario/ai-generate/" + encodeURIComponent(bot_id), {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          description: text,
          context: collectAiScenarioContextFromBlocks(),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { res: res, data: data };
          });
        })
        .then(function (r) {
          sub.disabled = false;
          sub.textContent = "Сгенерировать";
          if (!r.res.ok) {
            if (errEl) {
              errEl.textContent = r.data && r.data.detail ? r.data.detail : "Ошибка " + r.res.status;
              errEl.style.display = "block";
            }
            return;
          }
          var briefEl = document.getElementById("ai-scenario-brief");
          if (briefEl && r.data && r.data.optimized_brief) {
            briefEl.textContent = "ТЗ: " + r.data.optimized_brief;
            briefEl.style.display = "block";
          }
          if (r.data && r.data.scenario) {
            window.applyScenarioPayload(r.data.scenario);
            dismissAiScenarioOffer();
            closeAiScenarioModal();
          }
        })
        .catch(function () {
          sub.disabled = false;
          sub.textContent = "Сгенерировать";
          if (errEl) {
            errEl.textContent = "Сеть или сервер недоступны.";
            errEl.style.display = "block";
          }
        });
    };
    var btn = document.getElementById("ai-scenario-btn");
    if (btn) {
      btn.onclick = function () {
        if (!bot_id) {
          alert("Укажите bot_id в URL для генерации сценария.");
          return;
        }
        if ((blocks.length > 1 || connections.length > 0) && !confirm("Заменить текущий сценарий результатом ИИ?")) return;
        openAiScenarioModal(false);
      };
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && m.style.display === "flex") closeAiScenarioModal();
    });
  })();
})();
