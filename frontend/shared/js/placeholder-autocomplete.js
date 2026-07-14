/**
 * {{ placeholder autocomplete for scenario editor text fields.
 */
(function (global) {
  "use strict";

  var cache = { botId: null, items: [], loadedAt: 0 };

  function tr(key) {
    return typeof global.t === "function" ? global.t(key) : key;
  }

  function apiBase() {
    return typeof global.getApiOrigin === "function"
      ? global.getApiOrigin()
      : global.location && global.location.origin
        ? global.location.origin.replace(/\/$/, "")
        : "http://127.0.0.1:8000";
  }

  function authHeaders() {
    return typeof global.jsonApiHeaders === "function"
      ? global.jsonApiHeaders()
      : { "Content-Type": "application/json" };
  }

  function fetchPlaceholders(botId, callback) {
    if (!botId) {
      callback(defaultPlaceholders());
      return;
    }
    var now = Date.now();
    if (cache.botId === botId && cache.items.length && now - cache.loadedAt < 60000) {
      callback(cache.items);
      return;
    }
    fetch(apiBase() + "/api/analytics/" + encodeURIComponent(botId) + "/user-data-schema", {
      headers: authHeaders(),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var items = (data && data.placeholders) || [];
        if (!items.length) items = defaultPlaceholders();
        cache.botId = botId;
        cache.items = items;
        cache.loadedAt = now;
        callback(items);
      })
      .catch(function () {
        callback(defaultPlaceholders());
      });
  }

  function defaultPlaceholders() {
    return [
      "user.balance",
      "user.tg_user_id",
      "user.tg_user_name",
      "user.tg_user_date",
      "bot.item_price",
      "issued.email",
      "issued.pass",
      "issued.key",
      "now_msk",
    ];
  }

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getPrefixAtCaret(text, caret) {
    var before = text.slice(0, caret);
    var open = before.lastIndexOf("{{");
    if (open < 0) return null;
    var inner = before.slice(open + 2);
    if (inner.indexOf("}}") >= 0) return null;
    if (/\s/.test(inner)) return null;
    return { openIndex: open, partial: inner, replaceFrom: open + 2, replaceTo: caret };
  }

  function filterItems(items, partial) {
    var q = (partial || "").toLowerCase();
    if (!q) return items.slice(0, 20);
    return items
      .filter(function (item) {
        return item.toLowerCase().indexOf(q) >= 0;
      })
      .slice(0, 20);
  }

  function positionDropdown(dropdown, input) {
    var rect = input.getBoundingClientRect();
    dropdown.style.left = rect.left + "px";
    dropdown.style.top = rect.bottom + 4 + "px";
    dropdown.style.minWidth = Math.max(rect.width, 220) + "px";
  }

  function attach(input, options) {
    if (!input || input.dataset.placeholderAcBound === "1") return;
    input.dataset.placeholderAcBound = "1";
    options = options || {};

    var dropdown = document.createElement("div");
    dropdown.className = "placeholder-ac-dropdown";
    dropdown.hidden = true;
    document.body.appendChild(dropdown);

    var state = { active: -1, matches: [], prefix: null, items: [] };

    function hide() {
      dropdown.hidden = true;
      dropdown.innerHTML = "";
      state.active = -1;
      state.matches = [];
      state.prefix = null;
    }

    function insertSelection(value) {
      if (!state.prefix) return;
      var text = input.value || "";
      var before = text.slice(0, state.prefix.replaceFrom);
      var after = text.slice(state.prefix.replaceTo);
      var token = value;
      input.value = before + token + "}}" + after;
      var caret = (before + token + "}}").length;
      if (typeof input.setSelectionRange === "function") {
        input.setSelectionRange(caret, caret);
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      hide();
    }

    function renderDropdown() {
      if (!state.matches.length) {
        hide();
        return;
      }
      dropdown.innerHTML = state.matches
        .map(function (item, idx) {
          return (
            '<button type="button" class="placeholder-ac-option' +
            (idx === state.active ? " active" : "") +
            '" data-idx="' +
            idx +
            '">' +
            escapeHtml("{{" + item + "}}") +
            "</button>"
          );
        })
        .join("");
      dropdown.hidden = false;
      positionDropdown(dropdown, input);
      dropdown.querySelectorAll(".placeholder-ac-option").forEach(function (btn) {
        btn.onclick = function (ev) {
          ev.preventDefault();
          var ix = parseInt(btn.getAttribute("data-idx"), 10);
          if (state.matches[ix]) insertSelection(state.matches[ix]);
        };
      });
    }

    function refresh() {
      var caret = input.selectionStart == null ? (input.value || "").length : input.selectionStart;
      var text = input.value || "";
      state.prefix = getPrefixAtCaret(text, caret);
      if (!state.prefix) {
        hide();
        return;
      }
      if (text.slice(caret, caret + 2) === "}}") {
        hide();
        return;
      }
      state.matches = filterItems(state.items, state.prefix.partial);
      state.active = state.matches.length ? 0 : -1;
      renderDropdown();
    }

    fetchPlaceholders(options.botId, function (items) {
      state.items = items;
      refresh();
    });

    input.addEventListener("input", refresh);
    input.addEventListener("click", refresh);
    input.addEventListener("keyup", function (ev) {
      if (ev.key === "Escape") hide();
      else refresh();
    });
    input.addEventListener("keydown", function (ev) {
      if (dropdown.hidden) return;
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        if (!state.matches.length) return;
        state.active = (state.active + 1) % state.matches.length;
        renderDropdown();
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        if (!state.matches.length) return;
        state.active = (state.active - 1 + state.matches.length) % state.matches.length;
        renderDropdown();
      } else if (ev.key === "Enter" && state.active >= 0 && state.matches[state.active]) {
        ev.preventDefault();
        insertSelection(state.matches[state.active]);
      } else if (ev.key === " " && state.prefix) {
        hide();
      }
    });
    input.addEventListener("blur", function () {
      setTimeout(hide, 150);
    });
    window.addEventListener(
      "scroll",
      function () {
        if (!dropdown.hidden) positionDropdown(dropdown, input);
      },
      true
    );
    document.addEventListener("botbuilder:langchange", function () {
      cache.loadedAt = 0;
    });
  }

  function scanRoot(root, botId) {
    if (!root) return;
    root.querySelectorAll("input.editor-field, textarea.editor-field").forEach(function (el) {
      attach(el, { botId: botId });
    });
  }

  global.PlaceholderAutocomplete = {
    attach: attach,
    scanRoot: scanRoot,
    invalidateCache: function () {
      cache.loadedAt = 0;
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
