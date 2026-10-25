/**
 * AiPanel — BotCopilot frictionless tool-calling agent UI.
 * Auto-Pilot by default: tools execute immediately; Undo AI Action replaces confirmations.
 */
(function (global) {
  "use strict";

  var SESSION_KEY = "__bbAiChatHistory";
  var STORAGE_KEY = "bb_ai_chat_history";
  var AUTOPILOT_KEY = "bb_ai_autopilot";
  var SCHEMA_KEY = "__bbAiDbSchema";

  // Auto-Pilot ON by default (only off when explicitly "0")
  function loadAutoPilot() {
    try {
      var v = global.localStorage && global.localStorage.getItem(AUTOPILOT_KEY);
      if (v === "0") return false;
      return true;
    } catch (e) {
      return true;
    }
  }

  function saveAutoPilot(on) {
    try {
      if (global.localStorage) {
        global.localStorage.setItem(AUTOPILOT_KEY, on ? "1" : "0");
      }
    } catch (e) {}
  }

  function tr(key, fallback) {
    if (typeof global.t === "function") {
      var v = global.t(key);
      if (v && v !== key) return v;
    }
    return fallback || key;
  }

  function toast(msg, kind) {
    if (typeof global.showScenarioToast === "function") {
      global.showScenarioToast(msg, kind);
      return;
    }
    if (msg) alert(msg);
  }

  function headersJson() {
    if (typeof global.jsonApiHeaders === "function") return global.jsonApiHeaders();
    return { "Content-Type": "application/json" };
  }

  function fetchApi(path, options) {
    options = options || {};
    if (typeof global.apiFetch === "function") return global.apiFetch(path, options);
    var origin =
      typeof global.getApiOrigin === "function"
        ? global.getApiOrigin()
        : "http://127.0.0.1:8000";
    return fetch(path.indexOf("http") === 0 ? path : origin + path, options);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Strip emojis / hidden suggestion markers — never truncate or drop code. */
  function quietText(src) {
    return String(src == null ? "" : src)
      .replace(/<!--\s*PLUGIN_SUGGESTION:[\s\S]*?-->/g, "")
      .replace(
        /([\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]|[\uFE00-\uFE0F])/g,
        ""
      )
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  var FOLD_CHEVRON_SVG =
    '<svg class="ai-fold-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>';

  /** Split long/code-heavy replies into summary + collapsible details (no truncation). */
  function splitAssistantContent(raw) {
    var text = String(raw == null ? "" : raw);
    var hasCode = /```/.test(text);
    var plain = quietText(text);
    var paraBreak = text.search(/\n\s*\n/);
    var codeBreak = text.search(/```/);
    var needsFold =
      hasCode ||
      plain.length > 280 ||
      (plain.match(/\n/g) || []).length > 4;

    if (!needsFold) {
      return { summary: text, details: "", foldTitle: "" };
    }

    var cut = -1;
    if (paraBreak > 40 && paraBreak < 500) cut = paraBreak;
    else if (codeBreak > 20) cut = codeBreak;
    else {
      // First sentence or first line as summary — keep full remainder in fold
      var m = plain.match(/^(.{20,220}?[.!?…])(\s|$)/);
      if (m) {
        var idx = text.indexOf(m[1]);
        if (idx >= 0) cut = idx + m[1].length;
      }
      if (cut < 0) {
        var nl = text.indexOf("\n");
        if (nl > 20 && nl < 400) cut = nl;
      }
    }

    if (cut < 0 || cut >= text.length - 8) {
      // Entire body goes into fold; short label outside
      return {
        summary: "",
        details: text,
        foldTitle: tr("ai.fold_details", "Детали изменений"),
      };
    }

    return {
      summary: text.slice(0, cut).trim(),
      details: text.slice(cut).trim(),
      foldTitle: hasCode
        ? tr("ai.fold_code", "Код и детали")
        : tr("ai.fold_details", "Детали изменений"),
    };
  }

  function bindFoldBlocks(root) {
    if (!root) return;
    root.querySelectorAll(".ai-fold-header").forEach(function (btn) {
      if (btn._foldBound) return;
      btn._foldBound = true;
      btn.addEventListener("click", function () {
        var block = btn.closest(".ai-fold-block");
        if (!block) return;
        var open = block.classList.toggle("is-open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
  }

  function buildFoldHtml(title, bodyHtml) {
    return (
      '<div class="ai-fold-block">' +
      '<button type="button" class="ai-fold-header" aria-expanded="false">' +
      '<span class="ai-fold-title">' +
      escapeHtml(title || tr("ai.fold_details", "Детали изменений")) +
      "</span>" +
      FOLD_CHEVRON_SVG +
      "</button>" +
      '<div class="ai-fold-body ai-fold-content ai-details-text">' +
      bodyHtml +
      "</div>" +
      "</div>"
    );
  }

  function renderMarkdown(src) {
    // Preserve full source for fold/details — only strip emojis / hidden markers
    var text = quietText(src).replace(/\r\n/g, "\n");
    // Close an unclosed fenced block so trailing content is not lost mid-fence
    var fenceCount = (text.match(/```/g) || []).length;
    if (fenceCount % 2 === 1) {
      text = text + "\n```";
    }
    var blocks = [];
    text = text.replace(/```([\w-]*)\n?([\s\S]*?)```/g, function (_, lang, code) {
      var i = blocks.length;
      blocks.push(
        '<pre class="ai-md-pre"><code class="ai-md-code">' +
          escapeHtml(code.replace(/\n$/, "")) +
          "</code></pre>"
      );
      return "\n%%BLK" + i + "%%\n";
    });

    var lines = text.split("\n");
    var html = [];
    var listType = null;
    var para = [];

    function flushPara() {
      if (!para.length) return;
      html.push("<p>" + inlineMd(para.join("\n")) + "</p>");
      para = [];
    }
    function flushList() {
      if (!listType) return;
      html.push(listType === "ol" ? "</ol>" : "</ul>");
      listType = null;
    }
    function inlineMd(s) {
      var t = escapeHtml(s);
      t = t.replace(/`([^`]+)`/g, '<code class="ai-md-inline">$1</code>');
      t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      t = t.replace(/(^|[^*\w])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
      t = t.replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
      );
      return t.replace(/\n/g, "<br>");
    }

    for (var li = 0; li < lines.length; li++) {
      var line = lines[li];
      var blk = line.match(/^%%BLK(\d+)%%$/);
      if (blk) {
        flushPara();
        flushList();
        html.push(blocks[Number(blk[1])] || "");
        continue;
      }
      if (/^\s*$/.test(line)) {
        flushPara();
        flushList();
        continue;
      }
      var quote = line.match(/^>\s?(.*)$/);
      if (quote) {
        flushPara();
        flushList();
        html.push('<blockquote class="ai-md-quote">' + inlineMd(quote[1]) + "</blockquote>");
        continue;
      }
      var ol = line.match(/^\s*\d+\.\s+(.*)$/);
      var ul = line.match(/^\s*[-*]\s+(.*)$/);
      if (ol || ul) {
        flushPara();
        var want = ol ? "ol" : "ul";
        if (listType !== want) {
          flushList();
          listType = want;
          html.push(want === "ol" ? "<ol>" : "<ul>");
        }
        html.push("<li>" + inlineMd((ol || ul)[1]) + "</li>");
        continue;
      }
      flushList();
      para.push(line);
    }
    flushPara();
    flushList();
    return html.join("") || "<p></p>";
  }

  // ---- BotBuilderDB (schema vars from update_db_schema tool) ----
  global.BotBuilderDB = global.BotBuilderDB || {
    updateSchema: function (variables) {
      var cur = {};
      try {
        cur = global[SCHEMA_KEY] && typeof global[SCHEMA_KEY] === "object" ? global[SCHEMA_KEY] : {};
      } catch (e) {}
      var next = Object.assign({}, cur);
      if (variables && typeof variables === "object") {
        Object.keys(variables).forEach(function (k) {
          next[k] = variables[k];
        });
      }
      try {
        global[SCHEMA_KEY] = next;
      } catch (e2) {}
      try {
        if (global.localStorage && currentBotId()) {
          global.localStorage.setItem(
            "bb_ai_schema_" + currentBotId(),
            JSON.stringify(next)
          );
        }
      } catch (e3) {}
      return next;
    },
    getSchema: function () {
      try {
        return Object.assign({}, global[SCHEMA_KEY] || {});
      } catch (e) {
        return {};
      }
    },
  };

  function currentBotId() {
    var id = global.bot_id;
    if (!id) {
      try {
        id = new URLSearchParams(global.location.search || "").get("bot_id") || "";
      } catch (e0) {
        id = "";
      }
    }
    id = String(id || "").trim();
    return /^\d+$/.test(id) ? id : "";
  }

  // Chat history must be per bot, otherwise requests from one bot leak into another.
  function historyStorageKey() {
    var botId = currentBotId();
    if (botId) return STORAGE_KEY + "_bot_" + botId;
    var tpl = "";
    try {
      tpl = new URLSearchParams(global.location.search || "").get("template_id") || "";
    } catch (e1) {}
    return STORAGE_KEY + (tpl ? "_tpl_" + tpl : "_scratch");
  }

  function loadSessionHistory() {
    try {
      if (global.localStorage) global.localStorage.removeItem(STORAGE_KEY);
    } catch (eLegacy) {}
    try {
      var rawLs = global.localStorage && global.localStorage.getItem(historyStorageKey());
      if (rawLs) {
        var parsed = JSON.parse(rawLs);
        if (Array.isArray(parsed)) {
          try {
            global[SESSION_KEY] = parsed.slice();
          } catch (e0) {}
          return parsed.slice();
        }
      }
    } catch (e1) {}
    try {
      var raw = global[SESSION_KEY];
      if (Array.isArray(raw)) return raw.slice();
    } catch (e2) {}
    return [];
  }

  function saveSessionHistory(history) {
    var copy = Array.isArray(history) ? history.slice() : [];
    try {
      global[SESSION_KEY] = copy;
    } catch (e0) {}
    try {
      if (global.localStorage) {
        global.localStorage.setItem(historyStorageKey(), JSON.stringify(copy));
      }
    } catch (e1) {}
  }

  function clearPersistedHistory() {
    try {
      global[SESSION_KEY] = [];
    } catch (e0) {}
    try {
      if (global.localStorage) global.localStorage.removeItem(historyStorageKey());
    } catch (e1) {}
  }

  function currentScenarioSnapshot() {
    if (global.editor && typeof global.editor.getScenarioData === "function") {
      try {
        return global.editor.getScenarioData();
      } catch (e) {}
    }
    if (typeof global.getScenarioData === "function") {
      try {
        return global.getScenarioData();
      } catch (e) {}
    }
    return { blocks: [], connections: [], tags: [] };
  }

  function pushUndo() {
    if (global.editor && typeof global.editor.pushUndoSnapshot === "function") {
      global.editor.pushUndoSnapshot();
      return true;
    }
    if (typeof global.pushUndoSnapshot === "function") {
      global.pushUndoSnapshot();
      return true;
    }
    return false;
  }

  function undoLast() {
    if (global.editor && typeof global.editor.undoLastAction === "function") {
      return !!global.editor.undoLastAction();
    }
    if (typeof global.undoLastAction === "function") {
      return !!global.undoLastAction();
    }
    return false;
  }

  function AiPanel() {
    this.sidebar = document.getElementById("ai-sidebar");
    this.messagesEl = document.getElementById("ai-messages");
    this.inputEl = document.getElementById("ai-input");
    this.sendBtn = document.getElementById("ai-send-btn");
    this.genBtn = document.getElementById("ai-generate-btn"); // optional / removed from UI
    this.closeBtn = document.getElementById("ai-close-btn");
    this.clearBtn = document.getElementById("ai-clear-btn");
    this.autopilotBtn = document.getElementById("ai-autopilot-toggle");
    this.statusDot = document.getElementById("ai-status-dot");
    this.history = loadSessionHistory();
    this.busy = false;
    this.enabled = false;
    this.autoPilotEnabled = loadAutoPilot();
    this._historyLoaded = false;
    this._typingEl = null;

    if (!this.sidebar) return;

    var self = this;
    this._sendIconHtml = this.sendBtn ? this.sendBtn.innerHTML : "";
    if (this.sendBtn) {
      this.sendBtn.onclick = function () {
        if (self.busy) self.stop();
        else self.send();
      };
    }
    if (this.genBtn) this.genBtn.onclick = function () { self.runScenarioOp("replace"); };
    if (this.closeBtn) this.closeBtn.onclick = function () { self.toggle(false); };
    if (this.clearBtn) this.clearBtn.onclick = function () { self.clearChat(); };
    if (this.autopilotBtn) {
      this.autopilotBtn.onclick = function () {
        self.setAutoPilot(!self.autoPilotEnabled);
      };
      this._syncAutoPilotUi();
    }
    if (this.inputEl) {
      this.inputEl.onkeydown = function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          self.send();
        }
      };
      this.inputEl.addEventListener("input", function () {
        self._autosizeInput();
      });
      this._autosizeInput();
    }
    this._renderAll();
    this.refreshStatus();
    this.loadBackendHistory();
    this._consumePendingFixRequest();
    this._bindCanvasAutoClose();
    this._bindVisibilityResume();
    this._syncOpenButtons();
  }

  AiPanel.prototype._syncOpenButtons = function () {
    var open = this.isOpen();
    ["ws-ai-btn", "ai-scenario-btn"].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.classList.toggle("is-active", open);
    });
  };

  AiPanel.prototype._bindVisibilityResume = function () {
    if (this._visibilityBound) return;
    this._visibilityBound = true;
    var self = this;
    function resume() {
      if (!self.busy || !self._requestId) return;
      self._progressInFlight = false;
      if (!self._typingEl) self.showTyping();
      self._pollProgress();
    }
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") resume();
    });
    global.addEventListener("focus", resume);
  };

  AiPanel.prototype.close = function () {
    if (!this.sidebar) return;
    this.sidebar.classList.add("hidden");
    this.sidebar.setAttribute("aria-hidden", "true");
    this._syncOpenButtons();
  };

  AiPanel.prototype.isOpen = function () {
    return !!(this.sidebar && !this.sidebar.classList.contains("hidden"));
  };

  AiPanel.prototype._bindCanvasAutoClose = function () {
    if (this._canvasCloseBound) return;
    this._canvasCloseBound = true;
    var self = this;
    var CLICK_SLOP_PX = 5;
    var press = null;

    function eventTarget(ev) {
      return (ev && (ev.target || ev.srcElement)) || null;
    }

    function isInsideAiPanel(node) {
      if (!node) return false;
      if (self.sidebar && self.sidebar.contains(node)) return true;
      if (node.closest) {
        if (
          node.closest("#ai-sidebar") ||
          node.closest(".ai-sidebar") ||
          node.closest("#ai-assistant-drawer") ||
          node.closest("#ai-scenario-btn") ||
          node.closest("#ws-ai-btn") ||
          node.closest("#ws-header")
        ) {
          return true;
        }
      }
      return false;
    }

    function isOnCanvas(node) {
      if (!node || !node.closest) return false;
      return !!(node.closest("#canvas-wrapper") || node.closest("#canvas"));
    }

    // Wheel / zoom / scroll must never close the panel — do not listen to wheel/mousewheel.

    document.addEventListener(
      "pointerdown",
      function (e) {
        if (!self.isOpen()) {
          press = null;
          return;
        }
        // Only primary button can start a "click to close" gesture.
        // Middle/right are used for pan / context and are ignored.
        if (e.button !== 0) {
          press = null;
          return;
        }
        var t = eventTarget(e);
        if (isInsideAiPanel(t)) {
          press = null;
          return;
        }
        if (!isOnCanvas(t)) {
          press = null;
          return;
        }
        press = {
          x: e.clientX,
          y: e.clientY,
          pointerId: e.pointerId,
        };
      },
      true
    );

    document.addEventListener(
      "pointerup",
      function (e) {
        if (!press || !self.isOpen()) {
          press = null;
          return;
        }
        if (press.pointerId != null && e.pointerId != null && e.pointerId !== press.pointerId) {
          return;
        }
        var t = eventTarget(e);
        if (isInsideAiPanel(t)) {
          press = null;
          return;
        }
        var dx = Math.abs(e.clientX - press.x);
        var dy = Math.abs(e.clientY - press.y);
        var moved = dx > CLICK_SLOP_PX || dy > CLICK_SLOP_PX;
        var onCanvas = isOnCanvas(t) || isOnCanvas(document.elementFromPoint(press.x, press.y));
        press = null;
        // Drag / pan release — keep panel open
        if (moved) return;
        if (!onCanvas) return;
        self.close();
      },
      true
    );

    document.addEventListener(
      "pointercancel",
      function () {
        press = null;
      },
      true
    );
  };

  AiPanel.prototype._autosizeInput = function () {
    if (!this.inputEl) return;
    this.inputEl.style.height = "auto";
    this.inputEl.style.height = Math.min(120, Math.max(40, this.inputEl.scrollHeight)) + "px";
  };

  AiPanel.prototype._syncStatusDot = function () {
    if (!this.statusDot) return;
    this.statusDot.classList.toggle("is-off", !this.enabled);
    this.statusDot.classList.toggle("is-busy", !!this.busy);
    this.statusDot.title = this.busy
      ? "Working"
      : this.enabled
        ? "Ready"
        : "AI disabled";
  };

  AiPanel.prototype._consumePendingFixRequest = function () {
    var self = this;
    var payload = null;
    try {
      var raw = global.sessionStorage && global.sessionStorage.getItem("bb_ai_fix_request");
      if (raw) {
        payload = JSON.parse(raw);
        global.sessionStorage.removeItem("bb_ai_fix_request");
      }
    } catch (e0) {
      payload = null;
    }
    if (!payload) {
      try {
        var params = new URLSearchParams(global.location.search || "");
        if (params.get("ai_fix") === "1") {
          payload = {
            bot_id: currentBotId(),
            node_id: params.get("node_id") || "",
            message: "",
            detail: "",
          };
        }
      } catch (e1) {}
    }
    if (!payload) return;

    var nodeId = payload.node_id || "";
    var detail = (payload.detail || "").trim();
    var message = (payload.message || "").trim();
    var prompt =
      "Why did my bot fail? Please analyze this runtime error and fix the broken node/graph with patch_graph.\n" +
      (nodeId ? "failing_node_id: " + nodeId + "\n" : "") +
      (message ? "error: " + message + "\n" : "") +
      (detail ? "stack/detail:\n" + detail.slice(0, 6000) : "");

    // Open drawer then auto-send
    this.refreshStatus().then(function (ok) {
      if (!ok) {
        alert(
          tr(
            "ai.disabled_alert",
            "Enable the AI assistant in Application settings (endpoint, model, API key)."
          )
        );
        return;
      }
      self.sidebar.classList.remove("hidden");
      self.sidebar.setAttribute("aria-hidden", "false");
      self._syncOpenButtons();
      if (self.inputEl) {
        self.inputEl.value = prompt;
        self._autosizeInput();
      }
      // Defer send so history/status settle
      setTimeout(function () {
        self.send();
      }, 120);
    });
  };

  AiPanel.prototype.requestFixFromError = function (opts) {
    opts = opts || {};
    try {
      global.sessionStorage.setItem("bb_ai_fix_request", JSON.stringify(opts));
    } catch (e) {}
    this._consumePendingFixRequest();
  };

  AiPanel.prototype._syncAutoPilotUi = function () {
    if (!this.autopilotBtn) return;
    this.autopilotBtn.classList.toggle("is-active", !!this.autoPilotEnabled);
    this.autopilotBtn.setAttribute("aria-pressed", this.autoPilotEnabled ? "true" : "false");
    this.autopilotBtn.textContent = tr("ai.autopilot", "Auto-Pilot");
    var hint = document.querySelector(".ai-input-hint");
    if (hint) {
      hint.textContent = this.autoPilotEnabled
        ? "Enter to send · Shift+Enter new line · Auto-Pilot Active"
        : "Enter to send · Shift+Enter new line · Auto-Pilot Off";
    }
  };

  AiPanel.prototype.setAutoPilot = function (on) {
    this.autoPilotEnabled = !!on;
    saveAutoPilot(this.autoPilotEnabled);
    this._syncAutoPilotUi();
  };

  AiPanel.prototype.isAutoPilot = function () {
    return !!this.autoPilotEnabled;
  };

  AiPanel.prototype.scrollBottom = function () {
    if (!this.messagesEl) return;
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  };

  AiPanel.prototype.refreshStatus = function () {
    var self = this;
    return fetchApi("/api/ai/status")
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        self.enabled = !!(data && data.enabled);
        var btn = document.getElementById("ai-scenario-btn");
        if (btn) btn.classList.toggle("is-ai-off", !self.enabled);
        self._syncStatusDot();
        return self.enabled;
      })
      .catch(function () {
        self.enabled = false;
        self._syncStatusDot();
        return false;
      });
  };

  AiPanel.prototype.loadBackendHistory = function () {
    var self = this;
    var botId = currentBotId();
    if (!botId) {
      this._historyLoaded = true;
      return Promise.resolve();
    }
    return fetchApi("/api/ai/chat/" + encodeURIComponent(botId))
      .then(function (res) {
        return res.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        self._historyLoaded = true;
        var msgs = (data && data.messages) || [];
        if (!Array.isArray(msgs) || !msgs.length) return;
        self.history = msgs
          .filter(function (m) {
            return m && (m.role === "user" || m.role === "assistant") && m.content;
          })
          .map(function (m) {
            return {
              role: m.role,
              content: m.content,
              undoable: !!(m.undoable || (m.meta && m.meta.undoable)),
            };
          });
        saveSessionHistory(self.history);
        self._renderAll();
      })
      .catch(function () {
        self._historyLoaded = true;
      });
  };

  AiPanel.prototype.toggle = function (show) {
    var self = this;
    if (!this.sidebar) return;
    if (show === undefined) show = this.sidebar.classList.contains("hidden");
    if (show) {
      this.refreshStatus().then(function (ok) {
        if (!ok) {
          alert(
            tr(
              "ai.disabled_alert",
              "Enable the AI assistant in Application settings (endpoint, model, API key)."
            )
          );
          return;
        }
        self.sidebar.classList.remove("hidden");
        self.sidebar.setAttribute("aria-hidden", "false");
        self._syncOpenButtons();
        if (!self._historyLoaded) {
          self.loadBackendHistory().then(function () {
            self._renderAll();
            if (self.inputEl) self.inputEl.focus();
          });
        } else {
          self._renderAll();
          if (self.inputEl) self.inputEl.focus();
        }
      });
      return;
    }
    this.close();
  };

  AiPanel.prototype.clearChat = function () {
    var self = this;
    function doClear() {
      self.history = [];
      clearPersistedHistory();
      self._renderAll();
      var botId = currentBotId();
      if (botId) {
        fetchApi("/api/ai/chat/" + encodeURIComponent(botId), { method: "DELETE" }).catch(
          function () {}
        );
      }
    }
    if (!this.history.length) {
      doClear();
      return;
    }
    var title = tr("ai.clear_confirm_title", "Очистить историю чата?");
    var message = tr(
      "ai.clear_confirm_body",
      "Все текущие сообщения ассистента будут удалены. Это действие нельзя отменить."
    );
    var cancelLabel = tr("common.cancel", "Отмена");
    var confirmLabel = tr("ai.clear_action", "Очистить");
    if (global.AppConfirm && typeof global.AppConfirm.danger === "function") {
      global.AppConfirm.danger({
        title: title,
        message: message,
        cancelLabel: cancelLabel,
        confirmLabel: confirmLabel,
      }).then(function (ok) {
        if (ok) doClear();
      });
      return;
    }
    if (global.confirm(title + "\n\n" + message)) doClear();
  };

  var STOP_ICON_HTML =
    '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">' +
    '<rect x="5" y="5" width="14" height="14" rx="2" fill="currentColor"></rect></svg>';
  var PROGRESS_POLL_MS = 1000;

  function newRequestId() {
    return "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  AiPanel.prototype.setBusy = function (on) {
    this.busy = !!on;
    if (this.sidebar) this.sidebar.classList.toggle("ai-busy", this.busy);
    if (this.sendBtn) {
      // While busy the send button is the Stop button (only for requests that can be cancelled).
      var stoppable = this.busy && !!this._requestId;
      this.sendBtn.disabled = this.busy && !stoppable;
      this.sendBtn.classList.toggle("is-stop", stoppable);
      this.sendBtn.innerHTML = stoppable ? STOP_ICON_HTML : this._sendIconHtml;
      var label = stoppable ? tr("ai.stop", "Stop") : tr("ai.send", "Send");
      this.sendBtn.title = label;
      this.sendBtn.setAttribute("aria-label", label);
    }
    if (this.genBtn) this.genBtn.disabled = this.busy;
    this._syncStatusDot();
    if (on) this.showTyping();
    else this.hideTyping();
  };

  AiPanel.prototype.showTyping = function () {
    this.hideTyping();
    if (!this.messagesEl) return;
    var el = document.createElement("div");
    el.className = "ai-typing";
    el.innerHTML =
      '<div class="ai-typing-row">' +
      '<span class="ai-typing-dot"></span><span class="ai-typing-dot"></span><span class="ai-typing-dot"></span>' +
      '<span class="ai-progress-current"></span>' +
      "</div>" +
      '<ol class="ai-progress-steps"></ol>';
    this.messagesEl.appendChild(el);
    this._typingEl = el;
    this._progressCurrentEl = el.querySelector(".ai-progress-current");
    this._progressListEl = el.querySelector(".ai-progress-steps");
    (this._progressSteps || []).forEach(this._renderProgressStep, this);
    this.scrollBottom();
  };

  AiPanel.prototype.hideTyping = function () {
    if (this._typingEl && this._typingEl.parentNode) this._typingEl.parentNode.removeChild(this._typingEl);
    this._typingEl = null;
    this._progressCurrentEl = null;
    this._progressListEl = null;
  };

  AiPanel.prototype._renderProgressStep = function (ev) {
    if (!this._progressListEl) return;
    var li = document.createElement("li");
    li.className = "ai-progress-step is-" + String(ev.kind || "step").replace(/[^a-z_]/g, "");
    li.innerHTML =
      '<span class="ai-progress-time">' + escapeHtml(formatElapsed(ev.t)) + "</span>" +
      '<span class="ai-progress-text">' + escapeHtml(ev.text || "") + "</span>";
    this._progressListEl.appendChild(li);
  };

  function formatElapsed(t) {
    var s = Math.max(0, Math.round(Number(t) || 0));
    var m = Math.floor(s / 60);
    return (m ? m + ":" + String(s % 60).padStart(2, "0") : s + "s");
  }

  AiPanel.prototype._onProgressEvent = function (ev) {
    if (!ev || ev.seq <= this._progressSeq) return;
    this._progressSeq = ev.seq;
    if (this._progressCurrentEl) this._progressCurrentEl.textContent = ev.text || "";
    if (ev.kind === "think") return;
    this._progressSteps.push(ev);
    this._renderProgressStep(ev);
    this.scrollBottom();
  };

  AiPanel.prototype._pollProgress = function () {
    var self = this;
    var id = this._requestId;
    var now = Date.now();
    if (!id) return Promise.resolve();
    if (this._progressInFlight && now - (this._progressStartedAt || 0) < 8000) {
      return Promise.resolve();
    }
    this._progressInFlight = true;
    this._progressStartedAt = now;
    return fetchApi("/api/ai/progress/" + encodeURIComponent(id) + "?after=" + this._progressSeq)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (id !== self._requestId) return;
        ((data && data.events) || []).forEach(self._onProgressEvent, self);
      })
      .catch(function () {})
      .then(function () {
        self._progressInFlight = false;
        self._progressStartedAt = 0;
      });
  };

  AiPanel.prototype._startProgress = function (requestId) {
    var self = this;
    this._stopProgressTimer();
    this._requestId = requestId;
    this._progressSeq = -1;
    this._progressSteps = [];
    this._progressTimer = setInterval(function () { self._pollProgress(); }, PROGRESS_POLL_MS);
  };

  AiPanel.prototype._stopProgressTimer = function () {
    if (this._progressTimer) clearInterval(this._progressTimer);
    this._progressTimer = null;
  };

  /** Fetch the last events, stop polling and return the collected step log. */
  AiPanel.prototype._finishProgress = function () {
    var self = this;
    this._stopProgressTimer();
    this._progressInFlight = false;
    return this._pollProgress().then(function () {
      var steps = (self._progressSteps || []).slice();
      self._requestId = null;
      return steps;
    });
  };

  AiPanel.prototype._appendProgressLog = function (steps) {
    if (!this.messagesEl || !steps || !steps.length) return;
    var box = document.createElement("details");
    box.className = "ai-progress-log";
    var html =
      "<summary>" +
      escapeHtml(tr("ai.progress_log", "Work log ({n} steps)").replace("{n}", String(steps.length))) +
      '</summary><ol class="ai-progress-steps">';
    steps.forEach(function (ev) {
      html +=
        '<li class="ai-progress-step is-' + String(ev.kind || "step").replace(/[^a-z_]/g, "") + '">' +
        '<span class="ai-progress-time">' + escapeHtml(formatElapsed(ev.t)) + "</span>" +
        '<span class="ai-progress-text">' + escapeHtml(ev.text || "") + "</span></li>";
    });
    box.innerHTML = html + "</ol>";
    this.messagesEl.appendChild(box);
    this.scrollBottom();
  };

  AiPanel.prototype.stop = function () {
    var id = this._requestId;
    if (!id) return;
    if (this._progressCurrentEl) this._progressCurrentEl.textContent = tr("ai.stopping", "Stopping...");
    if (this.sendBtn) this.sendBtn.disabled = true;
    fetchApi("/api/ai/cancel/" + encodeURIComponent(id), { method: "POST" }).catch(function () {});
  };

  AiPanel.prototype._renderEmpty = function () {
    if (!this.messagesEl) return;
    this.messagesEl.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "ai-empty";
    wrap.innerHTML =
      "<p>" +
      escapeHtml(tr("ai.empty_hint", "Опишите, какого бота вы хотите создать…")) +
      "</p>" +
      '<div class="ai-suggestions">' +
      '<button type="button" class="ai-suggestion" data-s="poll">' +
      escapeHtml(tr("ai.suggest_poll", "Создать бота-опросник")) +
      "</button>" +
      '<button type="button" class="ai-suggestion" data-s="faq">' +
      escapeHtml(tr("ai.suggest_faq", "Создать FAQ-бота")) +
      "</button>" +
      '<button type="button" class="ai-suggestion" data-s="booking">' +
      escapeHtml(tr("ai.suggest_booking", "Создать бота записи")) +
      "</button>" +
      "</div>";
    var self = this;
    wrap.querySelectorAll(".ai-suggestion").forEach(function (btn) {
      btn.onclick = function () {
        var map = {
          poll: tr("ai.suggest_poll", "Создать бота-опросник"),
          faq: tr("ai.suggest_faq", "Создать FAQ-бота"),
          booking: tr("ai.suggest_booking", "Создать бота записи"),
        };
        if (self.inputEl) self.inputEl.value = map[btn.getAttribute("data-s")] || btn.textContent;
        self.send();
      };
    });
    this.messagesEl.appendChild(wrap);
  };

  AiPanel.prototype._renderAll = function () {
    if (!this.messagesEl) return;
    this.messagesEl.innerHTML = "";
    if (!this.history.length) {
      this._renderEmpty();
      return;
    }
    var self = this;
    this.history.forEach(function (msg) {
      if (!msg) return;
      if (msg.role === "user") {
        self.appendText("user", msg.content, true);
        return;
      }
      if (msg.role === "assistant") {
        if (msg.content) self.appendAssistantMessage(msg.content, !!msg.undoable, true);
      }
    });
    this.scrollBottom();
    if (this.busy) this.showTyping();
  };

  AiPanel.prototype.appendText = function (role, text, skipScroll) {
    if (!this.messagesEl) return;
    var empty = this.messagesEl.querySelector(".ai-empty");
    if (empty) empty.remove();
    var div = document.createElement("div");
    div.className = "ai-message " + role;
    if (role === "assistant") {
      div.innerHTML = renderMarkdown(text);
    } else {
      div.textContent = text;
    }
    this.messagesEl.appendChild(div);
    if (!skipScroll) this.scrollBottom();
    return div;
  };

  AiPanel.prototype.appendAssistantMessage = function (text, undoable, skipScroll) {
    if (!this.messagesEl) return null;
    var empty = this.messagesEl.querySelector(".ai-empty");
    if (empty) empty.remove();
    var wrap = document.createElement("div");
    wrap.className = "ai-message assistant";

    var parts = splitAssistantContent(text);
    var html = "";
    if (parts.summary) {
      html += '<div class="ai-msg-summary">' + renderMarkdown(parts.summary) + "</div>";
    }
    if (parts.details) {
      html += buildFoldHtml(parts.foldTitle, renderMarkdown(parts.details));
    }
    if (!html) {
      html = renderMarkdown(text);
    }
    wrap.innerHTML = html;
    bindFoldBlocks(wrap);

    if (undoable) {
      var bar = document.createElement("div");
      bar.className = "ai-msg-actions";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ai-undo-btn";
      btn.title = tr("ai.undo_action", "Undo AI Action");
      btn.setAttribute("aria-label", tr("ai.undo_action", "Undo AI Action"));
      btn.innerHTML =
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path></svg>' +
        "<span>" +
        escapeHtml(tr("ai.undo_short", "Undo")) +
        "</span>";
      btn.onclick = function () {
        if (undoLast()) {
          toast(tr("ai.undo_done", "AI action undone"), "ok");
          btn.disabled = true;
          btn.classList.add("is-used");
        } else {
          toast(tr("ai.undo_empty", "Nothing to undo"), "err");
        }
      };
      bar.appendChild(btn);
      wrap.appendChild(bar);
    }
    this.messagesEl.appendChild(wrap);
    if (!skipScroll) this.scrollBottom();
    return wrap;
  };

  /** Execute tool results from backend on the IDE canvas. */
  AiPanel.prototype.executeAgentResult = function (data) {
    var self = this;
    var applied = false;
    var undoPushed = false;
    var scenarioApplied = false;

    function ensureUndo() {
      if (!undoPushed) {
        pushUndo();
        undoPushed = true;
      }
    }

    function applyOnce(scenario) {
      if (!scenario || scenarioApplied) return;
      ensureUndo();
      self.applyScenarioPayload(scenario);
      scenarioApplied = true;
      applied = true;
    }

    if (data.schema_updates && typeof data.schema_updates === "object") {
      global.BotBuilderDB.updateSchema(data.schema_updates);
      applied = true;
    }

    var actions = Array.isArray(data.actions) ? data.actions : [];
    actions.forEach(function (a) {
      if (!a || !a.tool) return;
      if (a.tool === "update_db_schema" && a.variables) {
        global.BotBuilderDB.updateSchema(a.variables);
        applied = true;
      }
      if ((a.tool === "patch_graph" || a.tool === "create_complete_standalone_app") && a.scenario) {
        applyOnce(a.scenario);
      }
      if (a.tool === "create_custom_plugin" && a.plugin_created) {
        applied = true;
      }
    });

    if (data.scenario && typeof data.scenario === "object") {
      applyOnce(data.scenario);
    }

    return { applied: applied, undoable: undoPushed || !!data.undoable };
  };

  AiPanel.prototype.applyScenarioPayload = function (scenario) {
    if (!scenario || typeof scenario !== "object") return false;
    if (global.editor && typeof global.editor.patchScenario === "function") {
      // patchScenario already pushes undo — avoid double push by using load directly
      // when we already pushed
    }
    var loader =
      (global.editor && global.editor.loadScenarioData) ||
      global.loadScenarioData ||
      global.applyScenarioPayload;
    if (typeof loader !== "function") return false;
    // Flag triggers native canvas auto-layout inside applyScenarioPayload
    var payload = Object.assign({}, scenario, { _autoLayout: true });
    loader(payload);
    var align =
      (global.editor && global.editor.runCanvasAutoLayout) ||
      global.runCanvasAutoLayout;
    if (typeof align === "function") {
      global.setTimeout(function () {
        try {
          align();
        } catch (err) {
          console.warn("[AiPanel] auto-layout failed", err);
        }
      }, 60);
    }
    return true;
  };

  AiPanel.prototype.handleAgentReply = function (data) {
    var self = this;
    var reply = quietText((data && data.reply) || "") || tr("ai.autopilot_done", "Done.");

    function emitRepositoryUpdated(files) {
      var list = Array.isArray(files) ? files.filter(Boolean) : [];
      if (!list.length && Array.isArray(data && data.actions)) {
        data.actions.forEach(function (a) {
          if (!a) return;
          if (a.tool === "write_workspace_file" && a.relative_path) {
            list.push(a.relative_path);
          }
          (a.files_created || []).forEach(function (p) {
            if (p) list.push(p);
          });
          var created = a.created && typeof a.created === "object" ? a.created : null;
          if (created && Array.isArray(created.written_files)) {
            created.written_files.forEach(function (p) {
              if (p) list.push(p);
            });
          }
        });
      }
      // Deduplicate
      var uniq = [];
      list.forEach(function (p) {
        var s = String(p);
        if (uniq.indexOf(s) < 0) uniq.push(s);
      });
      if (!uniq.length) return;
      try {
        window.dispatchEvent(
          new CustomEvent("repository-updated", {
            detail: { files_created: uniq, source: "ai-copilot" },
          })
        );
      } catch (errEmit) {
        console.warn("[AiPanel] repository-updated dispatch failed", errEmit);
      }
      toast(
        tr("ai.files_saved", "Saved {n} file(s)").replace("{n}", String(uniq.length)),
        "ok"
      );
    }

    function finish(undoable) {
      self.appendAssistantMessage(reply, undoable);
      self.history.push({ role: "assistant", content: reply, undoable: !!undoable });
      saveSessionHistory(self.history);
      if (data.auto_executed || undoable) {
        toast(reply.split("\n")[0], "ok");
      }
      emitRepositoryUpdated(data && data.files_created);
    }

    function emitWorkspaceUpdated(result) {
      var actions = Array.isArray(data && data.actions) ? data.actions : [];
      var refreshCanvas = !!(data && data.refresh_canvas) || actions.some(function (a) { return a && a.refresh_canvas; });
      var refreshRepo = !!(data && data.refresh_repo) || actions.some(function (a) { return a && a.refresh_repo; });
      if (!refreshCanvas && !refreshRepo) return;
      try {
        window.dispatchEvent(
          new CustomEvent("workspace-updated", {
            detail: {
              refresh_canvas: refreshCanvas,
              refresh_repo: refreshRepo,
              canvas_applied: !!(result && result.applied),
              files_created: (data && data.files_created) || [],
              source: "ai-copilot",
            },
          })
        );
      } catch (errEmit) {
        console.warn("[AiPanel] workspace-updated dispatch failed", errEmit);
      }
    }

    var pluginReload = Promise.resolve();
    if (data.plugin_created) {
      pluginReload =
        typeof global.reloadPlugins === "function" ? global.reloadPlugins() : Promise.resolve();
    }

    Promise.resolve(pluginReload)
      .then(function () {
        var result = self.executeAgentResult(data || {});
        finish(result.undoable || !!data.undoable);
        emitWorkspaceUpdated(result);
      })
      .catch(function () {
        var result = self.executeAgentResult(data || {});
        finish(result.undoable || !!data.undoable);
        emitWorkspaceUpdated(result);
      });
  };

  AiPanel.prototype.send = function (fromHistory) {
    var self = this;
    if (this.busy) return;
    if (!fromHistory) {
      var text = ((this.inputEl && this.inputEl.value) || "").trim();
      if (!text) return;
      this.appendText("user", text);
      this.history.push({ role: "user", content: text });
      saveSessionHistory(this.history);
      if (this.inputEl) {
        this.inputEl.value = "";
        this.inputEl.style.height = "";
      }
    }
    var payloadMsgs = this.history
      .filter(function (m) {
        return m && (m.role === "user" || m.role === "assistant") && m.content;
      })
      .map(function (m) {
        return { role: m.role, content: m.content };
      })
      .slice(-40);
    if (!payloadMsgs.length) return;

    var requestId = newRequestId();
    this._startProgress(requestId);
    this.setBusy(true);
    fetchApi("/api/ai/chat", {
      method: "POST",
      headers: headersJson(),
      body: JSON.stringify({
        messages: payloadMsgs,
        bot_id: currentBotId() ? Number(currentBotId()) : null,
        current_scenario: currentScenarioSnapshot(),
        auto_pilot: true,
        request_id: requestId,
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (r) {
        return self._finishProgress().then(function (steps) {
          r.steps = steps;
          return r;
        });
      })
      .then(function (r) {
        self.setBusy(false);
        if (!r.ok) {
          var detail = (r.data && (r.data.detail || r.data.message)) || "HTTP " + r.status;
          if (Array.isArray(detail))
            detail = detail
              .map(function (x) {
                return x.msg || x;
              })
              .join("; ");
          self.appendAssistantMessage(String(detail), false);
          self._appendProgressLog(r.steps);
          toast(String(detail), "err");
          return;
        }
        self.handleAgentReply(r.data || {});
        self._appendProgressLog(r.steps);
      })
      .catch(function (err) {
        self._stopProgressTimer();
        self._requestId = null;
        self.setBusy(false);
        var msg = (err && err.message) || String(err);
        self.appendAssistantMessage(msg, false);
        toast(msg, "err");
      });
  };

  AiPanel.prototype.runScenarioOp = function (mode, hint) {
    var self = this;
    if (this.busy) return;
    mode = mode === "patch" ? "patch" : "replace";

    var historyMsgs = (this.history || [])
      .filter(function (m) {
        return m && m.content && (m.role === "user" || m.role === "assistant");
      })
      .map(function (m) {
        return { role: m.role, content: m.content };
      });

    var users = historyMsgs.filter(function (m) {
      return m.role === "user";
    });
    var instruction = hint || "";
    if (!instruction && users.length) {
      instruction = users
        .map(function (m) {
          return m.content;
        })
        .join("\n");
    }
    if (!instruction) instruction = ((this.inputEl && this.inputEl.value) || "").trim();
    if (!instruction && !historyMsgs.length) {
      alert(tr("ai.need_description", "Describe the bot first, then generate the scenario."));
      return;
    }

    this.setBusy(true);
    fetchApi("/api/ai/scenario-op", {
      method: "POST",
      headers: headersJson(),
      body: JSON.stringify({
        mode: mode,
        instruction: instruction || "Выполни операцию по истории диалога.",
        current_scenario: currentScenarioSnapshot(),
        messages: historyMsgs.slice(-40),
        auto_pilot: true,
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (r) {
        self.setBusy(false);
        if (!r.ok) {
          var detail = (r.data && r.data.detail) || "HTTP " + r.status;
          if (Array.isArray(detail))
            detail = detail
              .map(function (x) {
                return x.msg || x;
              })
              .join("; ");
          toast(String(detail), "err");
          self.appendAssistantMessage(String(detail), false);
          return;
        }
        var scenario = (r.data && r.data.scenario) || r.data;
        pushUndo();
        self.applyScenarioPayload(scenario);
        var n = (scenario.blocks && scenario.blocks.length) || 0;
        var summary =
          quietText((r.data && r.data.summary) || "") ||
          tr("ai.scenario_loaded", "Scenario generated and loaded");
        var status =
          summary +
          " (" +
          n +
          " " +
          tr("ai.blocks_count", "блоков") +
          ").";
        self.appendAssistantMessage(status, true);
        self.history.push({ role: "assistant", content: status, undoable: true });
        saveSessionHistory(self.history);
        toast(status, "ok");
      })
      .catch(function (err) {
        self.setBusy(false);
        toast((err && err.message) || String(err), "err");
      });
  };

  global.AiPanel = AiPanel;
})(typeof window !== "undefined" ? window : this);
