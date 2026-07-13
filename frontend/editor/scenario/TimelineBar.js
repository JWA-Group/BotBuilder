/**
 * Time Machine — horizontal version timeline for the scenario canvas editor.
 */
(function (global) {
  "use strict";

  var rootEl = null;
  var sliderInput = null;
  var tooltipEl = null;
  var emptyEl = null;
  var active = false;
  var botId = null;
  var versions = [];
  var previewTs = null;
  var loadingTs = null;
  var onPreview = null;
  var onEmpty = null;
  var onClose = null;
  var onApply = null;
  var retentionHours = 12;
  var trackFillEl = null;
  var markersEl = null;

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function localeTag() {
    var lang = typeof global.getLang === "function" ? global.getLang() : "en";
    if (lang === "ru") return "ru-RU";
    if (lang === "es") return "es-ES";
    return "en-US";
  }

  function authHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json", "Accept-Language": "en" };
  }

  function apiBase() {
    return typeof getApiOrigin === "function"
      ? getApiOrigin()
      : global.location && global.location.origin
        ? global.location.origin
        : "http://127.0.0.1:8000";
  }

  function userId() {
    return typeof getUserId === "function" ? getUserId() : "1";
  }

  function versionKindLabel(kind) {
    return kind === "auto" ? tr("editor.history_kind_auto") : tr("editor.history_kind_save");
  }

  function formatRelative(ts) {
    var now = Math.floor(Date.now() / 1000);
    var diff = Math.max(0, now - ts);
    if (diff < 60) return tr("editor.time_just_now");
    if (diff < 3600) {
      return tr("editor.time_minutes_ago", { n: Math.floor(diff / 60) });
    }
    if (diff < 86400) {
      return tr("editor.time_hours_ago", { n: Math.floor(diff / 3600) });
    }
    var d = Math.floor(diff / 86400);
    if (d < 7) return tr("editor.time_days_ago", { n: d });
    return formatAbsolute(ts);
  }

  function formatAbsolute(ts) {
    return new Date(ts * 1000).toLocaleString(localeTag(), {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function ensureRoot() {
    if (rootEl) return rootEl;
    rootEl = document.createElement("div");
    rootEl.id = "timeline-bar-root";
    rootEl.className = "timeline-bar-root";
    rootEl.setAttribute("role", "region");
    rootEl.innerHTML =
      '<div class="timeline-bar-inner">' +
      '  <div class="timeline-bar-head">' +
      '    <div class="timeline-bar-head-left">' +
      '      <span class="timeline-bar-title" id="timeline-bar-title"></span>' +
      '      <span class="timeline-bar-sub" id="timeline-bar-sub"></span>' +
      "    </div>" +
      '    <div class="timeline-bar-head-actions">' +
      '      <button type="button" class="timeline-bar-apply" id="timeline-bar-apply"></button>' +
      '      <button type="button" class="timeline-bar-close" id="timeline-bar-close" aria-label="">✕</button>' +
      "    </div>" +
      "  </div>" +
      '  <div class="timeline-track-wrap">' +
      '    <div class="timeline-track-shell">' +
      '      <div class="timeline-slider-rail" aria-hidden="true"></div>' +
      '      <div class="timeline-track-fill" id="timeline-track-fill" aria-hidden="true"></div>' +
      '      <div class="timeline-version-markers" id="timeline-version-markers" aria-hidden="true"></div>' +
      '      <input type="range" class="timeline-slider" id="timeline-slider" min="0" max="0" value="0" step="1" />' +
      "    </div>" +
      '    <div class="timeline-tooltip" id="timeline-tooltip" hidden></div>' +
      "  </div>" +
      '  <p class="timeline-bar-empty" id="timeline-bar-empty" hidden></p>' +
      "</div>";
    document.body.appendChild(rootEl);
    sliderInput = rootEl.querySelector("#timeline-slider");
    trackFillEl = rootEl.querySelector("#timeline-track-fill");
    markersEl = rootEl.querySelector("#timeline-version-markers");
    tooltipEl = rootEl.querySelector("#timeline-tooltip");
    emptyEl = rootEl.querySelector("#timeline-bar-empty");

    sliderInput.addEventListener("input", onSliderInput);
    sliderInput.addEventListener("change", onSliderChange);
    sliderInput.addEventListener("mousemove", onSliderHover);
    sliderInput.addEventListener("touchstart", onSliderHover, { passive: true });

    var applyBtn = rootEl.querySelector("#timeline-bar-apply");
    if (applyBtn) {
      applyBtn.addEventListener("click", function () {
        if (typeof onApply === "function") onApply();
        else close();
      });
    }

    var closeBtn = rootEl.querySelector("#timeline-bar-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        if (typeof onClose === "function") onClose();
        else close();
      });
    }

    refreshLabels();
    return rootEl;
  }

  function retentionNote() {
    return tr("editor.history_retention_note", { hours: retentionHours });
  }

  function updateTrackFill(idx, total) {
    if (!trackFillEl) return;
    if (!total || total <= 0) {
      trackFillEl.style.width = "0";
      return;
    }
    if (total === 1) {
      trackFillEl.style.width = "calc(100% - 28px)";
      return;
    }
    var pct = Math.min(100, Math.max(0, (idx / (total - 1)) * 100));
    trackFillEl.style.width = "calc((100% - 28px) * " + pct / 100 + ")";
  }

  function markerLeftPercent(index, total) {
    if (total <= 1) return 100;
    return (index / (total - 1)) * 100;
  }

  function renderTrack() {
    if (!markersEl) return;
    markersEl.innerHTML = "";
    var n = versions.length;
    if (n === 0) return;

    versions.forEach(function (v, i) {
      var m = document.createElement("span");
      m.className = "timeline-marker" + (v.kind === "auto" ? " is-auto" : " is-user");
      m.style.left = markerLeftPercent(i, n) + "%";
      markersEl.appendChild(m);
    });
  }

  function refreshLabels() {
    if (!rootEl) return;
    rootEl.setAttribute("aria-label", tr("editor.history_title"));
    var titleEl = rootEl.querySelector("#timeline-bar-title");
    if (titleEl) titleEl.textContent = tr("editor.history_title");
    var applyBtn = rootEl.querySelector("#timeline-bar-apply");
    if (applyBtn) {
      applyBtn.textContent = tr("editor.history_apply");
      applyBtn.setAttribute("aria-label", tr("editor.history_apply_aria"));
      applyBtn.disabled = !previewTs;
    }
    var closeBtn = rootEl.querySelector("#timeline-bar-close");
    if (closeBtn) closeBtn.setAttribute("aria-label", tr("editor.history_close_aria"));
    if (sliderInput) sliderInput.setAttribute("aria-label", tr("editor.history_slider_aria"));
    if (emptyEl && emptyEl.hidden === false) {
      emptyEl.textContent = tr("editor.history_empty") + " " + retentionNote();
    }
    syncSlider();
  }

  function setSub(text, isError) {
    var el = rootEl && rootEl.querySelector("#timeline-bar-sub");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-error", !!isError);
  }

  function setEmptyVisible(on, message) {
    var wrap = rootEl && rootEl.querySelector(".timeline-track-wrap");
    if (emptyEl) {
      emptyEl.hidden = !on;
      emptyEl.textContent = message || tr("editor.history_empty");
    }
    if (wrap) wrap.classList.toggle("is-disabled", !!on);
    var applyBtn = rootEl && rootEl.querySelector("#timeline-bar-apply");
    if (applyBtn) applyBtn.disabled = on || !previewTs;
  }

  function syncSlider() {
    if (!sliderInput) return;
    var n = versions.length;
    sliderInput.min = "0";
    sliderInput.max = String(Math.max(0, n - 1));
    if (n === 0) {
      sliderInput.value = "0";
      sliderInput.disabled = true;
      sliderInput.classList.remove("timeline-slider--solo");
      setEmptyVisible(true);
      setSub("");
      updateTrackFill(0, 0);
      renderTrack();
      return;
    }
    sliderInput.classList.toggle("timeline-slider--solo", n === 1);
    sliderInput.disabled = n === 1;
    sliderInput.min = "0";
    sliderInput.max = String(Math.max(0, n - 1));
    setEmptyVisible(false);
    var idx = versions.findIndex(function (v) {
      return v.timestamp === previewTs;
    });
    if (idx < 0) idx = n - 1;
    sliderInput.value = String(idx);
    var v = versions[idx];
    if (v) {
      setSub(
        versionKindLabel(v.kind) +
          " · " +
          formatRelative(v.timestamp) +
          " · " +
          formatAbsolute(v.timestamp) +
          " (" +
          (idx + 1) +
          "/" +
          n +
          ") · " +
          retentionNote()
      );
    }
    updateTrackFill(idx, n);
    renderTrack();
    highlightActiveMarker(idx);
    var applyBtn = rootEl && rootEl.querySelector("#timeline-bar-apply");
    if (applyBtn) applyBtn.disabled = !previewTs;
  }

  function highlightActiveMarker(idx) {
    if (!markersEl) return;
    var marks = markersEl.querySelectorAll(".timeline-marker");
    for (var i = 0; i < marks.length; i++) {
      marks[i].classList.toggle("is-active", i === idx);
    }
  }

  function showTooltip(idx, clientX) {
    if (!tooltipEl || !rootEl) return;
    var v = versions[idx];
    if (!v) {
      tooltipEl.hidden = true;
      return;
    }
    tooltipEl.hidden = false;
    tooltipEl.textContent = versionKindLabel(v.kind) + " · " + formatRelative(v.timestamp);
    var wrap = rootEl.querySelector(".timeline-track-wrap");
    if (!wrap) return;
    var rect = wrap.getBoundingClientRect();
    var x =
      typeof clientX === "number"
        ? clientX - rect.left
        : (rect.width * idx) / Math.max(1, versions.length - 1);
    tooltipEl.style.left = Math.min(rect.width - 8, Math.max(8, x)) + "px";
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.hidden = true;
  }

  function historyBase() {
    return (
      apiBase() +
      "/api/scenario/history/" +
      encodeURIComponent(botId) +
      "?user_id=" +
      encodeURIComponent(userId())
    );
  }

  function historyUrl(suffix) {
    return (
      apiBase() +
      "/api/scenario/history/" +
      encodeURIComponent(botId) +
      suffix +
      "?user_id=" +
      encodeURIComponent(userId())
    );
  }

  function fetchHistory() {
    if (!botId) return Promise.resolve([]);
    setSub(tr("editor.history_loading"), false);
    setEmptyVisible(false);
    var url = historyBase();
    return fetch(url, { headers: authHeaders() })
      .then(function (res) {
        if (!res.ok) {
          return res.text().then(function (text) {
            throw new Error("HTTP " + res.status + (text ? ": " + text.slice(0, 120) : ""));
          });
        }
        return res.json();
      })
      .then(function (data) {
        if (data && data.retention_hours) retentionHours = Number(data.retention_hours) || 12;
        versions = (data && data.versions) || [];
        renderTrack();
        syncSlider();
        return versions;
      })
      .catch(function (err) {
        versions = [];
        renderTrack();
        setEmptyVisible(true, tr("editor.history_load_error"));
        setSub((err && err.message) || tr("editor.history_load_fail"), true);
        if (typeof console !== "undefined" && console.warn) {
          console.warn("TimelineBar: fetchHistory failed", err);
        }
        return [];
      });
  }

  function seedFromEditor() {
    if (!botId || typeof global.collectScenarioPayload !== "function") {
      return Promise.resolve([]);
    }
    var url = historyUrl("/snapshot");
    return fetch(url, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(global.collectScenarioPayload()),
    })
      .then(function (res) {
        if (!res.ok) return [];
        return fetchHistory();
      })
      .catch(function () {
        return [];
      });
  }

  function loadVersionAt(ts) {
    if (!botId || !ts || loadingTs === ts) return Promise.resolve();
    loadingTs = ts;
    setSub(tr("editor.history_loading_version"), false);
    var url = historyUrl("/" + encodeURIComponent(ts));
    return fetch(url, { headers: authHeaders() })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (payload) {
        previewTs = ts;
        if (typeof onPreview === "function") onPreview(payload, ts);
        syncSlider();
      })
      .catch(function (err) {
        setSub(tr("editor.history_version_fail"), true);
        if (typeof console !== "undefined" && console.warn) {
          console.warn("TimelineBar: load version failed", err);
        }
      })
      .finally(function () {
        loadingTs = null;
      });
  }

  function onSliderInput() {
    var idx = parseInt(sliderInput.value, 10) || 0;
    showTooltip(idx);
    var v = versions[idx];
    if (v && v.timestamp !== previewTs) loadVersionAt(v.timestamp);
  }

  function onSliderChange() {
    hideTooltip();
  }

  function onSliderHover(e) {
    if (!sliderInput || versions.length === 0) return;
    var rect = sliderInput.getBoundingClientRect();
    var ratio = (e.clientX - rect.left) / rect.width;
    ratio = Math.min(1, Math.max(0, ratio));
    var idx = Math.round(ratio * (versions.length - 1));
    showTooltip(idx, e.clientX);
  }

  function open(id, options) {
    options = options || {};
    botId = id;
    onPreview = options.onPreview || null;
    onEmpty = options.onEmpty || null;
    onClose = options.onClose || null;
    onApply = options.onApply || null;
    ensureRoot();
    refreshLabels();
    active = true;
    rootEl.classList.add("is-visible");
    document.body.classList.add("timeline-bar-active");
    return fetchHistory()
      .then(function (list) {
        if (list.length === 0) {
          return seedFromEditor();
        }
        return list;
      })
      .then(function (list) {
        if (list.length === 0) {
          if (typeof onEmpty === "function") onEmpty();
          return list;
        }
        var latest = list[list.length - 1];
        return loadVersionAt(latest.timestamp).then(function () {
          return list;
        });
      });
  }

  function close() {
    active = false;
    previewTs = null;
    if (rootEl) rootEl.classList.remove("is-visible");
    document.body.classList.remove("timeline-bar-active");
  }

  function toggle(id, options) {
    if (active) {
      close();
      return Promise.resolve(false);
    }
    return open(id, options).then(function () {
      return true;
    });
  }

  function jumpToVersion(ts) {
    if (!ts || !versions.length) return Promise.resolve();
    var idx = versions.findIndex(function (v) {
      return v.timestamp === ts;
    });
    if (idx < 0) idx = versions.length - 1;
    if (sliderInput) sliderInput.value = String(idx);
    return loadVersionAt(versions[idx].timestamp);
  }

  function refresh() {
    if (!active || !botId) return Promise.resolve();
    return fetchHistory().then(function (list) {
      if (list.length && previewTs) {
        var still = list.some(function (v) {
          return v.timestamp === previewTs;
        });
        if (!still && list.length) return loadVersionAt(list[list.length - 1].timestamp);
      }
      return list;
    });
  }

  global.TimelineBar = {
    open: open,
    close: close,
    toggle: toggle,
    refresh: refresh,
    refreshLabels: refreshLabels,
    jumpToVersion: jumpToVersion,
    isActive: function () {
      return active;
    },
    getPreviewTimestamp: function () {
      return previewTs;
    },
    getVersions: function () {
      return versions.slice();
    },
    formatRelative: formatRelative,
    formatAbsolute: formatAbsolute,
  };
})(typeof window !== "undefined" ? window : globalThis);
