function escapeHtml(s) {
  if (s == null) return "";
  var div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function tr(key, params) {
  return typeof t === "function" ? t(key, params) : key;
}

function visibleTokenPart(token) {
  if (!token) return "";
  var len = token.length;
  if (len <= 4) return "";
  var showLen = Math.max(4, Math.ceil(len / 3));
  return token.slice(0, showLen);
}

function maskToken(token) {
  if (!token) return "—";
  var visible = visibleTokenPart(token);
  return visible ? visible + "••••••" : "••••";
}

function renderTokenValue(el, token, revealed) {
  if (!el) return;
  if (revealed) {
    el.textContent = token || "—";
    return;
  }
  var visible = visibleTokenPart(token);
  if (!visible) {
    el.innerHTML = '<span class="bot-api-masked">••••</span>';
    return;
  }
  el.innerHTML =
    '<span class="bot-api-visible-part">' +
    escapeHtml(visible) +
    '</span><span class="bot-api-masked">••••••</span>';
}

var deleteModalState = null;

function closeDeleteModal(confirmed) {
  var modal = document.getElementById("delete-bot-modal");
  if (!modal) return;
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("bots-modal-open");
  if (deleteModalState && deleteModalState.resolve) {
    deleteModalState.resolve(!!confirmed);
    deleteModalState = null;
  }
}

function confirmDeleteBot(botName) {
  return new Promise(function (resolve) {
    var modal = document.getElementById("delete-bot-modal");
    if (!modal) {
      resolve(window.confirm(tr("bots.delete_confirm_title") + "\n" + tr("bots.delete_confirm_body", { name: botName })));
      return;
    }
    var titleEl = modal.querySelector(".bots-modal-title");
    var textEl = modal.querySelector(".bots-modal-text");
    var nameEl = modal.querySelector(".bots-modal-bot-name");
    var cancelBtn = modal.querySelector(".bots-modal-cancel");
    var confirmBtn = modal.querySelector(".bots-modal-confirm");
    if (titleEl) titleEl.textContent = tr("bots.delete_confirm_title");
    if (textEl) textEl.textContent = tr("bots.delete_confirm_body");
    if (nameEl) nameEl.textContent = botName || "—";
    if (cancelBtn) cancelBtn.textContent = tr("common.cancel");
    if (confirmBtn) confirmBtn.textContent = tr("bots.delete");
    deleteModalState = { resolve: resolve };
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("bots-modal-open");
    if (confirmBtn) confirmBtn.focus();
  });
}

function apiToggleButtonHtml() {
  return (
    '<button type="button" class="bot-api-toggle" aria-pressed="false" aria-label="' +
    escapeHtml(tr("bots.token_show")) +
    '">' +
    '<span class="bot-api-icon bot-api-icon-hidden" aria-hidden="true">' +
    '<svg viewBox="0 0 24 24" focusable="false">' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M3 3l18 18"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M10.58 10.58A3 3 0 0 0 12 15a3 3 0 0 0 2.83-1.94"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M9.88 5.09A10.94 10.94 0 0 1 12 5c7 0 11 8 11 8a18.45 18.45 0 0 1-2.16 3.19"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M6.61 6.61A18.48 18.48 0 0 0 1 12s4 8 11 8a11.05 11.05 0 0 0 5.06-1.22"/>' +
    "</svg></span>" +
    '<span class="bot-api-icon bot-api-icon-visible" aria-hidden="true">' +
    '<svg viewBox="0 0 24 24" focusable="false">' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>' +
    '<circle fill="none" stroke="currentColor" stroke-width="1.75" cx="12" cy="12" r="3"/>' +
    "</svg></span></button>"
  );
}

function requestHeaders() {
  return typeof jsonApiHeaders === "function"
    ? jsonApiHeaders()
    : { "Content-Type": "application/json", "Accept-Language": "en" };
}

document.addEventListener("DOMContentLoaded", async () => {
  const user_id = typeof getUserId === "function" ? getUserId() : "1";

  var deleteModal = document.getElementById("delete-bot-modal");
  if (deleteModal) {
    deleteModal.querySelectorAll("[data-dismiss]").forEach(function (el) {
      el.addEventListener("click", function () {
        closeDeleteModal(false);
      });
    });
    var deleteConfirmBtn = deleteModal.querySelector(".bots-modal-confirm");
    if (deleteConfirmBtn) {
      deleteConfirmBtn.addEventListener("click", function () {
        closeDeleteModal(true);
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && deleteModalState && !deleteModal.hidden) {
        closeDeleteModal(false);
      }
    });
  }

  var platformHint = document.getElementById("platform-hint");
  var nameInput = document.getElementById("bot-name");
  var tokenInput = document.getElementById("bot-api-token");

  if (platformHint) {
    var hint = tr("bots.hint_telegram");
    platformHint.innerHTML = hint.replace(
      "BotFather",
      '<a href="https://t.me/BotFather" target="_blank" rel="noopener">BotFather</a>'
    );
  }
  if (nameInput) nameInput.placeholder = tr("bots.name_placeholder");
  if (tokenInput) tokenInput.placeholder = tr("bots.token_placeholder");

  var addForm = document.getElementById("add-bot-form");
  var addError = document.getElementById("add-bot-error");
  if (addForm) {
    addForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      if (addError) addError.classList.remove("visible");
      var name = document.getElementById("bot-name").value.trim();
      var api_token = document.getElementById("bot-api-token").value.trim();
      var platform = "telegram";
      if (!name || !api_token) {
        if (addError) {
          addError.textContent = tr("error.required_field");
          addError.classList.add("visible");
        }
        return;
      }
      var btn = addForm.querySelector(".btn-primary");
      if (btn) btn.disabled = true;
      try {
        var res = await fetch("/api/bots/create", {
          method: "POST",
          headers: requestHeaders(),
          body: JSON.stringify({
            name: name,
            api_token: api_token,
            user_id: parseInt(user_id, 10),
            platform: platform,
          }),
        });
        var data = res.ok ? await res.json() : await res.json().catch(function () { return {}; });
        if (res.ok) {
          document.getElementById("bot-name").value = "";
          document.getElementById("bot-api-token").value = "";
          window.location.reload();
          return;
        }
        if (addError) {
          addError.textContent = data.detail || tr("error.generic");
          addError.classList.add("visible");
        }
      } catch (err) {
        if (addError) {
          addError.textContent = tr("error.network");
          addError.classList.add("visible");
        }
      }
      if (btn) btn.disabled = false;
    });
  }

  const container = document.getElementById("bots-list");

  async function refreshBotStatus(botId) {
    try {
      const r = await fetch("/api/bots/status/" + botId, { headers: requestHeaders() });
      if (!r.ok) return;
      const data = await r.json();
      const card = document.querySelector(".bot-card[data-bot-id=\"" + botId + "\"]");
      if (!card) return;
      const badge = card.querySelector(".bot-status-badge");
      if (badge) {
        badge.textContent = data.running ? tr("bots.status_running") : tr("bots.status_stopped");
        badge.className = "bot-status-badge " + (data.running ? "status-running" : "status-stopped");
      }
    } catch (e) {}
  }

  async function loadBots() {
    if (container) container.textContent = tr("bots.loading");

    const res = await fetch(`/api/bots/my?user_id=${user_id}`, { headers: requestHeaders() });

    if (res.ok) {
      const bots = await res.json();
      if (bots.length === 0) {
        container.innerHTML = "<p>" + escapeHtml(tr("bots.empty")) + "</p>";
      } else {
        const html = bots
          .map(function (bot) {
            var plat = "telegram";
            var token = bot.api_token || "";
            return (
              '<div class="bot-card" data-bot-id="' +
              bot.id +
              '" data-bot-name="' +
              escapeHtml(bot.name) +
              '" data-platform="telegram">' +
              '<div class="bot-card-header">' +
              "<h3>" +
              escapeHtml(bot.name) +
              "</h3>" +
              '<div class="bot-card-badges">' +
              '<span class="bot-platform-badge bot-platform-telegram">' +
              escapeHtml(tr("bots.platform_telegram")) +
              "</span>" +
              '<span class="bot-status-badge status-stopped" data-bot-id="' +
              bot.id +
              '">—</span>' +
              "</div></div>" +
              '<div class="bot-api-row">' +
              '<span class="bot-api-label">' +
              escapeHtml(tr("bots.api_label")) +
              ":</span>" +
              '<span class="bot-api-value" data-token="' +
              escapeHtml(token) +
              '"></span>' +
              apiToggleButtonHtml() +
              "</div>" +
              '<div class="actions">' +
              '<div class="actions-primary">' +
              '<button class="start-btn" type="button">' +
              escapeHtml(tr("bots.run")) +
              "</button>" +
              '<button class="stop-btn" type="button">' +
              escapeHtml(tr("bots.stop")) +
              "</button>" +
              '<button class="delete-btn" type="button">' +
              escapeHtml(tr("bots.delete")) +
              "</button>" +
              "</div>" +
              '<a class="btn-scenario" href="/editor/scenario/index.html?bot_id=' +
              bot.id +
              '">' +
              escapeHtml(tr("bots.scenario_editor")) +
              "</a>" +
              "</div></div>"
            );
          })
          .join("");
        container.innerHTML = html;

        document.querySelectorAll(".bot-api-value").forEach(function (val) {
          renderTokenValue(val, val.getAttribute("data-token") || "", false);
        });

        bots.forEach(function (bot) {
          refreshBotStatus(bot.id);
        });

        document.querySelectorAll(".start-btn").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const card = btn.closest(".bot-card");
            const botId = card.dataset.botId;
            try {
              const r = await fetch("/api/bots/start/" + botId, {
                method: "POST",
                headers: requestHeaders(),
              });
              const data = await r.json().catch(function () { return {}; });
              await refreshBotStatus(botId);
              if (!r.ok) {
                var msg = data.detail || data.status || r.status;
                if (typeof msg === "object") msg = JSON.stringify(msg);
                alert(tr("bots.start_error") + ": " + msg);
              }
            } catch (err) {
              alert(tr("error.network"));
            }
          });
        });

        document.querySelectorAll(".stop-btn").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const card = btn.closest(".bot-card");
            const botId = card.dataset.botId;
            try {
              const r = await fetch("/api/bots/stop/" + botId, {
                method: "POST",
                headers: requestHeaders(),
              });
              await refreshBotStatus(botId);
              if (!r.ok) {
                const data = await r.json().catch(function () { return {}; });
                alert(tr("error.generic") + ": " + (data.detail || data.status || r.status));
              }
            } catch (err) {
              alert(tr("error.network"));
            }
          });
        });

        document.querySelectorAll(".bot-api-toggle").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var row = btn.closest(".bot-api-row");
            var val = row ? row.querySelector(".bot-api-value") : null;
            if (!val) return;
            var token = val.getAttribute("data-token") || "";
            var revealed = btn.getAttribute("aria-pressed") === "true";
            if (revealed) {
              renderTokenValue(val, token, false);
              btn.setAttribute("aria-pressed", "false");
              btn.setAttribute("aria-label", tr("bots.token_show"));
              btn.classList.remove("revealed");
            } else {
              renderTokenValue(val, token, true);
              btn.setAttribute("aria-pressed", "true");
              btn.setAttribute("aria-label", tr("bots.token_hide"));
              btn.classList.add("revealed");
            }
          });
        });

        document.querySelectorAll(".delete-btn").forEach(function (btn) {
          btn.addEventListener("click", async function () {
            var card = btn.closest(".bot-card");
            if (!card) return;
            var botId = card.dataset.botId;
            var botName = card.dataset.botName || "";
            if (!(await confirmDeleteBot(botName))) return;
            btn.disabled = true;
            try {
              await fetch("/api/bots/stop/" + botId, {
                method: "POST",
                headers: requestHeaders(),
              });
              var r = await fetch("/api/bots/" + botId + "?user_id=" + user_id, {
                method: "DELETE",
                headers: requestHeaders(),
              });
              if (r.ok) {
                card.remove();
                if (!document.querySelector(".bot-card") && container) {
                  container.innerHTML = "<p>" + escapeHtml(tr("bots.empty")) + "</p>";
                }
                return;
              }
              var data = await r.json().catch(function () { return {}; });
              alert(tr("bots.delete_error") + ": " + (data.detail || r.status));
            } catch (err) {
              alert(tr("error.network"));
            }
            btn.disabled = false;
          });
        });
      }
    } else {
      container.innerHTML =
        "<p style='color:red;'>" + escapeHtml(tr("bots.load_error")) + "</p>";
    }
  }

  await loadBots();

  document.addEventListener("botbuilder:langchange", function () {
    updatePlatformUi();
    loadBots();
  });
});
