/**
 * RunLogsStudio — per-bot process controls, CPU/RAM metrics, live SSE logs.
 * Strict bot_id isolation for stdout/stderr/AI LLM traces.
 */
(function (global) {
  "use strict";

  var MAX_LOGS = 800;
  var SNAPSHOT_MS = 2000;

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
    var h = { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    try {
      var token =
        (global.localStorage &&
          (global.localStorage.getItem("access_token") ||
            global.localStorage.getItem("token"))) ||
        "";
      if (token) h.Authorization = "Bearer " + token;
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

  function svg(name) {
    var c =
      ' width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    if (name === "play") {
      return "<svg" + c + '><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>';
    }
    if (name === "stop") {
      return "<svg" + c + '><rect x="6" y="6" width="12" height="12" rx="1"></rect></svg>';
    }
    if (name === "restart") {
      return (
        "<svg" +
        c +
        '><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>'
      );
    }
    if (name === "copy") {
      return (
        "<svg" +
        c +
        '><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'
      );
    }
    if (name === "trash") {
      return (
        "<svg" +
        c +
        '><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>'
      );
    }
    if (name === "pause") {
      return "<svg" + c + '><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>';
    }
    return "";
  }

  function formatUptime(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + "h " + m + "m";
    if (m > 0) return m + "m " + s + "s";
    return s + "s";
  }

  function layerClass(layer) {
    var L = String(layer || "API").toUpperCase();
    if (L === "ERROR") return "rl-layer-error";
    if (L === "LLM") return "rl-layer-llm";
    if (L === "BOT") return "rl-layer-bot";
    return "rl-layer-api";
  }

  function RunLogsStudio(opts) {
    this.botId = String((opts && opts.botId) || global.bot_id || "");
    this.rootEl = null;
    this._mounted = false;
    this._paused = false;
    this._status = "stopped";
    this._pid = null;
    this._logs = [];
    this._filter = "";
    this._layer = "";
    this._streamAbort = null;
    this._snapshotTimer = null;
    this._scrollPinned = true;
    this._busy = false;
  }

  RunLogsStudio.prototype.mount = function (root) {
    var el =
      typeof root === "string"
        ? document.querySelector(root)
        : root || document.getElementById("rl-root");
    if (!el) return this;
    this.rootEl = el;
    this._mounted = true;
    el.classList.add("rl-root");
    el.innerHTML = this._shellHtml();
    this._bind();
    this.refreshSnapshot();
    this.loadHistory();
    this.connectStream();
    this._snapshotTimer = global.setInterval(
      function () {
        if (this._mounted) this.refreshSnapshot();
      }.bind(this),
      SNAPSHOT_MS
    );
    return this;
  };

  RunLogsStudio.prototype.destroy = function () {
    this._mounted = false;
    this.closeStream();
    if (this._snapshotTimer) {
      global.clearInterval(this._snapshotTimer);
      this._snapshotTimer = null;
    }
    if (this.rootEl) this.rootEl.innerHTML = "";
  };

  RunLogsStudio.prototype._shellHtml = function () {
    return (
      '<div class="rl-metrics">' +
      this._metricCard("status", tr("run.status", "Status"), "—") +
      this._metricCard("cpu", tr("run.cpu", "Bot CPU"), "0%") +
      this._metricCard("ram", tr("run.ram", "Bot RAM"), "0 MB") +
      this._metricCard("host", tr("run.host", "Host"), "—") +
      "</div>" +
      '<div class="rl-toolbar">' +
      '<div class="rl-status-block">' +
      '<span class="rl-status-dot" id="rl-status-dot" data-state="stopped"></span>' +
      '<span class="rl-status-text" id="rl-status-text">' +
      escapeHtml(tr("bots.status_stopped", "Stopped")) +
      "</span>" +
      '<span class="rl-pid" id="rl-pid"></span>' +
      "</div>" +
      '<div class="rl-actions">' +
      '<button type="button" class="rl-btn primary" id="rl-start" title="' +
      escapeHtml(tr("bots.start", "Start")) +
      '">' +
      svg("play") +
      "<span>" +
      escapeHtml(tr("bots.start", "Start")) +
      "</span></button>" +
      '<button type="button" class="rl-btn" id="rl-stop" title="' +
      escapeHtml(tr("bots.stop", "Stop")) +
      '">' +
      svg("stop") +
      "<span>" +
      escapeHtml(tr("bots.stop", "Stop")) +
      "</span></button>" +
      '<button type="button" class="rl-btn" id="rl-restart" title="' +
      escapeHtml(tr("run.restart", "Restart")) +
      '">' +
      svg("restart") +
      "<span>" +
      escapeHtml(tr("run.restart", "Restart")) +
      "</span></button>" +
      "</div></div>" +
      '<div class="rl-console">' +
      '<div class="rl-console-bar">' +
      '<span class="rl-console-title">' +
      escapeHtml(tr("run.console", "Live Console")) +
      "</span>" +
      '<div class="rl-console-filters">' +
      '<input type="search" class="rl-filter" id="rl-filter" placeholder="' +
      escapeHtml(tr("monitor.filter_placeholder", "Filter by text…")) +
      '" />' +
      '<select class="rl-layer" id="rl-layer">' +
      '<option value="">' +
      escapeHtml(tr("monitor.all_layers", "All layers")) +
      "</option>" +
      '<option value="BOT">BOT</option>' +
      '<option value="API">API</option>' +
      '<option value="LLM">LLM</option>' +
      '<option value="ERROR">ERROR</option>' +
      "</select>" +
      '<button type="button" class="rl-btn ghost" id="rl-pause">' +
      svg("pause") +
      "<span>" +
      escapeHtml(tr("monitor.pause", "Pause")) +
      "</span></button>" +
      '<button type="button" class="rl-btn ghost" id="rl-copy">' +
      svg("copy") +
      "<span>" +
      escapeHtml(tr("run.copy_logs", "Copy Logs")) +
      "</span></button>" +
      '<button type="button" class="rl-btn ghost" id="rl-clear">' +
      svg("trash") +
      "<span>" +
      escapeHtml(tr("run.clear_console", "Clear Console")) +
      "</span></button>" +
      "</div></div>" +
      '<div class="rl-terminal mon-terminal" id="rl-terminal" role="log" aria-live="polite"></div>' +
      "</div>"
    );
  };

  RunLogsStudio.prototype._metricCard = function (id, label, value) {
    return (
      '<div class="rl-metric-card" id="rl-metric-' +
      id +
      '">' +
      '<span class="rl-metric-label">' +
      escapeHtml(label) +
      "</span>" +
      '<span class="rl-metric-value" id="rl-val-' +
      id +
      '">' +
      escapeHtml(value) +
      "</span>" +
      '<div class="rl-metric-bar" id="rl-bar-' +
      id +
      '" hidden><div class="rl-metric-fill" style="width:0%"></div></div>' +
      "</div>"
    );
  };

  RunLogsStudio.prototype._bind = function () {
    var self = this;
    var start = document.getElementById("rl-start");
    var stop = document.getElementById("rl-stop");
    var restart = document.getElementById("rl-restart");
    var clearBtn = document.getElementById("rl-clear");
    var copyBtn = document.getElementById("rl-copy");
    var pauseBtn = document.getElementById("rl-pause");
    var filter = document.getElementById("rl-filter");
    var layer = document.getElementById("rl-layer");
    var term = document.getElementById("rl-terminal");

    if (start) {
      start.addEventListener("click", function () {
        self._botAction("start");
      });
    }
    if (stop) {
      stop.addEventListener("click", function () {
        self._botAction("stop");
      });
    }
    if (restart) {
      restart.addEventListener("click", function () {
        self._restart();
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        self.clearConsole();
      });
    }
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        self.copyLogs();
      });
    }
    if (pauseBtn) {
      pauseBtn.addEventListener("click", function () {
        self._paused = !self._paused;
        var span = pauseBtn.querySelector("span");
        if (span) {
          span.textContent = self._paused
            ? tr("monitor.resume", "Resume")
            : tr("monitor.pause", "Pause");
        }
        if (!self._paused) self._renderTerminal();
      });
    }
    if (filter) {
      filter.addEventListener("input", function () {
        self._filter = filter.value || "";
        self._renderTerminal();
      });
    }
    if (layer) {
      layer.addEventListener("change", function () {
        self._layer = layer.value || "";
        self._renderTerminal();
      });
    }
    if (term) {
      term.addEventListener("scroll", function () {
        self._scrollPinned = term.scrollTop < 48;
      });
    }
  };

  RunLogsStudio.prototype.setStatus = function (state, pid) {
    this._status = state || "stopped";
    this._pid = pid || null;
    var dot = document.getElementById("rl-status-dot");
    var text = document.getElementById("rl-status-text");
    var pidEl = document.getElementById("rl-pid");
    var val = document.getElementById("rl-val-status");
    if (dot) dot.setAttribute("data-state", this._status);
    var label =
      this._status === "running"
        ? tr("bots.status_running", "Running")
        : this._status === "compiling"
          ? tr("run.compiling", "Compiling")
          : tr("bots.status_stopped", "Stopped");
    if (text) text.textContent = label;
    if (val) val.textContent = label;
    if (pidEl) {
      pidEl.textContent = this._pid ? "PID " + this._pid : "";
    }
    var start = document.getElementById("rl-start");
    var stop = document.getElementById("rl-stop");
    var restart = document.getElementById("rl-restart");
    var running = this._status === "running";
    var busy = this._busy || this._status === "compiling";
    if (start) start.disabled = running || busy;
    if (stop) stop.disabled = !running && this._status !== "compiling";
    if (restart) restart.disabled = !running || busy;
  };

  RunLogsStudio.prototype.refreshSnapshot = function () {
    var self = this;
    if (!this.botId) {
      this.setStatus("stopped", null);
      return Promise.resolve();
    }
    return fetch(
      apiOrigin() +
        "/api/monitor/bot/" +
        encodeURIComponent(this.botId) +
        "/snapshot",
      { headers: authHeaders() }
    )
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        if (!self._mounted) return;
        if (self._status === "compiling") return;
        var running = !!(data && data.running);
        self.setStatus(running ? "running" : "stopped", data && data.pid);
        var cpu = document.getElementById("rl-val-cpu");
        var ram = document.getElementById("rl-val-ram");
        var host = document.getElementById("rl-val-host");
        var cpuPct = Number((data && data.cpu_percent) || 0);
        var memMb = Number((data && data.memory_mb) || 0);
        if (cpu) cpu.textContent = cpuPct.toFixed(1) + "%";
        if (ram) ram.textContent = memMb.toFixed(1) + " MB";
        self._setBar("cpu", Math.min(100, cpuPct));
        self._setBar("ram", Math.min(100, memMb / 4));
        if (host && data && data.host) {
          var h = data.host;
          host.textContent =
            "CPU " +
            Number(h.cpu_percent || 0).toFixed(0) +
            "% · RAM " +
            Number(h.memory_percent || 0).toFixed(0) +
            "%";
        }
        if (running && data.uptime_sec != null) {
          var st = document.getElementById("rl-val-status");
          if (st && self._status === "running") {
            st.textContent =
              tr("bots.status_running", "Running") +
              " · " +
              formatUptime(data.uptime_sec);
          }
        }
      })
      .catch(function () {});
  };

  RunLogsStudio.prototype._setBar = function (id, pct) {
    var wrap = document.getElementById("rl-bar-" + id);
    if (!wrap) return;
    wrap.hidden = false;
    var fill = wrap.querySelector(".rl-metric-fill");
    if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
  };

  RunLogsStudio.prototype._botAction = function (action) {
    var self = this;
    if (!this.botId || this._busy) return;
    this._busy = true;
    if (action === "start") this.setStatus("compiling", null);
    var path =
      action === "stop"
        ? "/api/bots/stop/" + encodeURIComponent(this.botId)
        : "/api/bots/start/" + encodeURIComponent(this.botId);
    fetch(apiOrigin() + path, { method: "POST", headers: authHeaders() })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        self._busy = false;
        if (!res.ok) {
          self.setStatus("stopped", null);
          self._appendLocal(
            "ERROR",
            (res.data && (res.data.detail || res.data.error)) ||
              tr("run.action_failed", "Action failed")
          );
          return;
        }
        return self.refreshSnapshot();
      })
      .catch(function (err) {
        self._busy = false;
        self.setStatus("stopped", null);
        self._appendLocal(
          "ERROR",
          (err && err.message) || tr("run.action_failed", "Action failed")
        );
      });
  };

  RunLogsStudio.prototype._restart = function () {
    var self = this;
    if (!this._pid || this._busy) return;
    this._busy = true;
    this.setStatus("compiling", this._pid);
    fetch(
      apiOrigin() +
        "/api/monitor/process/" +
        encodeURIComponent(this._pid) +
        "/action",
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({ action: "restart" }),
      }
    )
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        self._busy = false;
        if (!res.ok) {
          self._appendLocal(
            "ERROR",
            (res.data && (res.data.detail || res.data.error)) ||
              tr("run.action_failed", "Action failed")
          );
        }
        return self.refreshSnapshot();
      })
      .catch(function (err) {
        self._busy = false;
        self._appendLocal(
          "ERROR",
          (err && err.message) || tr("run.action_failed", "Action failed")
        );
        return self.refreshSnapshot();
      });
  };

  RunLogsStudio.prototype._appendLocal = function (layer, message) {
    this._ingest([
      {
        ts: new Date().toISOString(),
        layer: layer,
        bot_id: this.botId,
        message: String(message || ""),
      },
    ]);
  };

  RunLogsStudio.prototype.loadHistory = function () {
    var self = this;
    if (!this.botId) return Promise.resolve();
    return fetch(
      apiOrigin() +
        "/api/monitor/logs/history?limit=200&bot_id=" +
        encodeURIComponent(this.botId),
      { headers: authHeaders() }
    )
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        var logs = (data && data.logs) || [];
        self._logs = logs.filter(function (p) {
          return p && String(p.bot_id) === String(self.botId);
        });
        self._renderTerminal();
      })
      .catch(function () {});
  };

  RunLogsStudio.prototype.connectStream = function () {
    var self = this;
    this.closeStream();
    if (!this.botId) return;
    var controller = new AbortController();
    this._streamAbort = controller;
    var url =
      apiOrigin() +
      "/api/monitor/logs/stream?bot_id=" +
      encodeURIComponent(this.botId);
    fetch(url, { headers: authHeaders(), signal: controller.signal })
      .then(function (res) {
        if (!res.ok || !res.body) throw new Error("stream unavailable");
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";
        function readNext() {
          return reader.read().then(function (chunk) {
            if (chunk.done || !self._mounted) return;
            buf += decoder.decode(chunk.value, { stream: true });
            buf = self._consumeSse(buf, function (payload) {
              if (Array.isArray(payload)) self._ingest(payload);
              else if (payload && payload.message) self._ingest([payload]);
            });
            return readNext();
          });
        }
        return readNext();
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        if (!self._mounted) return;
        global.setTimeout(function () {
          if (self._mounted) self.connectStream();
        }, 4000);
      });
  };

  RunLogsStudio.prototype.closeStream = function () {
    if (this._streamAbort) {
      this._streamAbort.abort();
      this._streamAbort = null;
    }
  };

  RunLogsStudio.prototype._consumeSse = function (buffer, onEvent) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    parts.forEach(function (block) {
      block.split("\n").forEach(function (line) {
        if (line.indexOf("data: ") === 0) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch (e) {}
        }
      });
    });
    return rest;
  };

  RunLogsStudio.prototype._ingest = function (batch) {
    if (!batch || !batch.length) return;
    var self = this;
    var added = false;
    batch.forEach(function (p) {
      if (!p || !p.message) return;
      if (p.bot_id == null || String(p.bot_id) !== String(self.botId)) return;
      self._logs.push(p);
      added = true;
    });
    if (!added) return;
    if (self._logs.length > MAX_LOGS) {
      self._logs = self._logs.slice(-MAX_LOGS);
    }
    if (!self._paused) self._renderTerminal(true);
  };

  RunLogsStudio.prototype._filtered = function () {
    var self = this;
    var q = (this._filter || "").trim().toLowerCase();
    var layer = (this._layer || "").toUpperCase();
    return this._logs.filter(function (p) {
      if (String(p.bot_id) !== String(self.botId)) return false;
      if (layer && String(p.layer || "").toUpperCase() !== layer) return false;
      if (!q) return true;
      var hay =
        String(p.message || "") +
        " " +
        String(p.detail || "") +
        " " +
        String(p.layer || "");
      return hay.toLowerCase().indexOf(q) >= 0;
    });
  };

  function formatTs(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleTimeString("ru-RU", { hour12: false });
    } catch (e) {
      return String(iso).slice(11, 19) || String(iso);
    }
  }

  function extractNodeIdFromPacket(packet) {
    var detail = String((packet && packet.detail) || "");
    var m = detail.match(/node_id:\s*(\S+)/i);
    if (m) return m[1];
    var msg = String((packet && packet.message) || "");
    m = msg.match(/node\s+([A-Za-z0-9_\-]+)/i);
    return m ? m[1] : "";
  }

  function isFixableRuntimeError(packet) {
    if (!packet) return false;
    var layer = String(packet.layer || "").toUpperCase();
    if (layer !== "ERROR") return false;
    var hay = ((packet.message || "") + "\n" + (packet.detail || "")).toLowerCase();
    return (
      hay.indexOf("runtime error") >= 0 ||
      hay.indexOf("node_id:") >= 0 ||
      hay.indexOf("traceback") >= 0 ||
      hay.indexOf("exception") >= 0
    );
  }

  RunLogsStudio.prototype._openFixWithAi = function (packet) {
    var nodeId = extractNodeIdFromPacket(packet);
    var payload = {
      bot_id: this.botId,
      node_id: nodeId,
      message: (packet && packet.message) || "",
      detail: (packet && packet.detail) || "",
      timestamp: (packet && (packet.timestamp || packet.ts)) || "",
    };
    try {
      global.sessionStorage.setItem("bb_ai_fix_request", JSON.stringify(payload));
    } catch (e) {}
    if (global.aiPanel && typeof global.aiPanel.toggle === "function") {
      if (typeof global.aiPanel._consumePendingFixRequest === "function") {
        global.aiPanel._consumePendingFixRequest();
      }
      global.aiPanel.toggle(true);
    }
  };

  RunLogsStudio.prototype._createLogNode = function (packet) {
    var self = this;
    var layer = String((packet && packet.layer) || "API").toUpperCase();
    var hasDetail = !!(packet.detail && String(packet.detail).trim());
    var fixable = isFixableRuntimeError(packet);
    var line = document.createElement("div");
    line.className =
      "mon-log-line" +
      (layer === "ERROR" ? " mon-log-line-error" : "") +
      (hasDetail ? " mon-log-expandable" : "");
    line.dataset.layer = layer;
    line.dataset.bot = packet.bot_id || this.botId || "";

    var head = document.createElement("div");
    head.className = "mon-log-head";

    var ts = document.createElement("span");
    ts.className = "mon-log-ts";
    ts.textContent = formatTs(packet.ts || packet.timestamp);

    var badge = document.createElement("span");
    badge.className =
      "mon-log-badge " +
      (layer === "LLM"
        ? "mon-badge-llm"
        : layer === "BOT"
          ? "mon-badge-bot"
          : layer === "ERROR"
            ? "mon-badge-error"
            : "mon-badge-api");
    badge.textContent = layer === "BOT" ? "BOT #" + (packet.bot_id || this.botId) : layer;

    var msg = document.createElement("span");
    msg.className = "mon-log-msg";
    msg.textContent = packet.message || "";

    head.appendChild(ts);
    head.appendChild(badge);
    if (hasDetail) {
      var chev = document.createElement("span");
      chev.className = "mon-log-chevron";
      chev.textContent = "▸";
      head.appendChild(chev);
    }
    head.appendChild(msg);

    if (fixable) {
      var fixBtn = document.createElement("button");
      fixBtn.type = "button";
      fixBtn.className = "mon-fix-ai-btn";
      fixBtn.textContent = "Fix with AI";
      fixBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        self._openFixWithAi(packet);
      });
      head.appendChild(fixBtn);
    }

    line.appendChild(head);
    if (hasDetail) {
      var detail = document.createElement("pre");
      detail.className = "mon-log-detail";
      detail.hidden = true;
      detail.textContent = String(packet.detail);
      line.appendChild(detail);
      head.addEventListener("click", function (e) {
        if (e.target && e.target.closest && e.target.closest(".mon-fix-ai-btn")) return;
        var open = line.classList.toggle("is-open");
        detail.hidden = !open;
        var c = head.querySelector(".mon-log-chevron");
        if (c) c.textContent = open ? "▾" : "▸";
      });
    }
    return line;
  };

  RunLogsStudio.prototype._renderTerminal = function () {
    var term = document.getElementById("rl-terminal");
    if (!term) return;
    var rows = this._filtered();
    term.textContent = "";
    if (!rows.length) {
      var empty = document.createElement("div");
      empty.className = "mon-empty rl-empty";
      empty.textContent = tr("run.console_empty", "No log output for this bot yet.");
      term.appendChild(empty);
      return;
    }
    var frag = document.createDocumentFragment();
    for (var i = rows.length - 1; i >= 0; i--) {
      frag.appendChild(this._createLogNode(rows[i]));
    }
    term.appendChild(frag);
    if (this._scrollPinned) {
      term.scrollTop = 0;
    }
  };

  RunLogsStudio.prototype.clearConsole = function () {
    var self = this;
    this._logs = [];
    this._renderTerminal();
    if (!this.botId) return;
    fetch(
      apiOrigin() +
        "/api/monitor/logs?bot_id=" +
        encodeURIComponent(this.botId),
      { method: "DELETE", headers: authHeaders() }
    ).catch(function () {});
  };

  RunLogsStudio.prototype.copyLogs = function () {
    var rows = this._filtered();
    var text = rows
      .map(function (p) {
        return (
          "[" +
          String(p.ts || "") +
          "] [" +
          String(p.layer || "") +
          "] " +
          String(p.message || "") +
          (p.detail ? "\n" + String(p.detail) : "")
        );
      })
      .join("\n");
    if (!text) return;
    var done = function () {
      var btn = document.getElementById("rl-copy");
      if (!btn) return;
      var span = btn.querySelector("span");
      if (!span) return;
      var prev = span.textContent;
      span.textContent = tr("ds.copied", "Copied");
      global.setTimeout(function () {
        span.textContent = prev;
      }, 1200);
    };
    if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
      global.navigator.clipboard.writeText(text).then(done).catch(function () {
        fallbackCopy(text);
        done();
      });
    } else {
      fallbackCopy(text);
      done();
    }
  };

  function fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) {}
  }

  global.RunLogsStudio = RunLogsStudio;
})(typeof window !== "undefined" ? window : this);
