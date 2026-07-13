/**
 * AnalyticsView — Product & Marketing Analytics Dashboard (Chart.js).
 */
(function (global) {
  "use strict";

  var state = {
    apiOrigin: "",
    headers: {},
    range: "30d",
    activityChart: null,
    loading: false,
  };

  function getApiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
  }

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function authHeaders() {
    return typeof global.apiHeaders === "function" ? global.apiHeaders() : {};
  }

  function jsonHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json" };
  }

  function el(id) {
    return document.getElementById(id);
  }

  function selectedBotId() {
    var sel = el("bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function setStatus(msg, kind) {
    var node = el("an-status");
    if (!node) return;
    if (!msg) {
      node.hidden = true;
      node.textContent = "";
      node.className = "an-status";
      return;
    }
    node.hidden = false;
    node.textContent = msg;
    node.className = "an-status" + (kind === "error" ? " an-status-error" : "");
  }

  function formatNumber(n) {
    var v = Number(n) || 0;
    if (Math.abs(v) >= 1000000) return (v / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    if (Math.abs(v) % 1 !== 0) return v.toFixed(1);
    return String(Math.round(v));
  }

  function trendBadge(changePct, invert) {
    var pct = changePct == null ? null : Number(changePct);
    if (pct == null || isNaN(pct)) {
      return { cls: "an-trend-flat", text: "—" };
    }
    var upIsGood = !invert;
    var isUp = pct > 0.05;
    var isDown = pct < -0.05;
    var arrow = isUp ? "▲" : isDown ? "▼" : "●";
    var cls = "an-trend-flat";
    if (isUp) cls = upIsGood ? "an-trend-up" : "an-trend-down";
    if (isDown) cls = upIsGood ? "an-trend-down" : "an-trend-up";
    var sign = pct > 0 ? "+" : "";
    return { cls: cls, text: arrow + " " + sign + pct.toFixed(1) + "%" };
  }

  function applyTrend(elId, changePct, invert) {
    var node = el(elId);
    if (!node) return;
    var t = trendBadge(changePct, invert);
    node.className = "an-trend " + t.cls;
    node.textContent = t.text;
  }

  function metricValue(obj) {
    if (obj == null) return 0;
    if (typeof obj === "object" && obj.value != null) return obj.value;
    return obj;
  }

  function metricChange(obj) {
    if (obj && typeof obj === "object") return obj.change_pct;
    return null;
  }

  function loadBots() {
    return fetch(state.apiOrigin + "/api/analytics/bots", { headers: state.headers })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var sel = el("bot-select");
        if (!sel) return;
        var prev = sel.value;
        sel.innerHTML = '<option value="">' + tr("common.select") + "</option>";
        (data || []).forEach(function (b) {
          var opt = document.createElement("option");
          opt.value = b.id;
          opt.textContent = b.name || "Bot " + b.id;
          sel.appendChild(opt);
        });
        if (prev) sel.value = prev;
        if (!sel.value && data && data.length) {
          sel.value = String(data[0].id);
        }
      })
      .catch(function () {});
  }

  function apiUrl(path) {
    var botId = selectedBotId();
    return (
      state.apiOrigin +
      "/api/projects/" +
      encodeURIComponent(botId) +
      "/analytics/" +
      path +
      "?range=" +
      encodeURIComponent(state.range)
    );
  }

  function renderOverview(data) {
    if (!data) return;
    var subs = data.total_subscribers || {};
    var active = data.active_users || {};
    var dau = data.dau || {};
    var mau = data.mau || {};
    var messages = data.messages_sent || {};
    var errRate = data.error_rate || {};

    if (el("kpi-subscribers")) el("kpi-subscribers").textContent = formatNumber(metricValue(subs));
    applyTrend("kpi-subscribers-trend", metricChange(subs), false);

    var dauVal = metricValue(dau);
    var mauVal = metricValue(mau);
    if (el("kpi-active")) {
      el("kpi-active").textContent = formatNumber(dauVal) + " / " + formatNumber(mauVal);
    }
    applyTrend("kpi-active-trend", metricChange(active), false);
    if (el("kpi-active-hint")) {
      el("kpi-active-hint").textContent = tr("analytics.active_hint", {
        dau: formatNumber(dauVal),
        mau: formatNumber(mauVal),
        active: formatNumber(metricValue(active)),
      });
    }

    if (el("kpi-messages")) el("kpi-messages").textContent = formatNumber(metricValue(messages));
    applyTrend("kpi-messages-trend", metricChange(messages), false);

    var er = metricValue(errRate);
    if (el("kpi-errors")) el("kpi-errors").textContent = (Number(er) || 0).toFixed(2) + "%";
    applyTrend("kpi-errors-trend", metricChange(errRate), true);
  }

  function renderActivityChart(series, granularity) {
    var canvas = el("an-activity-chart");
    if (!canvas || !global.Chart) return;
    var isHourly = granularity === "hour";
    var labels = (series || []).map(function (p) {
      return p.date;
    });
    var newUsers = (series || []).map(function (p) {
      return p.new_users || 0;
    });
    var messages = (series || []).map(function (p) {
      return p.messages_count || 0;
    });

    var ctx = canvas.getContext("2d");
    if (state.activityChart) {
      state.activityChart.data.labels = labels;
      state.activityChart.data.datasets[0].label = tr("analytics.chart_new_users");
      state.activityChart.data.datasets[1].label = tr("analytics.chart_messages");
      state.activityChart.data.datasets[0].data = newUsers;
      state.activityChart.data.datasets[1].data = messages;
      state.activityChart.options.scales.x.ticks.maxTicksLimit = isHourly ? 12 : 8;
      state.activityChart.options.scales.x.ticks.callback = function (val) {
        var label = this.getLabelForValue(val);
        if (!label) return label;
        if (isHourly) return label;
        return label.length >= 10 ? label.slice(5) : label;
      };
      state.activityChart.update("active");
      return;
    }

    state.activityChart = new global.Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: tr("analytics.chart_new_users"),
            data: newUsers,
            borderColor: "#2563eb",
            backgroundColor: "rgba(37, 99, 235, 0.12)",
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderWidth: 2.5,
            yAxisID: "y",
          },
          {
            label: tr("analytics.chart_messages"),
            data: messages,
            borderColor: "#06b6d4",
            backgroundColor: "rgba(6, 182, 212, 0.08)",
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderWidth: 2.5,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "top",
            align: "end",
            labels: { boxWidth: 10, usePointStyle: true, pointStyle: "circle", color: "#64748b" },
          },
          tooltip: {
            backgroundColor: "#0f172a",
            titleColor: "#f8fafc",
            bodyColor: "#e2e8f0",
            padding: 10,
            cornerRadius: 8,
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: "#94a3b8",
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: isHourly ? 12 : 8,
              callback: function (val) {
                var label = this.getLabelForValue(val);
                if (!label) return label;
                if (isHourly) return label;
                return label.length >= 10 ? label.slice(5) : label;
              },
            },
          },
          y: {
            position: "left",
            beginAtZero: true,
            grid: { color: "rgba(148, 163, 184, 0.18)" },
            ticks: { color: "#94a3b8", precision: 0 },
            title: { display: false },
          },
          y1: {
            position: "right",
            beginAtZero: true,
            grid: { drawOnChartArea: false },
            ticks: { color: "#94a3b8", precision: 0 },
          },
        },
        animation: { duration: 450 },
      },
    });
  }

  function renderFunnel(payload) {
    var host = el("an-funnel");
    if (!host) return;
    var steps = (payload && payload.steps) || [];
    var totalClicks = (payload && (payload.total_clicks || payload.baseline)) || 0;
    if (!steps.length) {
      host.innerHTML =
        '<div class="an-empty"><strong>' +
        escapeHtml(tr("analytics.funnel_empty_title")) +
        "</strong>" +
        escapeHtml(
          payload && payload.has_block_tracking === false
            ? tr("analytics.funnel_empty_restart")
            : tr("analytics.funnel_empty_period")
        ) +
        "</div>";
      return;
    }

    var maxPct = Math.max.apply(
      null,
      steps.map(function (s) {
        return Number(s.percentage) || 0;
      }).concat([1])
    );

    host.innerHTML =
      '<div class="an-funnel-sub" style="margin-bottom:10px">' +
      escapeHtml(tr("analytics.funnel_total", { n: formatNumber(totalClicks) })) +
      "</div>" +
      steps
        .map(function (s) {
          var pct = Number(s.percentage) || 0;
          var width = Math.max(2, (pct / maxPct) * 100);
          var name = s.name || s.label || s.block_id || "";
          var type = String(s.type || "").toLowerCase();
          var count = Number(s.count) || 0;
          var metricLine = tr("analytics.funnel_metric", { n: count, type: type });
          return (
            '<div class="an-funnel-row">' +
            '<div class="an-funnel-meta">' +
            '<div class="an-funnel-title" title="' +
            escapeAttr(name) +
            '">' +
            escapeHtml(name) +
            "</div>" +
            '<div class="an-funnel-sub">' +
            escapeHtml(metricLine) +
            "</div>" +
            '<div class="an-funnel-track"><div class="an-funnel-fill" style="width:' +
            width.toFixed(1) +
            '%"></div></div>' +
            "</div>" +
            '<div class="an-funnel-pct">' +
            pct.toFixed(1) +
            "%</div>" +
            "</div>"
          );
        })
        .join("");
  }

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(v) {
    return escapeHtml(v).replace(/'/g, "&#39;");
  }

  function clearDashboard() {
    ["kpi-subscribers", "kpi-active", "kpi-messages", "kpi-errors"].forEach(function (id) {
      if (el(id)) el(id).textContent = "—";
    });
    ["kpi-subscribers-trend", "kpi-active-trend", "kpi-messages-trend", "kpi-errors-trend"].forEach(
      function (id) {
        applyTrend(id, null, false);
      }
    );
    renderActivityChart([]);
    renderFunnel({ steps: [] });
  }

  function refreshAll() {
    var botId = selectedBotId();
    if (!botId) {
      clearDashboard();
      setStatus(tr("analytics.select_bot_hint"), "");
      return Promise.resolve();
    }
    if (state.loading) return Promise.resolve();
    state.loading = true;

    return Promise.all([
      fetch(apiUrl("overview"), { headers: state.headers }).then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      }),
      fetch(apiUrl("activity"), { headers: state.headers }).then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      }),
      fetch(apiUrl("funnel"), { headers: state.headers }).then(function (r) {
        return r.json().then(function (d) {
          return { ok: r.ok, data: d };
        });
      }),
    ])
      .then(function (results) {
        var overview = results[0];
        var activity = results[1];
        var funnel = results[2];
        if (!overview.ok) throw new Error((overview.data && overview.data.detail) || tr("analytics.load_error"));
        if (!activity.ok) throw new Error((activity.data && activity.data.detail) || tr("analytics.load_error"));
        if (!funnel.ok) throw new Error((funnel.data && funnel.data.detail) || tr("analytics.load_error"));
        renderOverview(overview.data);
        renderActivityChart(
          (activity.data && activity.data.series) || [],
          (activity.data && activity.data.granularity) || "day"
        );
        renderFunnel(funnel.data || {});
        setStatus("", "");
      })
      .catch(function (err) {
        setStatus(err.message || tr("analytics.load_error"), "error");
      })
      .finally(function () {
        state.loading = false;
      });
  }

  function setRange(range) {
    state.range = range || "30d";
    document.querySelectorAll(".an-range-btn").forEach(function (btn) {
      btn.classList.toggle("an-range-btn-active", btn.getAttribute("data-range") === state.range);
    });
    refreshAll();
  }

  function bindEvents() {
    var botSel = el("bot-select");
    if (botSel) {
      botSel.addEventListener("change", refreshAll);
    }
    document.querySelectorAll(".an-range-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setRange(btn.getAttribute("data-range"));
      });
    });
    el("an-refresh") && el("an-refresh").addEventListener("click", refreshAll);
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    state.headers = authHeaders();
    bindEvents();
    loadBots().then(refreshAll);
    document.addEventListener("botbuilder:langchange", function () {
      loadBots().then(refreshAll);
    });
  }

  global.AnalyticsView = { init: init, refresh: refreshAll };
})(typeof window !== "undefined" ? window : globalThis);
