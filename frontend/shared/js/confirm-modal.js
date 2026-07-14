/**
 * AppConfirm — themed delete/confirm dialog (same look as bots delete modal).
 */
(function (global) {
  "use strict";

  var TRASH_ICON =
    '<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M3 6h18"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M8 6V4h8v2"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M19 6l-1 14H6L5 6"/>' +
    '<path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M10 11v6M14 11v6"/>' +
    "</svg>";

  var pendingResolve = null;

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function ensureModal() {
    var modal = document.getElementById("app-confirm-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "app-confirm-modal";
    modal.className = "app-confirm-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML =
      '<div class="app-confirm-backdrop" data-dismiss="true"></div>' +
      '<div class="app-confirm-panel" role="document">' +
      '<div class="app-confirm-icon">' +
      TRASH_ICON +
      "</div>" +
      '<h2 class="app-confirm-title"></h2>' +
      '<p class="app-confirm-text"></p>' +
      '<p class="app-confirm-detail" hidden></p>' +
      '<div class="app-confirm-actions">' +
      '<button type="button" class="app-confirm-btn app-confirm-cancel" data-dismiss="true"></button>' +
      '<button type="button" class="app-confirm-btn app-confirm-danger"></button>' +
      "</div></div>";
    document.body.appendChild(modal);

    modal.addEventListener("click", function (ev) {
      if (ev.target && ev.target.getAttribute("data-dismiss") === "true") {
        close(false);
      }
    });
    modal.querySelector(".app-confirm-danger").addEventListener("click", function () {
      close(true);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && modal && !modal.hidden) close(false);
    });
    return modal;
  }

  function close(confirmed) {
    var modal = document.getElementById("app-confirm-modal");
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("app-confirm-open");
    if (pendingResolve) {
      var fn = pendingResolve;
      pendingResolve = null;
      fn(!!confirmed);
    }
  }

  function show(options) {
    options = options || {};
    var modal = ensureModal();
    var title = options.title || tr("common.confirm_delete_title");
    var message = options.message || tr("common.confirm_delete_body");
    var detail = options.detail || "";
    var cancelLabel = options.cancelLabel || tr("common.cancel");
    var confirmLabel = options.confirmLabel || tr("common.delete");

    modal.querySelector(".app-confirm-title").textContent = title;
    modal.querySelector(".app-confirm-text").textContent = message;
    var detailEl = modal.querySelector(".app-confirm-detail");
    if (detailEl) {
      if (detail) {
        detailEl.textContent = detail;
        detailEl.hidden = false;
      } else {
        detailEl.textContent = "";
        detailEl.hidden = true;
      }
    }
    modal.querySelector(".app-confirm-cancel").textContent = cancelLabel;
    modal.querySelector(".app-confirm-danger").textContent = confirmLabel;

    return new Promise(function (resolve) {
      pendingResolve = resolve;
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("app-confirm-open");
      var confirmBtn = modal.querySelector(".app-confirm-danger");
      if (confirmBtn) confirmBtn.focus();
    });
  }

  function danger(options) {
    return show(options);
  }

  global.AppConfirm = { show: show, danger: danger };
})(typeof window !== "undefined" ? window : globalThis);
