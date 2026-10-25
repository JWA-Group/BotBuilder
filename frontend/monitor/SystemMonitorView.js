/**
 * SystemMonitorView — metrics (2s cadence) + batched log stream (DocumentFragment + DOM cap).
 */
(function (global) {
  "use strict";

  var MAX_STORED_LOGS = 500;
  var MAX_VISIBLE_DOM = 500;
  var METRICS_INTERVAL_MS = 2000;
  var PROCESSES_INTERVAL_MS = 6000;
  var FILTER_DEBOUNCE_MS = 350;

  var state = {
    apiOrigin: "",
    metricsTimer: null,
    processesTimer: null,
    logPaused: false,
    logLines: [],
    streamAbort: null,
    systemMemMb: 8192,
    processCache: {},
    filterTimer: null,
    botFilterTimer: null,
    knownBotIds: {},
    terminalScrollPinned: true, // pinned to newest = top
  };

  function getApiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
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

  function formatUptime(seconds) {
    var s = Math.max(0, parseInt(seconds, 10) || 0);
    if (s < 60) return s + "с";
    var m = Math.floor(s / 60);
    if (m < 60) return m + "м " + (s % 60) + "с";
    var h = Math.floor(m / 60);
    return h + "ч " + (m % 60) + "м";
  }

  function formatTs(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleTimeString("ru-RU", { hour12: false });
    } catch (e) {
      return iso.slice(11, 19) || iso;
    }
  }

  function getFilters() {
    var search = el("mon-log-search");
    var layerF = el("mon-layer-filter");
    var botF = el("mon-bot-filter");
    return {
      q: search && search.value ? search.value.trim().toLowerCase() : "",
      layer: layerF && layerF.value ? layerF.value : "",
      bot: botF && botF.value ? botF.value : "",
    };
  }

  function passesFilters(packet, filters) {
    filters = filters || getFilters();
    if (filters.layer && (packet.layer || "").toUpperCase() !== filters.layer) return false;
    if (filters.bot && String(packet.bot_id || "") !== filters.bot) return false;
    if (filters.q) {
      var hay = ((packet.message || "") + "\n" + (packet.detail || "")).toLowerCase();
      if (hay.indexOf(filters.q) < 0) return false;
    }
    return true;
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
    var layer = (packet.layer || "").toUpperCase();
    if (layer !== "ERROR") return false;
    var hay = ((packet.message || "") + "\n" + (packet.detail || "")).toLowerCase();
    return (
      hay.indexOf("runtime error") >= 0 ||
      hay.indexOf("node_id:") >= 0 ||
      hay.indexOf("traceback") >= 0 ||
      hay.indexOf("exception") >= 0
    );
  }

  function openFixWithAi(packet) {
    var botId = packet && packet.bot_id ? String(packet.bot_id) : "";
    if (!botId) {
      showAlert("Нет bot_id у этой ошибки — откройте редактор сценария вручную.");
      return;
    }
    var nodeId = extractNodeIdFromPacket(packet);
    var payload = {
      bot_id: botId,
      node_id: nodeId,
      message: packet.message || "",
      detail: packet.detail || "",
      timestamp: packet.timestamp || "",
    };
    try {
      global.sessionStorage.setItem("bb_ai_fix_request", JSON.stringify(payload));
    } catch (e) {}
    var url =
      "/editor/scenario/index.html?bot_id=" +
      encodeURIComponent(botId) +
      "&ai_fix=1" +
      (nodeId ? "&node_id=" + encodeURIComponent(nodeId) : "");
    global.open(url, "_blank");
  }

  function createLogNode(packet) {
    var layer = (packet.layer || "API").toUpperCase();
    var hasDetail = !!(packet.detail && String(packet.detail).trim());
    var fixable = isFixableRuntimeError(packet);
    var line = document.createElement("div");
    line.className =
      "mon-log-line" +
      (layer === "ERROR" ? " mon-log-line-error" : "") +
      (hasDetail ? " mon-log-expandable" : "");
    line.dataset.layer = layer;
    line.dataset.bot = packet.bot_id || "";

    var head = document.createElement("div");
    head.className = "mon-log-head";

    var ts = document.createElement("span");
    ts.className = "mon-log-ts";
    ts.textContent = formatTs(packet.timestamp);

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
    badge.textContent = layer === "BOT" && packet.bot_id ? "BOT #" + packet.bot_id : layer;

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
      fixBtn.title = "Fix with AI";
      fixBtn.textContent = "✨ Fix with AI";
      fixBtn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        openFixWithAi(packet);
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
  }

  /** Hard DOM cap: drop oldest nodes (now at the bottom) until <= MAX_VISIBLE_DOM. */
  function enforceDomCap(term) {
    var excess = term.childNodes.length - MAX_VISIBLE_DOM;
    while (excess > 0 && term.lastChild) {
      term.removeChild(term.lastChild);
      excess -= 1;
    }
  }

  function isTerminalPinned(term) {
    return term.scrollTop < 40;
  }

  /**
   * Newest logs go to the top. Batch is chronological, so insert newest-first.
   */
  function appendLogBatch(packets) {
    if (!packets || !packets.length || state.logPaused) return;
    var term = el("mon-terminal");
    if (!term) return;

    var filters = getFilters();
    var frag = document.createDocumentFragment();
    var added = 0;

    for (var i = packets.length - 1; i >= 0; i--) {
      var packet = packets[i];
      if (!packet || !packet.message) continue;
      if (!passesFilters(packet, filters)) continue;
      frag.appendChild(createLogNode(packet));
      added += 1;
    }
    if (!added) return;

    var empty = term.querySelector(".mon-empty");
    if (empty) empty.remove();

    term.insertBefore(frag, term.firstChild);
    enforceDomCap(term);

    if (state.terminalScrollPinned) {
      term.scrollTop = 0;
    }
  }

  function rebuildTerminal() {
    var term = el("mon-terminal");
    if (!term) return;
    var filters = getFilters();
    var visible = state.logLines.filter(function (p) {
      return passesFilters(p, filters);
    });
    if (visible.length > MAX_VISIBLE_DOM) {
      visible = visible.slice(-MAX_VISIBLE_DOM);
    }

    var frag = document.createDocumentFragment();
    for (var i = visible.length - 1; i >= 0; i--) {
      frag.appendChild(createLogNode(visible[i]));
    }

    term.textContent = "";
    if (frag.childNodes.length) {
      term.appendChild(frag);
    } else {
      var empty = document.createElement("div");
      empty.className = "mon-empty";
      empty.textContent = tr("monitor.no_filtered");
      term.appendChild(empty);
    }
    if (state.terminalScrollPinned) {
      term.scrollTop = 0;
    }
  }

  function scheduleFilterRebuild() {
    if (state.filterTimer) clearTimeout(state.filterTimer);
    state.filterTimer = setTimeout(function () {
      state.filterTimer = null;
      rebuildTerminal();
    }, FILTER_DEBOUNCE_MS);
  }

  /** Ingest a server batch (List[Dict]) — store + one DocumentFragment paint. */
  function ingestLogBatch(batch) {
    if (!Array.isArray(batch) || !batch.length) return;

    for (var i = 0; i < batch.length; i++) {
      var packet = batch[i];
      if (!packet || !packet.message) continue;
      state.logLines.push(packet);
      if (packet.bot_id) state.knownBotIds[String(packet.bot_id)] = true;
    }
    if (state.logLines.length > MAX_STORED_LOGS) {
      state.logLines = state.logLines.slice(-MAX_STORED_LOGS);
    }

    appendLogBatch(batch);
    scheduleBotFilterUpdate();
  }

  function scheduleBotFilterUpdate() {
    if (state.botFilterTimer) return;
    state.botFilterTimer = setTimeout(function () {
      state.botFilterTimer = null;
      updateBotFilterOptions();
    }, 1500);
  }

  function updateBotFilterOptions() {
    var sel = el("mon-bot-filter");
    if (!sel) return;
    var current = sel.value;
    Object.keys(state.processCache || {}).forEach(function (id) {
      state.knownBotIds[id] = true;
    });
    var sorted = Object.keys(state.knownBotIds).sort(function (a, b) {
      return parseInt(a, 10) - parseInt(b, 10);
    });
    if (!sorted.length) return;

    var opts = '<option value="">' + tr("monitor.all_bots") + "</option>";
    sorted.forEach(function (id) {
      var name =
        (state.processCache[id] && state.processCache[id].name) || "Bot #" + id;
      opts += '<option value="' + escapeHtml(id) + '">' + escapeHtml(name) + "</option>";
    });
    if (sel.innerHTML !== opts) {
      sel.innerHTML = opts;
      if (current && state.knownBotIds[current]) sel.value = current;
    }
  }

  function showAlert(msg) {
    var box = el("mon-alert");
    if (!box) return;
    if (!msg) {
      box.hidden = true;
      box.textContent = "";
      return;
    }
    box.hidden = false;
    box.textContent = msg;
  }

  /** Metrics UI only — never called from the log path. */
  function updateMetrics(data) {
    if (!data) return;
    var cpuPct = Math.min(100, Math.max(0, data.cpu_percent || 0));
    var memMb = data.memory_mb || 0;
    var mainMem = (data.main && data.main.memory_mb) || 0;
    var mainCpu = (data.main && data.main.cpu_percent) || 0;
    var botsMem = data.bots_memory_mb != null ? data.bots_memory_mb : 0;
    var botsCpu = data.bots_cpu_percent != null ? data.bots_cpu_percent : 0;
    var bots = data.bot_count != null ? data.bot_count : 0;

    var cpuVal = el("mon-cpu-value");
    var cpuBar = el("mon-cpu-bar");
    var cpuDetail = el("mon-cpu-detail");
    var memVal = el("mon-mem-value");
    var memBar = el("mon-mem-bar");
    var memDetail = el("mon-mem-detail");
    var botCount = el("mon-bot-count");
    var mainPid = el("mon-main-pid");

    if (cpuVal) cpuVal.textContent = cpuPct.toFixed(1) + "%";
    if (cpuBar) cpuBar.style.width = cpuPct + "%";
    if (cpuDetail) {
      cpuDetail.textContent = tr("monitor.cpu_detail", {
        server: mainCpu.toFixed(1),
        bots: botsCpu.toFixed(1),
        total: cpuPct.toFixed(1),
      });
    }

    if (memVal) memVal.textContent = memMb.toFixed(1) + " MB";
    if (memBar) {
      var memPct = Math.min(100, (memMb / state.systemMemMb) * 100);
      memBar.style.width = memPct + "%";
    }
    if (memDetail && data.main) {
      var otherMem = data.other_memory_mb != null ? data.other_memory_mb : 0;
      var parts = tr("monitor.mem_detail", {
        pid: data.main.pid,
        main: mainMem.toFixed(1),
        bots: botsMem.toFixed(1),
      });
      if (otherMem > 0) {
        parts += tr("monitor.mem_service", { other: otherMem.toFixed(1) });
      }
      parts += tr("monitor.mem_total", { total: memMb.toFixed(1) });
      memDetail.textContent = parts;
    }
    if (botCount) botCount.textContent = String(bots);
    if (mainPid && data.main) mainPid.textContent = String(data.main.pid);

    if (data.psutil_ok === false) {
      showAlert(tr("monitor.psutil_error"));
    } else {
      showAlert("");
    }
  }

  function fetchMetrics() {
    return fetch(state.apiOrigin + "/api/monitor/resources", { headers: authHeaders() })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showAlert((result.data && result.data.detail) || tr("monitor.metrics_error"));
          return;
        }
        updateMetrics(result.data);
      })
      .catch(function (err) {
        showAlert(err.message || tr("monitor.no_api"));
      });
  }

  function renderProcesses(rows) {
    var tbody = el("mon-process-tbody");
    if (!tbody) return;
    state.processCache = {};
    if (!rows || !rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="mon-empty">' + escapeHtml(tr("monitor.no_bots")) + "</td></tr>";
      return;
    }
    tbody.innerHTML = rows
      .map(function (row) {
        state.processCache[String(row.bot_id)] = row;
        state.knownBotIds[String(row.bot_id)] = true;
        return (
          "<tr>" +
          "<td><strong>" +
          escapeHtml(row.name || "Bot #" + row.bot_id) +
          '</strong><br><span class="mon-metric-hint">#' +
          escapeHtml(row.bot_id) +
          "</span></td>" +
          '<td class="mon-metric-mono">' +
          escapeHtml(row.pid) +
          "</td>" +
          "<td>" +
          escapeHtml((row.cpu_percent || 0).toFixed(1)) +
          "%</td>" +
          "<td>" +
          escapeHtml((row.memory_mb || 0).toFixed(1)) +
          " MB</td>" +
          "<td>" +
          escapeHtml(formatUptime(row.uptime_seconds)) +
          "</td>" +
          "<td>" +
          escapeHtml(row.platform || "—") +
          "</td>" +
          '<td><div class="mon-action-group">' +
          '<button type="button" class="mon-btn-secondary mon-btn-warn" data-action="restart" data-pid="' +
          escapeHtml(row.pid) +
          '">Restart</button>' +
          '<button type="button" class="mon-btn-secondary mon-btn-danger" data-action="kill" data-pid="' +
          escapeHtml(row.pid) +
          '">Kill</button>' +
          "</div></td>" +
          "</tr>"
        );
      })
      .join("");
    scheduleBotFilterUpdate();
  }

  function fetchProcesses() {
    return fetch(state.apiOrigin + "/api/monitor/processes", { headers: authHeaders() })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) return;
        renderProcesses((result.data && result.data.processes) || []);
      })
      .catch(function () {});
  }

  function processAction(pid, action) {
    if (!pid) return;
    fetch(state.apiOrigin + "/api/monitor/process/" + encodeURIComponent(pid) + "/action", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ action: action }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) return;
        fetchProcesses();
        fetchMetrics();
      })
      .catch(function () {});
  }

  function consumeSseChunk(buffer, onEvent) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    parts.forEach(function (block) {
      block.split("\n").forEach(function (line) {
        if (line.indexOf("data: ") === 0) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch (e) {
            /* skip */
          }
        }
      });
    });
    return rest;
  }

  function connectLogStream() {
    closeLogStream();
    var controller = new AbortController();
    state.streamAbort = controller;

    fetch(state.apiOrigin + "/api/monitor/logs/stream", {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(function (res) {
        if (!res.ok || !res.body) throw new Error("stream unavailable");
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";
        function readNext() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buf += decoder.decode(chunk.value, { stream: true });
            buf = consumeSseChunk(buf, function (payload) {
              // Server sends List[Dict] every 500ms; tolerate legacy single-object packets.
              if (Array.isArray(payload)) {
                ingestLogBatch(payload);
              } else if (payload && payload.message) {
                ingestLogBatch([payload]);
              }
            });
            return readNext();
          });
        }
        return readNext();
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        setTimeout(connectLogStream, 4000);
      });
  }

  function closeLogStream() {
    if (state.streamAbort) {
      state.streamAbort.abort();
      state.streamAbort = null;
    }
  }

  function loadHistory() {
    return fetch(state.apiOrigin + "/api/monitor/logs/history?limit=80", {
      headers: authHeaders(),
    })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var logs = (data && data.logs) || [];
        state.logLines = logs.slice(-MAX_STORED_LOGS);
        logs.forEach(function (p) {
          if (p.bot_id) state.knownBotIds[String(p.bot_id)] = true;
        });
        rebuildTerminal();
      })
      .catch(function () {});
  }

  function bindEvents() {
    var term = el("mon-terminal");
    if (term) {
      term.addEventListener("scroll", function () {
        state.terminalScrollPinned = isTerminalPinned(term);
      });
    }

    el("mon-refresh-btn") &&
      el("mon-refresh-btn").addEventListener("click", function () {
        fetchMetrics();
        fetchProcesses();
      });

    el("mon-log-clear") &&
      el("mon-log-clear").addEventListener("click", function () {
        state.logLines = [];
        var t = el("mon-terminal");
        if (t) {
          t.textContent = "";
          var empty = document.createElement("div");
          empty.className = "mon-empty";
          empty.textContent = tr("monitor.log_cleared");
          t.appendChild(empty);
        }
        fetch(state.apiOrigin + "/api/monitor/logs", {
          method: "DELETE",
          headers: authHeaders(),
        }).catch(function () {});
      });

    el("mon-log-pause") &&
      el("mon-log-pause").addEventListener("click", function () {
        state.logPaused = !state.logPaused;
        el("mon-log-pause").textContent = state.logPaused ? tr("monitor.resume") : tr("monitor.pause");
        if (!state.logPaused) rebuildTerminal();
      });

    ["mon-log-search", "mon-layer-filter", "mon-bot-filter"].forEach(function (id) {
      var node = el(id);
      if (!node) return;
      var ev = node.tagName === "SELECT" ? "change" : "input";
      node.addEventListener(ev, scheduleFilterRebuild);
    });

    var tbody = el("mon-process-tbody");
    if (tbody) {
      tbody.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-action]");
        if (!btn) return;
        processAction(btn.getAttribute("data-pid"), btn.getAttribute("data-action"));
      });
    }

    global.addEventListener("beforeunload", function () {
      closeLogStream();
      if (state.metricsTimer) clearInterval(state.metricsTimer);
      if (state.processesTimer) clearInterval(state.processesTimer);
    });
    global.addEventListener("pagehide", function () {
      closeLogStream();
    });
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    if (global.navigator && global.navigator.deviceMemory) {
      state.systemMemMb = Math.max(512, global.navigator.deviceMemory * 1024);
    }
    bindEvents();
    loadHistory();
    connectLogStream();
    // Metrics/charts only on their own 2s cadence — never tied to log paint.
    fetchMetrics();
    fetchProcesses();
    state.metricsTimer = setInterval(fetchMetrics, METRICS_INTERVAL_MS);
    state.processesTimer = setInterval(fetchProcesses, PROCESSES_INTERVAL_MS);

    document.addEventListener("botbuilder:langchange", function () {
      var pauseBtn = el("mon-log-pause");
      if (pauseBtn) pauseBtn.textContent = state.logPaused ? tr("monitor.resume") : tr("monitor.pause");
      updateBotFilterOptions();
      rebuildTerminal();
      fetchMetrics();
      fetchProcesses();
    });
  }

  global.SystemMonitorView = { init: init };
})(typeof window !== "undefined" ? window : globalThis);
