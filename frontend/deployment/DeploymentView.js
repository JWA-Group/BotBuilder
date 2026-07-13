/**
 * DeploymentView — ZIP export + SSH auto-deploy with SSE console.
 */
(function (global) {
  "use strict";

  var state = {
    apiOrigin: "",
    botId: "",
    deploying: false,
    exportBusy: false,
    eventSource: null,
    abortStream: null,
    currentJobId: "",
    logDownloadPath: "",
    consoleText: "",
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

  function selectedBotId() {
    var sel = el("dep-bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function updateActionButtons() {
    var hasBot = !!selectedBotId();
    var exportBtn = el("dep-export-btn");
    var launchBtn = el("dep-launch-btn");
    if (exportBtn) exportBtn.disabled = !hasBot || state.exportBusy || state.deploying;
    if (launchBtn) launchBtn.disabled = !hasBot || state.deploying || state.exportBusy;
    var logDl = el("dep-log-download-btn");
    var logCp = el("dep-log-copy-btn");
    if (logDl) logDl.disabled = !hasBot;
    if (logCp) logCp.disabled = !hasBot && !state.consoleText;
  }

  function appendConsole(line, kind) {
    var box = el("dep-console");
    if (!box) return;
    state.consoleText += line + "\n";
    var span = document.createElement("span");
    span.className =
      "dep-console-line" +
      (kind === "ok" ? " dep-console-line-ok" : kind === "err" ? " dep-console-line-err" : "");
    span.textContent = line + "\n";
    box.appendChild(span);
    box.scrollTop = box.scrollHeight;
  }

  function setLogActionsEnabled(enabled) {
    var dl = el("dep-log-download-btn");
    var cp = el("dep-log-copy-btn");
    if (dl) dl.disabled = !enabled;
    if (cp) cp.disabled = !enabled;
  }

  function showLogPath(text) {
    var node = el("dep-log-path");
    if (!node) return;
    if (!text) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = text;
  }

  function downloadFullLog() {
    var botId = selectedBotId();
    if (!botId) return;
    var urls = [];
    if (state.currentJobId) {
      urls.push(
        state.apiOrigin +
          "/api/projects/" +
          encodeURIComponent(botId) +
          "/deploy/logs/" +
          encodeURIComponent(state.currentJobId)
      );
    }
    urls.push(
      state.apiOrigin +
        "/api/projects/" +
        encodeURIComponent(botId) +
        "/deploy/logs/latest"
    );

    function tryNext(i) {
      if (i >= urls.length) {
        appendConsole(tr("deployment.log_not_found"), "err");
        return;
      }
      fetch(urls[i], { headers: authHeaders() })
        .then(function (res) {
          if (!res.ok) {
            tryNext(i + 1);
            return null;
          }
          return res.blob();
        })
        .then(function (blob) {
          if (!blob) return;
          triggerDownload(blob, "deploy_bot_" + botId + ".log");
        })
        .catch(function () {
          tryNext(i + 1);
        });
    }
    tryNext(0);
  }

  function copyConsoleLog() {
    var text = state.consoleText || (el("dep-console") && el("dep-console").textContent) || "";
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        appendConsole(tr("deployment.log_copied"), "ok");
      });
      return;
    }
    appendConsole(text, null);
  }

  function clearConsole() {
    var box = el("dep-console");
    if (box) box.textContent = "";
    state.consoleText = "";
    state.currentJobId = "";
    state.logDownloadPath = "";
    setLogActionsEnabled(false);
    showLogPath("");
    var checklist = el("dep-checklist");
    if (checklist) {
      checklist.hidden = true;
      checklist.innerHTML = "";
    }
  }

  function showSuccessChecklist() {
    var checklist = el("dep-checklist");
    if (!checklist) return;
    checklist.hidden = false;
    checklist.innerHTML =
      "<h3>" + escapeHtml(tr("deployment.success_title")) + "</h3>" +
      "<ul>" +
      "<li>" + escapeHtml(tr("deployment.success_1")) + "</li>" +
      "<li>" + escapeHtml(tr("deployment.success_2")) + "</li>" +
      "<li>" + escapeHtml(tr("deployment.success_3", { id: selectedBotId() })) + "</li>" +
      "<li>" + escapeHtml(tr("deployment.success_4")) + "</li>" +
      "</ul>";
  }

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function parseResponse(res) {
    var ct = (res.headers.get("content-type") || "").toLowerCase();
    if (ct.indexOf("application/json") !== -1) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    }
    return res.blob().then(function (blob) {
      return { ok: res.ok, status: res.status, data: blob };
    });
  }

  function triggerDownload(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      if (a.parentNode) a.parentNode.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  }

  function exportZip() {
    var botId = selectedBotId();
    if (!botId || state.exportBusy) return;
    state.exportBusy = true;
    updateActionButtons();
    clearConsole();
    appendConsole(tr("deployment.building", { id: botId }));

    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(botId) + "/export/zip", {
      headers: authHeaders(),
    })
      .then(parseResponse)
      .then(function (result) {
        if (!result.ok) {
          var detail =
            result.data && result.data.detail
              ? result.data.detail
              : tr("deployment.export_error") + " (" + result.status + ")";
          throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
        var filename = "bot_" + botId + "_deploy.zip";
        triggerDownload(result.data, filename);
        appendConsole(tr("deployment.archive_saved", { name: filename }), "ok");
      })
      .catch(function (err) {
        appendConsole("✗ " + (err.message || tr("deployment.export_error")), "err");
      })
      .finally(function () {
        state.exportBusy = false;
        updateActionButtons();
      });
  }

  function closeStream() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
    if (state.abortStream) {
      state.abortStream();
      state.abortStream = null;
    }
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
            /* ignore malformed */
          }
        }
      });
    });
    return rest;
  }

  function streamDeployLogs(botId, jobId) {
    closeStream();
    var url =
      state.apiOrigin +
      "/api/projects/" +
      encodeURIComponent(botId) +
      "/deploy/ssh/stream/" +
      encodeURIComponent(jobId);

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    state.abortStream = function () {
      if (controller) controller.abort();
    };

    fetch(url, {
      headers: authHeaders(),
      signal: controller ? controller.signal : undefined,
    })
      .then(function (res) {
        if (!res.ok || !res.body) throw new Error("Не удалось подключиться к потоку логов");
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = "";

        function readNext() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buf += decoder.decode(chunk.value, { stream: true });
            buf = consumeSseChunk(buf, handleStreamEvent);
            return readNext();
          });
        }
        return readNext();
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") return;
        appendConsole("✗ " + (err.message || "Ошибка потока"), "err");
        state.deploying = false;
        updateActionButtons();
      });
  }

  function handleStreamEvent(data) {
    if (!data || !data.type) return;
    if (data.type === "log" && data.line) {
      var kind = null;
      if (data.line.indexOf("✓") === 0 || data.line.indexOf("✔") === 0) kind = "ok";
      if (data.line.indexOf("✗") === 0 || data.line.indexOf("ERROR") >= 0) kind = "err";
      appendConsole(data.line, kind);
      return;
    }
    if (data.type === "done") {
      state.deploying = false;
      updateActionButtons();
      closeStream();
      if (data.log_download) state.logDownloadPath = data.log_download;
      setLogActionsEnabled(!!state.currentJobId);
      if (data.success) {
        appendConsole(tr("deployment.done"), "ok");
        showSuccessChecklist();
      } else {
        appendConsole("✗ " + (data.error || tr("deployment.failed")), "err");
        appendConsole(tr("deployment.download_log_hint"), null);
      }
    }
  }

  function launchDeploy(ev) {
    if (ev) ev.preventDefault();
    var botId = selectedBotId();
    if (!botId || state.deploying) return;

    var host = (el("dep-host") && el("dep-host").value || "").trim();
    var username = (el("dep-username") && el("dep-username").value || "").trim();
    var password = el("dep-password") ? el("dep-password").value : "";
    var sshKey = el("dep-key") ? el("dep-key").value.trim() : "";
    var port = parseInt(el("dep-port") && el("dep-port").value, 10) || 22;

    if (!host || !username) {
      appendConsole(tr("deployment.specify_host"), "err");
      return;
    }
    if (!password && !sshKey) {
      appendConsole(tr("deployment.specify_auth"), "err");
      return;
    }

    state.deploying = true;
    updateActionButtons();
    clearConsole();
    appendConsole(tr("deployment.launching", { host: host }));

    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(botId) + "/deploy/ssh", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        host: host,
        username: username,
        password: password || null,
        ssh_private_key: sshKey || null,
        port: port,
      }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          var detail = result.data && result.data.detail ? result.data.detail : tr("deployment.failed");
          throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        }
        var jobId = result.data && result.data.job_id;
        if (!jobId) throw new Error("Сервер не вернул job_id");
        state.currentJobId = jobId;
        setLogActionsEnabled(true);
        showLogPath(
          "Полный лог: projects/deploy_logs/" +
            jobId +
            ".log  (или кнопка «Скачать полный лог»)"
        );
        streamDeployLogs(botId, jobId);
      })
      .catch(function (err) {
        appendConsole("✗ " + (err.message || tr("deployment.failed")), "err");
        state.deploying = false;
        updateActionButtons();
      });
  }

  function loadBots() {
    var select = el("dep-bot-select");
    if (!select) return Promise.resolve();

    var userId = typeof global.getUserId === "function" ? global.getUserId() : "1";
    return fetch(state.apiOrigin + "/api/analytics/bots?user_id=" + encodeURIComponent(userId), {
      headers: authHeaders(),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        select.innerHTML = '<option value="">' + tr("deployment.bot_select") + "</option>";
        var bots = (result.data && result.data.bots) || result.data || [];
        if (!Array.isArray(bots)) bots = [];
        bots.forEach(function (bot) {
          var opt = document.createElement("option");
          opt.value = String(bot.id);
          opt.textContent = (bot.name || "Bot") + " (#" + bot.id + ")";
          select.appendChild(opt);
        });
      })
      .catch(function () {
        /* keep empty select */
      });
  }

  function bindEvents() {
    var botSel = el("dep-bot-select");
    if (botSel) {
      botSel.addEventListener("change", function () {
        state.botId = selectedBotId();
        updateActionButtons();
      });
    }

    var exportBtn = el("dep-export-btn");
    if (exportBtn) exportBtn.addEventListener("click", exportZip);

    var form = el("dep-ssh-form");
    if (form) form.addEventListener("submit", launchDeploy);

    var logDl = el("dep-log-download-btn");
    if (logDl) logDl.addEventListener("click", downloadFullLog);
    var logCp = el("dep-log-copy-btn");
    if (logCp) logCp.addEventListener("click", copyConsoleLog);
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    bindEvents();
    loadBots().then(updateActionButtons);
    document.addEventListener("botbuilder:langchange", function () {
      loadBots().then(updateActionButtons);
    });
  }

  global.DeploymentView = { init: init };
})(typeof window !== "undefined" ? window : globalThis);
