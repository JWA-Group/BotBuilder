/**
 * ChannelHubView — multi-chart analytics + live moderation (vanilla JS + Chart.js).
 */
(function (global) {
  "use strict";

  var PIE_COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#fb7185", "#2dd4bf", "#94a3b8"];

  var CHART_THROTTLE_MS = 4500;
  var FEED_POLL_MS = 5000;
  var CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js";
  var JSPDF_URL = "https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js";
  var HTML2CANVAS_URL = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";

  var state = {
    tab: "analytics",
    range: "30d",
    keywords: [],
    whitelist: [],
    growthChart: null,
    hoursChart: null,
    topPostsChart: null,
    reactionsChart: null,
    modChart: null,
    views: { activity: "bar", reactions: "pie", moderation: "pie" },
    chartCache: { hours: [], reactions: [], moderation: [], topPosts: [] },
    postsAll: [],
    postsIndex: {},
    postsSort: { key: "engagement", dir: "desc" },
    postsSearch: "",
    chartsReady: false,
    lastChartsAt: 0,
    pendingCharts: null,
    botStartQueued: false,
    loading: false,
    loadingCharts: false,
    revision: "",
    feedRevision: "",
    pollTimer: null,
    chartTimer: null,
    comments: [],
    restricted: [],
    feedFilter: "all",
    feedSearch: "",
    selected: null,
    inspector: null,
  };

  function tr(key) {
    return typeof global.t === "function" ? global.t(key) : key;
  }

  function apiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    return (global.location && global.location.origin) || "http://127.0.0.1:8000";
  }

  function headers() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json" };
  }

  function el(id) {
    return document.getElementById(id);
  }

  function botId() {
    var sel = el("bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function setStatus(msg, kind) {
    var node = el("ch-status");
    if (node) {
      node.hidden = true;
      node.textContent = "";
    }
    if (!msg) return;
    var existing = document.getElementById("ch-toast");
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    var isError = kind === "error";
    var toast = document.createElement("div");
    toast.id = "ch-toast";
    toast.className = "ch-toast" + (isError ? " ch-toast-error" : " ch-toast-success");
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<span class="ch-toast-icon" aria-hidden="true">' +
      (isError ? "!" : "✓") +
      '</span><span class="ch-toast-text"></span>';
    toast.querySelector(".ch-toast-text").textContent = msg;
    document.body.appendChild(toast);
    requestAnimationFrame(function () {
      toast.classList.add("visible");
    });
    clearTimeout(setStatus._timer);
    setStatus._timer = setTimeout(function () {
      toast.classList.remove("visible");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 320);
    }, isError ? 4200 : 2600);
  }

  function inlineCloneStyles(sourceRoot, cloneRoot) {
    if (!sourceRoot || !cloneRoot) return;
    var srcNodes = [sourceRoot].concat(Array.prototype.slice.call(sourceRoot.querySelectorAll("*")));
    var cloneNodes = [cloneRoot].concat(Array.prototype.slice.call(cloneRoot.querySelectorAll("*")));
    var n = Math.min(srcNodes.length, cloneNodes.length);
    for (var i = 0; i < n; i++) {
      var cs = window.getComputedStyle(srcNodes[i]);
      var style = cloneNodes[i].style;
      style.background = cs.backgroundColor;
      style.backgroundImage = "none";
      style.backgroundColor = cs.backgroundColor;
      style.color = cs.color;
      style.borderColor = cs.borderColor;
      style.outlineColor = cs.outlineColor;
      style.boxShadow = "none";
      style.backdropFilter = "none";
      style.webkitBackdropFilter = "none";
      style.textShadow = "none";
      style.filter = "none";
      if (cs.borderRadius) style.borderRadius = cs.borderRadius;
      if (cs.padding) style.padding = cs.padding;
      if (cs.margin) style.margin = cs.margin;
      if (cs.font) style.font = cs.font;
      if (cs.display === "none") style.display = "none";
    }
    Array.prototype.forEach.call(cloneRoot.querySelectorAll("canvas"), function (c, idx) {
      var srcCanvas = sourceRoot.querySelectorAll("canvas")[idx];
      if (!srcCanvas) return;
      try {
        var img = cloneRoot.ownerDocument.createElement("img");
        img.src = srcCanvas.toDataURL("image/png");
        img.width = srcCanvas.width;
        img.height = srcCanvas.height;
        img.style.width = srcCanvas.style.width || (srcCanvas.clientWidth + "px");
        img.style.height = srcCanvas.style.height || (srcCanvas.clientHeight + "px");
        img.style.maxWidth = "100%";
        if (c.parentNode) c.parentNode.replaceChild(img, c);
      } catch (e) { /* ignore */ }
    });
  }

  function setLive(ok) {
    var badge = el("ch-live-badge");
    if (!badge) return;
    badge.classList.toggle("is-stale", !ok);
    badge.textContent = ok ? tr("channel_hub.live_sync") : tr("channel_hub.live_sync_stale");
  }

  function fmt(n) {
    var v = Number(n) || 0;
    if (Math.abs(v) >= 1000000) return (v / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(Math.round(v));
  }

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTime(ts) {
    if (!ts) return "—";
    try {
      var d = typeof ts === "number" ? new Date(ts * (ts < 1e12 ? 1000 : 1)) : new Date(ts);
      if (isNaN(d.getTime())) return "—";
      return d.toLocaleString();
    } catch (e) {
      return "—";
    }
  }

  function formatDuration(sec) {
    sec = Math.max(0, Number(sec) || 0);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    if (h > 0) return h + "h " + m + "m";
    return m + "m";
  }

  function loadScriptOnce(url, globalCheck) {
    if (globalCheck && globalCheck()) return Promise.resolve();
    var key = "_ch_script_" + url;
    if (loadScriptOnce[key]) return loadScriptOnce[key];
    loadScriptOnce[key] = new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-ch-src="' + url + '"]');
      if (existing) {
        if (globalCheck && globalCheck()) return resolve();
        existing.addEventListener("load", function () { resolve(); });
        existing.addEventListener("error", function () { reject(new Error("Failed to load " + url)); });
        return;
      }
      var s = document.createElement("script");
      s.src = url;
      s.async = true;
      s.setAttribute("data-ch-src", url);
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("Failed to load " + url)); };
      document.head.appendChild(s);
    });
    return loadScriptOnce[key];
  }

  function ensureChartJs() {
    return loadScriptOnce(CHART_JS_URL, function () { return !!global.Chart; });
  }

  function ensurePdfLibs() {
    return loadScriptOnce(HTML2CANVAS_URL, function () { return !!global.html2canvas; }).then(function () {
      return loadScriptOnce(JSPDF_URL, function () { return !!(global.jspdf && global.jspdf.jsPDF); });
    });
  }

  function fetchJson(path, options) {
    return fetch(apiOrigin() + path, options || { headers: headers() }).then(function (r) {
      return r.text().then(function (text) {
        var data = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (e) {
            if (!r.ok) throw new Error(text.slice(0, 200) || ("HTTP " + r.status));
            throw new Error("Invalid JSON response");
          }
        }
        if (!r.ok) {
          var detail = data && (data.detail || data.error);
          throw new Error(typeof detail === "string" ? detail : ("HTTP " + r.status));
        }
        return data;
      });
    });
  }

  function parseKeywordBlob(raw) {
    return String(raw || "")
      .split(",")
      .map(function (s) { return s.trim(); })
      .filter(function (s) { return !!s; })
      .filter(function (s, i, arr) { return arr.indexOf(s) === i; });
  }

  function normalizeUrlChip(raw) {
    return String(raw || "")
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .replace(/\/$/, "");
  }

  function parseUrlBlob(raw) {
    return parseKeywordBlob(raw)
      .map(normalizeUrlChip)
      .filter(Boolean)
      .filter(function (s, i, arr) { return arr.indexOf(s) === i; });
  }

  function mergeList(targetKey, extra) {
    var next = (state[targetKey] || []).slice();
    (extra || []).forEach(function (kw) {
      if (next.indexOf(kw) < 0) next.push(kw);
    });
    state[targetKey] = next;
    if (targetKey === "keywords") renderChips("rule-chips", "keywords");
    else renderChips("rule-url-chips", "whitelist");
  }

  function chartTheme() {
    var dark = document.documentElement.classList.contains("theme-dark");
    return {
      text: dark ? "#a1a1aa" : "#71717a",
      grid: dark ? "rgba(161,161,170,0.18)" : "rgba(113,113,122,0.18)",
      join: "#22c55e",
      leave: "#ef4444",
    };
  }

  function makeAreaGradient(chart, colorTop, colorBottom) {
    var ctx = chart.ctx;
    var area = chart.chartArea;
    if (!area) return colorTop;
    var g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, colorTop);
    g.addColorStop(1, colorBottom);
    return g;
  }

  function chartAnimOpts() {
    // After first paint, disable entry animations to avoid lag under live traffic.
    return state.chartsReady
      ? { duration: 0, animateRotate: false, animateScale: false }
      : { duration: 600 };
  }

  function chartCommonOptions(extra) {
    var base = {
      responsive: true,
      maintainAspectRatio: false,
      animation: chartAnimOpts(),
      transitions: { active: { animation: { duration: 0 } } },
    };
    if (!extra) return base;
    Object.keys(extra).forEach(function (k) { base[k] = extra[k]; });
    return base;
  }

  function tooltipOpts() {
    return {
      backgroundColor: "rgba(24,24,27,0.92)",
      titleColor: "#fafafa",
      bodyColor: "#e4e4e7",
      cornerRadius: 10,
      padding: 10,
    };
  }

  function destroyChart(key) {
    if (state[key]) {
      state[key].destroy();
      state[key] = null;
    }
  }

  function renderGrowth(series) {
    var canvas = el("ch-growth-chart");
    if (!canvas || !global.Chart) return;
    var theme = chartTheme();
    destroyChart("growthChart");
    state.growthChart = new global.Chart(canvas, {
      type: "line",
      data: {
        labels: (series || []).map(function (p) { return String(p.date).slice(5); }),
        datasets: [
          {
            label: tr("channel_hub.joins"),
            data: (series || []).map(function (p) { return p.joins; }),
            borderColor: theme.join,
            backgroundColor: function (ctx) {
              return makeAreaGradient(ctx.chart, "rgba(34,197,94,0.35)", "rgba(34,197,94,0.02)");
            },
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: tr("channel_hub.leaves"),
            data: (series || []).map(function (p) { return p.leaves; }),
            borderColor: theme.leave,
            backgroundColor: function (ctx) {
              return makeAreaGradient(ctx.chart, "rgba(239,68,68,0.28)", "rgba(239,68,68,0.02)");
            },
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
          },
        ],
      },
      options: chartCommonOptions({
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { color: theme.text, usePointStyle: true } }, tooltip: tooltipOpts() },
        scales: {
          x: { ticks: { color: theme.text }, grid: { color: theme.grid } },
          y: { beginAtZero: true, ticks: { color: theme.text }, grid: { color: theme.grid } },
        },
      }),
    });
  }

  function renderHours(hours) {
    state.chartCache.hours = hours || [];
    var canvas = el("ch-hours-chart");
    if (!canvas || !global.Chart) return;
    var theme = chartTheme();
    var view = state.views.activity;
    destroyChart("hoursChart");
    var labels = state.chartCache.hours.map(function (h) { return String(h.hour).padStart(2, "0"); });
    var values = state.chartCache.hours.map(function (h) { return h.count; });
    if (view === "pie") {
      state.hoursChart = new global.Chart(canvas, {
        type: "doughnut",
        data: {
          labels: labels,
          datasets: [{ data: values, backgroundColor: labels.map(function (_, i) { return PIE_COLORS[i % PIE_COLORS.length]; }), borderWidth: 0 }],
        },
        options: chartCommonOptions({
          plugins: { legend: { display: false }, tooltip: tooltipOpts() },
        }),
      });
      return;
    }
    state.hoursChart = new global.Chart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: tr("channel_hub.comments"),
          data: values,
          backgroundColor: function (ctx) {
            return makeAreaGradient(ctx.chart, "rgba(37,99,235,0.55)", "rgba(37,99,235,0.12)");
          },
          borderRadius: 8,
          borderSkipped: false,
        }],
      },
      options: chartCommonOptions({
        plugins: { legend: { display: false }, tooltip: tooltipOpts() },
        scales: {
          x: { ticks: { color: theme.text }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: theme.text }, grid: { color: theme.grid } },
        },
      }),
    });
  }

  function renderTopPostsChart(posts) {
    state.chartCache.topPosts = (posts || []).slice(0, 5);
    var canvas = el("ch-top-posts-chart");
    if (!canvas || !global.Chart) return;
    var theme = chartTheme();
    destroyChart("topPostsChart");
    var rows = state.chartCache.topPosts;
    state.topPostsChart = new global.Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map(function (p) {
          return "#" + (p.message_id || p.telegram_message_id || p.id || "—");
        }),
        datasets: [{
          label: tr("channel_hub.col_engagement"),
          data: rows.map(function (p) { return p.engagement; }),
          backgroundColor: "#60a5fa",
          borderRadius: 8,
        }],
      },
      options: chartCommonOptions({
        indexAxis: "y",
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, tooltipOpts(), {
            callbacks: {
              title: function (items) {
                var i = items[0] && items[0].dataIndex;
                var p = rows[i];
                if (!p) return "";
                return "#" + (p.message_id || p.telegram_message_id || p.id || "—");
              },
              afterTitle: function (items) {
                var i = items[0] && items[0].dataIndex;
                var p = rows[i];
                if (!p) return "";
                return [
                  tr("channel_hub.col_views") + ": " + fmt(p.views_count),
                  tr("channel_hub.col_comments") + ": " + fmt(p.comments_count),
                ];
              },
            },
          }),
        },
        scales: {
          x: { beginAtZero: true, ticks: { color: theme.text }, grid: { color: theme.grid } },
          y: { ticks: { color: theme.text }, grid: { display: false } },
        },
      }),
    });
  }

  function modLabel(key) {
    var map = {
      clean: tr("channel_hub.slice_clean"),
      warn: tr("channel_hub.warn"),
      mute: tr("channel_hub.slice_mute"),
      ban: tr("channel_hub.ban"),
    };
    return map[key] || key;
  }

  function renderPieOrBar(chartKey, canvasId, slices, viewKey, labelFn) {
    var canvas = el(canvasId);
    if (!canvas || !global.Chart) return;
    var theme = chartTheme();
    var view = state.views[viewKey];
    destroyChart(chartKey);
    var labels = (slices || []).map(function (s) { return labelFn ? labelFn(s.label) : s.label; });
    var values = (slices || []).map(function (s) { return s.count; });
    var colors = labels.map(function (_, i) { return PIE_COLORS[i % PIE_COLORS.length]; });
    if (view === "bar") {
      state[chartKey] = new global.Chart(canvas, {
        type: "bar",
        data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderRadius: 8 }] },
        options: chartCommonOptions({
          plugins: { legend: { display: false }, tooltip: tooltipOpts() },
          scales: {
            x: { ticks: { color: theme.text }, grid: { display: false } },
            y: { beginAtZero: true, ticks: { color: theme.text }, grid: { color: theme.grid } },
          },
        }),
      });
      return;
    }
    state[chartKey] = new global.Chart(canvas, {
      type: "doughnut",
      data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
      options: chartCommonOptions({
        cutout: viewKey === "moderation" ? "62%" : "50%",
        plugins: { legend: { position: "bottom", labels: { color: theme.text } }, tooltip: tooltipOpts() },
      }),
    });
  }

  function renderReactions(slices) {
    state.chartCache.reactions = slices || [];
    renderPieOrBar("reactionsChart", "ch-reactions-chart", state.chartCache.reactions, "reactions");
  }

  function renderModeration(slices) {
    state.chartCache.moderation = slices || [];
    renderPieOrBar("modChart", "ch-mod-chart", state.chartCache.moderation, "moderation", modLabel);
  }

  function filteredSortedPosts() {
    var q = (state.postsSearch || "").trim().toLowerCase();
    var rows = (state.postsAll || []).slice();
    if (q) {
      rows = rows.filter(function (p) {
        var hay = [
          p.message_id,
          p.telegram_message_id,
          p.id,
          p.post_url,
          p.text,
          p.full_text,
        ].join(" ").toLowerCase();
        return hay.indexOf(q) >= 0;
      });
    }
    var key = state.postsSort.key || "engagement";
    var dir = state.postsSort.dir === "asc" ? 1 : -1;
    rows.sort(function (a, b) {
      var av = a[key];
      var bv = b[key];
      if (key === "message_id") {
        av = a.message_id || a.telegram_message_id || a.id || 0;
        bv = b.message_id || b.telegram_message_id || b.id || 0;
      }
      av = Number(av) || 0;
      bv = Number(bv) || 0;
      if (av === bv) return 0;
      return av > bv ? dir : -dir;
    });
    return rows;
  }

  function updateSortButtons() {
    document.querySelectorAll(".ch-sort-btn").forEach(function (btn) {
      var key = btn.getAttribute("data-sort");
      var active = key === state.postsSort.key;
      btn.classList.toggle("ch-sort-active", active);
      btn.setAttribute("data-dir", active ? state.postsSort.dir : "");
    });
  }

  function renderPosts(posts) {
    if (posts) state.postsAll = posts.slice();
    var tbody = el("ch-posts-table") && el("ch-posts-table").querySelector("tbody");
    if (!tbody) return;
    state.postsIndex = {};
    var rows = filteredSortedPosts();
    updateSortButtons();
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5">' + escapeHtml(tr("channel_hub.empty")) + "</td></tr>";
      return;
    }
    tbody.innerHTML = rows.map(function (p) {
      state.postsIndex[String(p.id)] = p;
      var mid = p.message_id || p.telegram_message_id || p.id;
      var url = p.post_url || "#";
      var short = url.replace(/^https?:\/\//, "");
      if (short.length > 28) short = short.slice(0, 26) + "…";
      return '<tr data-post-id="' + p.id + '">' +
        "<td>#" + escapeHtml(mid) + "</td>" +
        '<td><a class="ch-post-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer" data-stop="1">' +
        escapeHtml(short) + "</a></td>" +
        "<td>" + fmt(p.views_count) + "</td>" +
        "<td>" + fmt(p.comments_count) + "</td>" +
        "<td>" + fmt(p.engagement) + "</td></tr>";
    }).join("");
    tbody.querySelectorAll("tr[data-post-id]").forEach(function (row) {
      row.onclick = function (e) {
        if (e.target && (e.target.getAttribute("data-stop") || e.target.closest("a"))) return;
        var post = state.postsIndex[row.getAttribute("data-post-id")];
        if (post) openPostModal(post);
      };
    });
  }

  function openPostModal(post) {
    var modal = el("ch-post-modal");
    if (!modal || !post) return;
    el("pm-id").textContent = "#" + (post.message_id || post.telegram_message_id || post.id || "—");
    el("pm-views").textContent = fmt(post.views_count);
    if (el("pm-reactions")) el("pm-reactions").textContent = fmt(post.reactions_count);
    el("pm-comments").textContent = fmt(post.comments_count);
    el("pm-engagement").textContent = fmt(post.engagement);
    var link = el("pm-link");
    var url = post.post_url || "#";
    link.href = url;
    link.textContent = url;
    el("pm-text").textContent = post.full_text || post.text || "";
    modal.hidden = false;
  }

  function closePostModal() {
    var modal = el("ch-post-modal");
    if (modal) modal.hidden = true;
  }

  function renderChips(wrapId, listKey) {
    var wrap = el(wrapId);
    if (!wrap) return;
    wrap.innerHTML = "";
    (state[listKey] || []).forEach(function (kw, idx) {
      var chip = document.createElement("span");
      chip.className = "ch-chip";
      chip.innerHTML = escapeHtml(kw) + ' <button type="button" data-idx="' + idx + '" aria-label="' + escapeHtml(tr("common.remove")) + '">×</button>';
      wrap.appendChild(chip);
    });
    wrap.querySelectorAll("button").forEach(function (btn) {
      btn.onclick = function () {
        state[listKey].splice(Number(btn.getAttribute("data-idx")), 1);
        renderChips(wrapId, listKey);
      };
    });
  }

  function fillRules(rules) {
    state.keywords = (rules && rules.forbidden_keywords) || [];
    state.whitelist = (rules && rules.allowed_urls_whitelist) || [];
    renderChips("rule-chips", "keywords");
    renderChips("rule-url-chips", "whitelist");
    if (el("rule-block-links")) el("rule-block-links").checked = !!(rules && rules.block_links);
    if (el("rule-block-stickers")) el("rule-block-stickers").checked = !!(rules && rules.block_stickers);
    if (el("rule-block-media")) el("rule-block-media").checked = !!(rules && rules.block_media);
    if (el("rule-anti-flood")) el("rule-anti-flood").checked = !!(rules && rules.anti_flood);
    if (el("rule-mute-permanent")) el("rule-mute-permanent").checked = !!(rules && rules.mute_permanent);
    if (el("rule-instant-mute")) el("rule-instant-mute").checked = !!(rules && rules.instant_mute_on_warn);
    if (el("rule-enabled")) el("rule-enabled").checked = !rules || rules.enabled !== false;
    if (el("rule-max-warnings")) el("rule-max-warnings").value = (rules && rules.max_warnings) || 3;
    if (el("rule-mute-minutes")) el("rule-mute-minutes").value = (rules && rules.mute_duration_minutes) || 60;
    if (el("rule-flood-max")) el("rule-flood-max").value = (rules && rules.flood_max_messages) || 5;
    if (el("rule-flood-window")) el("rule-flood-window").value = (rules && rules.flood_time_window_seconds) || 10;
    if (el("rule-flood-action")) el("rule-flood-action").value = (rules && rules.flood_action) || "warn";
    if (el("rule-warn-decay")) el("rule-warn-decay").value = (rules && rules.warn_decay_hours) || 24;
    if (el("rule-instant-mute-mins")) el("rule-instant-mute-mins").value = (rules && rules.instant_mute_duration_minutes) || 10;
  }

  function restrictedMap() {
    var map = {};
    (state.restricted || []).forEach(function (u) {
      if (u.user_id != null) map[String(u.user_id)] = u;
    });
    return map;
  }

  function commentStatus(c, rmap) {
    var kind = c.violation_kind || "";
    var r = rmap[String(c.user_id)];
    if (r && r.action === "ban") return { key: "banned", cls: "ch-badge-high", label: tr("channel_hub.badge_high") };
    if (kind === "flood" || (r && r.action === "mute")) return { key: "muted", cls: "ch-badge-warn", label: tr("channel_hub.badge_flood") };
    if (kind === "link" || kind === "keyword" || c.moderated || c.is_deleted) {
      return { key: "flagged", cls: "ch-badge-high", label: tr("channel_hub.badge_spam") };
    }
    return { key: "clean", cls: "ch-badge-clean", label: tr("channel_hub.badge_clean") };
  }

  function filteredFeed() {
    var q = (state.feedSearch || "").toLowerCase();
    var rmap = restrictedMap();
    return (state.comments || []).filter(function (c) {
      if (c.is_deleted && state.feedFilter !== "all") {
        /* still show deleted in all */
      }
      var st = commentStatus(c, rmap);
      if (state.feedFilter === "flagged" && !(st.key === "flagged" || c.moderated || c.is_deleted)) return false;
      if (state.feedFilter === "muted" && st.key !== "muted") return false;
      if (state.feedFilter === "banned" && st.key !== "banned") return false;
      if (!q) return true;
      var hay = ((c.username || "") + " " + (c.text || "") + " " + (c.user_id || "")).toLowerCase();
      return hay.indexOf(q) >= 0;
    });
  }

  function deleteComment(c, ev) {
    if (ev) ev.stopPropagation();
    if (!c || !c.message_id || !c.chat_id) return;
    var id = botId();
    if (!id) return;
    var card = document.querySelector('.ch-feed-item[data-id="' + c.id + '"]');
    if (card) card.classList.add("is-removing");
    fetchJson("/api/telegram/comment", {
      method: "DELETE",
      headers: headers(),
      body: JSON.stringify({
        bot_id: Number(id),
        chat_id: Number(c.chat_id),
        message_id: Number(c.message_id),
        user_id: Number(c.user_id || 0),
        username: c.username || "",
      }),
    })
      .then(function () {
        state.comments = (state.comments || []).filter(function (x) { return x.id !== c.id; });
        if (state.selected && state.selected.id === c.id) state.selected = null;
        setStatus(tr("channel_hub.action_ok"));
        renderFeed();
        if (state.inspector) loadInspector(state.selected || { user_id: c.user_id, chat_id: c.chat_id, username: c.username });
      })
      .catch(function (err) {
        if (card) card.classList.remove("is-removing");
        setStatus(String(err.message || err), "error");
      });
  }

  function renderFeed() {
    var list = el("ch-feed-list");
    if (!list) return;
    var rows = filteredFeed();
    var rmap = restrictedMap();
    if (!rows.length) {
      list.innerHTML = '<div class="ch-inspector-empty">' + escapeHtml(tr("channel_hub.empty")) + "</div>";
      return;
    }
    list.innerHTML = rows.map(function (c) {
      var st = commentStatus(c, rmap);
      var selected = state.selected && state.selected.id === c.id ? " is-selected" : "";
      var gone = c.is_deleted ? " is-deleted" : "";
      return '<article class="ch-feed-item' + selected + gone + '" data-id="' + c.id + '">' +
        '<div class="ch-feed-top"><span class="ch-feed-user">' + escapeHtml(c.username || c.user_id || "—") +
        '</span><span class="ch-badge ' + st.cls + '">' + escapeHtml(st.label) + "</span></div>" +
        '<div class="ch-feed-text">' + escapeHtml(c.text || "") + "</div>" +
        '<div class="ch-feed-actions">' +
        '<button type="button" class="db-btn-danger ch-btn-sm" data-del="' + c.id + '">' + escapeHtml(tr("channel_hub.delete_comment")) + "</button>" +
        "</div></article>";
    }).join("");
    list.querySelectorAll(".ch-feed-item").forEach(function (node) {
      node.onclick = function (e) {
        if (e.target && e.target.getAttribute("data-del")) return;
        var id = Number(node.getAttribute("data-id"));
        var item = (state.comments || []).find(function (c) { return c.id === id; });
        if (!item) return;
        state.selected = item;
        renderFeed();
        loadInspector(item);
      };
    });
    list.querySelectorAll("[data-del]").forEach(function (btn) {
      btn.onclick = function (e) {
        e.stopPropagation();
        var id = Number(btn.getAttribute("data-del"));
        var item = (state.comments || []).find(function (c) { return c.id === id; });
        if (item) deleteComment(item, e);
      };
    });
  }

  function loadInspector(item) {
    var empty = el("ch-inspector-empty");
    var body = el("ch-inspector-body");
    if (!item || !item.user_id) {
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
      return;
    }
    var id = botId();
    var path = "/api/channel/" + encodeURIComponent(id) + "/users/" + encodeURIComponent(item.user_id);
    if (item.chat_id) path += "?chat_id=" + encodeURIComponent(item.chat_id);
    fetchJson(path)
      .then(function (data) {
        state.inspector = data;
        if (empty) empty.hidden = true;
        if (body) body.hidden = false;
        el("insp-username").textContent = data.username || item.username || "—";
        el("insp-userid").textContent = String(data.user_id || item.user_id);
        el("insp-joined").textContent = formatTime(data.joined_at);
        el("insp-warnings").textContent = String(data.warning_count || 0);
        el("insp-reason").textContent = data.last_reason || "";
        var decay = el("insp-decay");
        if (decay) {
          if (data.decay_seconds_left != null && data.warning_count > 0) {
            decay.textContent = tr("channel_hub.decay_in") + ": " + formatDuration(data.decay_seconds_left);
          } else {
            decay.textContent = "";
          }
        }
        var hist = el("insp-history");
        if (!hist) return;
        var comments = data.comments || [];
        if (!comments.length) {
          hist.innerHTML = '<div class="ch-inspector-empty">' + escapeHtml(tr("channel_hub.empty")) + "</div>";
          return;
        }
        hist.innerHTML = comments.map(function (c) {
          return '<div class="ch-history-item">' +
            '<div class="ch-history-top">' + escapeHtml(c.text || "") +
            (c.is_deleted ? "" : ' <button type="button" class="db-btn-danger ch-btn-sm" data-hist-del="' + c.id + '">' + escapeHtml(tr("channel_hub.delete_comment")) + "</button>") +
            "</div><div class='an-label'>" + escapeHtml(formatTime(c.created_at)) +
            (c.is_deleted ? " · " + escapeHtml(tr("channel_hub.deleted")) : "") + "</div></div>";
        }).join("");
        hist.querySelectorAll("[data-hist-del]").forEach(function (btn) {
          btn.onclick = function () {
            var cid = Number(btn.getAttribute("data-hist-del"));
            var row = comments.find(function (c) { return c.id === cid; });
            if (!row) return;
            deleteComment({
              id: row.id,
              chat_id: row.chat_id || data.chat_id,
              message_id: row.message_id,
              user_id: data.user_id,
              username: data.username,
            });
          };
        });
      })
      .catch(function (err) {
        setStatus(String(err.message || err), "error");
      });
  }

  function applyCharts(snap) {
    if (!snap) return;
    renderGrowth((snap.growth && snap.growth.series) || []);
    renderHours((snap.activity_hours && snap.activity_hours.hours) || []);
    renderPosts((snap.posts && snap.posts.posts) || []);
    var charts = snap.charts || {};
    renderTopPostsChart((charts.top_posts_chart && charts.top_posts_chart.posts) || []);
    renderReactions((charts.reactions && charts.reactions.slices) || []);
    renderModeration((charts.moderation && charts.moderation.slices) || []);
    state.chartsReady = true;
    state.lastChartsAt = Date.now();
    state.revision = snap.revision || state.revision;
  }

  function applySnapshot(snap, forceCharts) {
    if (!snap) return;
    var ov = snap.overview || {};
    if (el("kpi-subscribers")) el("kpi-subscribers").textContent = fmt(ov.subscribers);
    if (el("kpi-joins")) el("kpi-joins").textContent = fmt(ov.joins_today);
    if (el("kpi-leaves")) el("kpi-leaves").textContent = fmt(ov.leaves_today);
    if (el("kpi-err")) el("kpi-err").textContent = fmt(ov.engagement_score != null ? ov.engagement_score : ov.engagement_rate);
    if (el("kpi-moderated")) el("kpi-moderated").textContent = fmt(ov.comments_moderated);
    // Live feed always updates immediately (decoupled from charts).
    state.comments = (snap.comments && snap.comments.comments) || [];
    state.restricted = (snap.restricted && snap.restricted.users) || [];
    renderFeed();
    state.feedRevision = snap.revision || "";

    var now = Date.now();
    var chartsDue = forceCharts || !state.chartsReady || (now - state.lastChartsAt >= CHART_THROTTLE_MS);
    if (chartsDue) {
      state.pendingCharts = snap;
      // Defer Chart.js work so the window stays interactive (back button, tabs).
      var snapRef = snap;
      setTimeout(function () {
        if (state.pendingCharts !== snapRef && !forceCharts) return;
        ensureChartJs()
          .then(function () {
            if (state.pendingCharts !== snapRef && state.chartsReady && !forceCharts) return;
            applyCharts(snapRef);
            if (state.pendingCharts === snapRef) state.pendingCharts = null;
          })
          .catch(function () {
            /* charts optional — KPIs/feed already shown */
          });
      }, forceCharts ? 16 : 50);
    } else {
      state.pendingCharts = snap;
    }
    if (forceCharts && !state.keywords.length) fillRules(snap.rules || {});
    if (!(ov.channels || []).length) setStatus(tr("channel_hub.no_channels"));
    else if (forceCharts) setStatus("");
  }

  function ensureBotRunning(id) {
    if (!id || state.botStartQueued) return;
    state.botStartQueued = true;
    fetchJson("/api/bots/status/" + encodeURIComponent(id))
      .then(function (st) {
        if (!st || !st.running) {
          return fetchJson("/api/bots/start/" + encodeURIComponent(id), {
            method: "POST",
            headers: headers(),
          }).catch(function () { return null; });
        }
        return null;
      })
      .catch(function () { return null; });
  }

  function refresh(force) {
    var id = botId();
    if (!id) {
      setLive(false);
      return Promise.resolve();
    }
    if (state.loading && !force) return Promise.resolve();
    state.loading = true;
    return fetchJson("/api/channel/" + encodeURIComponent(id) + "/snapshot?range=" + encodeURIComponent(state.range))
      .then(function (snap) {
        applySnapshot(snap, !!force);
        setLive(true);
      })
      .catch(function (err) {
        setLive(false);
        setStatus(String(err.message || err), "error");
      })
      .finally(function () {
        state.loading = false;
      });
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(function () {
      if (document.hidden) return;
      refresh(false);
    }, FEED_POLL_MS);
    state.chartTimer = setInterval(function () {
      if (document.hidden) return;
      if (state.pendingCharts) {
        var snap = state.pendingCharts;
        ensureChartJs()
          .then(function () {
            if (state.pendingCharts !== snap) return;
            applyCharts(snap);
            state.pendingCharts = null;
          })
          .catch(function () {});
      }
    }, CHART_THROTTLE_MS);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    if (state.chartTimer) {
      clearInterval(state.chartTimer);
      state.chartTimer = null;
    }
  }

  function loadBots() {
    return fetchJson("/api/channel/bots").then(function (data) {
      var bots = (data && data.bots) || [];
      var sel = el("bot-select");
      if (!sel) return bots;
      var current = sel.value;
      sel.innerHTML = "";
      bots.forEach(function (b) {
        var opt = document.createElement("option");
        opt.value = b.id;
        opt.textContent = b.name + (b.kind === "moderator" ? " · " + tr("channel_hub.moderator_bot") : "");
        sel.appendChild(opt);
      });
      var preferred = bots.find(function (b) { return b.kind === "moderator"; }) || bots[0];
      if (current) sel.value = current;
      else if (preferred) sel.value = String(preferred.id);
      var setup = el("ch-setup-panel");
      if (setup) setup.hidden = bots.some(function (b) { return b.kind === "moderator"; });
      return bots;
    });
  }

  function connectModerator() {
    var token = (el("mod-token") && el("mod-token").value || "").trim();
    var name = (el("mod-name") && el("mod-name").value || "").trim();
    if (!token) return setStatus(tr("channel_hub.token_required"), "error");
    setStatus(tr("channel_hub.connecting"));
    fetchJson("/api/channel/moderator/setup", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ api_token: token, name: name }),
    })
      .then(function (bot) {
        if (el("mod-token")) el("mod-token").value = "";
        setStatus(tr("channel_hub.connected"));
        return loadBots().then(function () {
          if (bot && bot.id && el("bot-select")) el("bot-select").value = String(bot.id);
          return refresh(true);
        });
      })
      .catch(function (err) {
        setStatus(String(err.message || err), "error");
      });
  }

  function saveRules() {
    var id = botId();
    if (!id) return setStatus(tr("common.select_bot"), "error");
    var payload = {
      channel_id: 0,
      forbidden_keywords: state.keywords.slice(),
      allowed_urls_whitelist: state.whitelist.slice(),
      block_links: el("rule-block-links").checked,
      block_stickers: el("rule-block-stickers").checked,
      block_media: el("rule-block-media").checked,
      anti_flood: el("rule-anti-flood").checked,
      mute_permanent: el("rule-mute-permanent").checked,
      instant_mute_on_warn: el("rule-instant-mute").checked,
      enabled: el("rule-enabled").checked,
      max_warnings: Number(el("rule-max-warnings").value || 3),
      mute_duration_minutes: Number(el("rule-mute-minutes").value || 60),
      flood_max_messages: Number(el("rule-flood-max").value || 5),
      flood_time_window_seconds: Number(el("rule-flood-window").value || 10),
      flood_action: el("rule-flood-action").value || "warn",
      warn_decay_hours: Number(el("rule-warn-decay").value || 24),
      instant_mute_duration_minutes: Number(el("rule-instant-mute-mins").value || 10),
    };
    fetchJson("/api/channel/" + encodeURIComponent(id) + "/rules", {
      method: "PUT",
      headers: headers(),
      body: JSON.stringify(payload),
    })
      .then(function (rules) {
        fillRules(rules);
        setStatus(tr("channel_hub.rules_saved"));
      })
      .catch(function (err) {
        setStatus(String(err.message || err), "error");
      });
  }

  function addKeywordsFromInput() {
    var input = el("rule-keyword-input");
    if (!input) return;
    mergeList("keywords", parseKeywordBlob(input.value));
    input.value = "";
  }

  function addUrlsFromInput() {
    var input = el("rule-whitelist-input");
    if (!input) return;
    mergeList("whitelist", parseUrlBlob(input.value));
    input.value = "";
  }

  function runAction(payload) {
    var id = botId();
    if (!id) return setStatus(tr("common.select_bot"), "error");
    if (!payload.user_id) return setStatus(tr("channel_hub.no_user"), "error");
    fetchJson("/api/channel/" + encodeURIComponent(id) + "/actions", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify(payload),
    })
      .then(function () {
        setStatus(tr("channel_hub.action_ok"));
        return refresh(true).then(function () {
          if (state.selected) loadInspector(state.selected);
        });
      })
      .catch(function (err) {
        setStatus(String(err.message || err), "error");
      });
  }

  function exportPdf() {
    var root = el("ch-dashboard-root");
    if (!root) return;
    setStatus(tr("channel_hub.exporting"));
    var prevTab = state.tab;
    switchTab("analytics");
    closePostModal();
    document.body.classList.add("pdf-rendering");

    function cleanup() {
      document.body.classList.remove("pdf-rendering");
      switchTab(prevTab);
    }

    function runElectronPdf() {
      return global.electronAPI.exportPdf({ defaultName: "channel-hub-report.pdf" }).then(function (res) {
        cleanup();
        if (res && res.canceled) {
          setStatus("");
          return;
        }
        setStatus(tr("channel_hub.export_done"));
      });
    }

    function runHtml2CanvasPdf() {
      return ensurePdfLibs().then(function () {
        var jsPDF = global.jspdf && global.jspdf.jsPDF;
        if (!global.html2canvas || !jsPDF) {
          cleanup();
          setStatus(tr("channel_hub.export_unavailable"), "error");
          return;
        }
        return global.html2canvas(root, {
          backgroundColor: getComputedStyle(document.documentElement).getPropertyValue("--bg-main").trim() || "#ffffff",
          scale: 2,
          useCORS: true,
          logging: false,
          foreignObjectRendering: false,
          onclone: function (clonedDoc) {
            clonedDoc.body.classList.add("pdf-rendering");
            var clonedRoot = clonedDoc.getElementById("ch-dashboard-root");
            inlineCloneStyles(root, clonedRoot);
            Array.prototype.forEach.call(clonedDoc.querySelectorAll("style"), function (s) {
              if (s.textContent && (s.textContent.indexOf("color-mix") >= 0 || s.textContent.indexOf("color(") >= 0)) {
                s.textContent = "";
              }
            });
          },
        }).then(function (canvas) {
          var pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
          var pageWidth = pdf.internal.pageSize.getWidth();
          var pageHeight = pdf.internal.pageSize.getHeight();
          var margin = 28;
          pdf.setFontSize(16);
          pdf.text(tr("channel_hub.pdf_title"), margin, 36);
          pdf.setFontSize(10);
          pdf.setTextColor(120);
          pdf.text(new Date().toLocaleString() + " · " + state.range, margin, 52);
          var imgWidth = pageWidth - margin * 2;
          var imgHeight = (canvas.height * imgWidth) / canvas.width;
          var y = 64;
          var remaining = imgHeight;
          var srcY = 0;
          var sliceHeight = ((pageHeight - y - margin) * canvas.width) / imgWidth;
          while (remaining > 0) {
            var pageCanvas = document.createElement("canvas");
            pageCanvas.width = canvas.width;
            pageCanvas.height = Math.min(sliceHeight, canvas.height - srcY);
            var ctx = pageCanvas.getContext("2d");
            ctx.drawImage(canvas, 0, srcY, canvas.width, pageCanvas.height, 0, 0, canvas.width, pageCanvas.height);
            var pageData = pageCanvas.toDataURL("image/png");
            var drawH = (pageCanvas.height * imgWidth) / canvas.width;
            pdf.addImage(pageData, "PNG", margin, y, imgWidth, drawH);
            remaining -= drawH;
            srcY += pageCanvas.height;
            if (remaining > 4) {
              pdf.addPage();
              y = margin;
            }
          }
          pdf.save("channel-hub-report.pdf");
          cleanup();
          setStatus(tr("channel_hub.export_done"));
        });
      });
    }

    setTimeout(function () {
      var p =
        global.electronAPI && typeof global.electronAPI.exportPdf === "function"
          ? runElectronPdf()
          : runHtml2CanvasPdf();
      Promise.resolve(p).catch(function (err) {
        cleanup();
        setStatus(String(err.message || err), "error");
      });
    }, 220);
  }

  function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".ch-tab").forEach(function (btn) {
      btn.classList.toggle("ch-tab-active", btn.getAttribute("data-tab") === tab);
    });
    ["analytics", "rules", "moderation"].forEach(function (name) {
      var panel = el("tab-" + name);
      if (panel) panel.hidden = name !== tab;
    });
  }

  function bindChipInput(inputId, addFn) {
    var input = el(inputId);
    if (!input) return;
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        addFn();
      }
    });
    input.addEventListener("blur", function () {
      if ((input.value || "").indexOf(",") >= 0) addFn();
    });
  }

  function bind() {
    document.querySelectorAll(".ch-tab").forEach(function (btn) {
      btn.onclick = function () {
        var tab = btn.getAttribute("data-tab");
        switchTab(tab);
        if (tab === "rules" && !state.keywords.length) refresh(true);
      };
    });
    document.querySelectorAll(".an-range-btn").forEach(function (btn) {
      btn.onclick = function () {
        state.range = btn.getAttribute("data-range") || "30d";
        document.querySelectorAll(".an-range-btn").forEach(function (b) {
          b.classList.toggle("an-range-btn-active", b === btn);
        });
        refresh(true);
      };
    });
    document.querySelectorAll(".ch-view-switch").forEach(function (group) {
      var key = group.getAttribute("data-switch");
      group.querySelectorAll(".ch-view-btn").forEach(function (btn) {
        btn.onclick = function () {
          state.views[key] = btn.getAttribute("data-view") || "bar";
          group.querySelectorAll(".ch-view-btn").forEach(function (b) {
            b.classList.toggle("ch-view-active", b === btn);
          });
          if (key === "activity") renderHours(state.chartCache.hours);
          if (key === "reactions") renderReactions(state.chartCache.reactions);
          if (key === "moderation") renderModeration(state.chartCache.moderation);
        };
      });
    });
    document.querySelectorAll(".ch-filter-btn").forEach(function (btn) {
      btn.onclick = function () {
        state.feedFilter = btn.getAttribute("data-filter") || "all";
        document.querySelectorAll(".ch-filter-btn").forEach(function (b) {
          b.classList.toggle("ch-filter-active", b === btn);
        });
        renderFeed();
      };
    });
    var search = el("ch-feed-search");
    if (search) {
      search.oninput = function () {
        state.feedSearch = search.value || "";
        renderFeed();
      };
    }
    var postsSearch = el("ch-posts-search");
    if (postsSearch) {
      postsSearch.oninput = function () {
        state.postsSearch = postsSearch.value || "";
        renderPosts();
      };
    }
    document.querySelectorAll(".ch-sort-btn").forEach(function (btn) {
      btn.onclick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        var key = btn.getAttribute("data-sort") || "engagement";
        if (state.postsSort.key === key) {
          state.postsSort.dir = state.postsSort.dir === "desc" ? "asc" : "desc";
        } else {
          state.postsSort.key = key;
          state.postsSort.dir = key === "message_id" ? "asc" : "desc";
        }
        renderPosts();
      };
    });
    var sel = el("bot-select");
    if (sel) sel.onchange = function () { refresh(true); };
    var connectBtn = el("mod-connect");
    if (connectBtn) connectBtn.onclick = connectModerator;
    var addBtn = el("rule-add-keyword");
    if (addBtn) addBtn.onclick = addKeywordsFromInput;
    var addUrl = el("rule-add-url");
    if (addUrl) addUrl.onclick = addUrlsFromInput;
    bindChipInput("rule-keyword-input", addKeywordsFromInput);
    bindChipInput("rule-whitelist-input", addUrlsFromInput);
    var saveBtn = el("rule-save");
    if (saveBtn) saveBtn.onclick = saveRules;
    var exportBtn = el("ch-export-pdf");
    if (exportBtn) exportBtn.onclick = exportPdf;
    var modalClose = el("ch-post-modal-close");
    if (modalClose) modalClose.onclick = closePostModal;
    var modal = el("ch-post-modal");
    if (modal) {
      modal.querySelectorAll("[data-close-modal]").forEach(function (node) {
        node.onclick = closePostModal;
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closePostModal();
    });
    document.querySelectorAll("[data-insp-act]").forEach(function (btn) {
      btn.onclick = function () {
        var insp = state.inspector || state.selected;
        if (!insp) return;
        runAction({
          action: btn.getAttribute("data-insp-act"),
          chat_id: Number(insp.chat_id || (state.selected && state.selected.chat_id) || 0),
          user_id: Number(insp.user_id || (state.selected && state.selected.user_id) || 0),
          username: insp.username || (state.selected && state.selected.username) || "",
          duration_minutes: btn.getAttribute("data-mins") ? Number(btn.getAttribute("data-mins")) : null,
          reason: tr("channel_hub.manual_reason"),
          channel_id: state.selected && state.selected.channel_id ? Number(state.selected.channel_id) : null,
          message_id: state.selected && state.selected.message_id ? Number(state.selected.message_id) : null,
        });
      };
    });
  }

  function init() {
    bind();
    switchTab("analytics");
    // Shell is interactive immediately; data + charts fill in without blocking navigation.
    loadBots()
      .then(function () { return refresh(true); })
      .then(function () {
        startPolling();
        setTimeout(function () {
          ensureBotRunning(botId());
        }, 2000);
      })
      .catch(function (err) {
        setLive(false);
        setStatus(String(err.message || err), "error");
      });
    global.addEventListener("beforeunload", stopPolling);
  }

  global.ChannelHubView = { init: init, refresh: refresh };
})(window);
