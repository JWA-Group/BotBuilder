/**
 * BroadcastView — rich-text composer, audience filters, Telegram preview, async send.
 */
(function (global) {
  "use strict";

  var IMAGE_EXT = /\.(jpe?g|png|gif|webp)$/i;

  var state = {
    apiOrigin: "",
    filters: [],
    images: [],
    files: [],
    sending: false,
    pollTimer: null,
    savedRange: null,
    normalizedHtml: "",
    normalizeTimer: null,
    htmlPanelOpen: false,
    htmlPanelDirty: false,
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

  function stripHtml(html) {
    var tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    return (tmp.textContent || tmp.innerText || "").replace(/\u00a0/g, " ").trim();
  }

  function setStatus(message, kind) {
    var box = el("bc-status");
    if (!box) return;
    if (!message) {
      box.textContent = "";
      box.className = "bc-status";
      box.hidden = true;
      return;
    }
    box.textContent = message;
    box.className = "bc-status" + (kind ? " bc-status-" + kind : "");
    box.hidden = false;
  }

  function selectedBotId() {
    var sel = el("bc-bot-select");
    return sel && sel.value ? sel.value : "";
  }

  function selectedFilterId() {
    var sel = el("bc-role-select");
    return sel && sel.value ? sel.value : "all";
  }

  function imagePosition() {
    var sel = el("bc-image-position");
    return sel && sel.value === "after" ? "after" : "before";
  }

  function parseFetchResponse(res) {
    return res.text().then(function (text) {
      var data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (e) {
          data = { detail: "Ответ сервера не JSON (код " + res.status + ")" };
        }
      }
      return { ok: res.ok, status: res.status, data: data };
    });
  }

  function apiErrorMessage(result, fallback) {
    if (!result || !result.data) return fallback;
    var detail = result.data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0] && detail[0].msg) return detail[0].msg;
    return fallback + " (" + (result.status || "?") + ")";
  }

  function applyBotIdFromUrl() {
    var sel = el("bc-bot-select");
    if (!sel) return;
    var params = new URLSearchParams(global.location.search || "");
    var fromUrl = params.get("bot_id");
    if (fromUrl && sel.querySelector('option[value="' + fromUrl + '"]')) {
      sel.value = fromUrl;
    }
  }

  function updatePreviewBotName() {
    var nameEl = el("bc-preview-bot-name");
    var sel = el("bc-bot-select");
    if (!nameEl || !sel) return;
    var opt = sel.options[sel.selectedIndex];
    nameEl.textContent = opt && opt.value ? opt.textContent : tr("mailing.your_bot");
  }

  function loadBots() {
    return fetch(state.apiOrigin + "/api/analytics/bots", { headers: authHeaders() })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var sel = el("bc-bot-select");
        if (!sel) return;
        var prev = sel.value;
        sel.innerHTML = '<option value="">' + tr("common.select_bot") + "</option>";
        (data || []).forEach(function (b) {
          var opt = document.createElement("option");
          opt.value = b.id;
          opt.textContent = b.name || "Bot " + b.id;
          sel.appendChild(opt);
        });
        applyBotIdFromUrl();
        if (!sel.value && prev) sel.value = prev;
        updatePreviewBotName();
      })
      .catch(function () {
        setStatus(tr("mailing.load_bots_error"), "error");
      });
  }

  function updateFilterMeta() {
    var meta = el("bc-filter-meta");
    if (!meta) return;
    var filterId = selectedFilterId();
    var found = state.filters.find(function (f) {
      return f.id === filterId;
    });
    meta.textContent = found && typeof found.count === "number" ? tr("mailing.recipients", { n: found.count }) : "";
  }

  function loadFilters() {
    var botId = selectedBotId();
    var roleSel = el("bc-role-select");
    var sendBtn = el("bc-send-btn");
    if (!botId) {
      state.filters = [];
      if (roleSel) {
        roleSel.innerHTML = '<option value="all">' + tr("mailing.all_subscribers") + "</option>";
        roleSel.disabled = true;
      }
      if (sendBtn) sendBtn.disabled = true;
      updateFilterMeta();
      return Promise.resolve();
    }

    return fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(botId) + "/broadcast/roles", {
      headers: authHeaders(),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, "Ошибка загрузки фильтров"));
        state.filters = (result.data && result.data.filters) || [];
        if (roleSel) {
          roleSel.innerHTML = state.filters
            .map(function (f) {
              var label = f.label || f.id;
              if (typeof f.count === "number") label += " (" + f.count + ")";
              return (
                '<option value="' +
                escapeHtml(f.id) +
                '">' +
                escapeHtml(label) +
                "</option>"
              );
            })
            .join("");
          roleSel.disabled = state.filters.length === 0;
        }
        if (sendBtn) sendBtn.disabled = false;
        updateFilterMeta();
      })
      .catch(function () {
        // silent — avoid layout jump from status banners
      });
  }

  function saveSelection() {
    var sel = global.getSelection();
    if (sel && sel.rangeCount) {
      state.savedRange = sel.getRangeAt(0).cloneRange();
    }
  }

  function restoreSelection() {
    var editor = el("bc-editor");
    if (!editor || !state.savedRange) return;
    editor.focus();
    var sel = global.getSelection();
    sel.removeAllRanges();
    sel.addRange(state.savedRange);
  }

  function findAncestorTag(node, tagName, root) {
    var el = node && node.nodeType === 3 ? node.parentElement : node;
    tagName = String(tagName || "").toLowerCase();
    while (el && el !== root) {
      if (el.tagName && el.tagName.toLowerCase() === tagName) return el;
      el = el.parentElement;
    }
    return null;
  }

  function unwrapElement(element) {
    if (!element || !element.parentNode) return;
    var parent = element.parentNode;
    while (element.firstChild) parent.insertBefore(element.firstChild, element);
    parent.removeChild(element);
  }

  function normalizedToEditorHtml(normalized) {
    if (!normalized) return "";
    var parts = normalized.split(/(<pre[\s\S]*?<\/pre>)/gi);
    return parts
      .map(function (part, index) {
        if (index % 2 === 1) return part;
        return part.replace(/\n/g, "<br>");
      })
      .join("");
  }

  function editorHtmlToPlainNewlines(html) {
    var container = document.createElement("div");
    container.innerHTML = html || "";
    container.querySelectorAll("br").forEach(function (br) {
      br.replaceWith(document.createTextNode("\n"));
    });
    container.querySelectorAll("div, p").forEach(function (block) {
      block.insertAdjacentText("afterend", "\n");
    });
    return container.innerHTML;
  }

  function fetchNormalizedHtml(rawHtml) {
    var botId = selectedBotId();
    var urls = [state.apiOrigin + "/api/broadcast/normalize"];
    if (botId) {
      urls.push(
        state.apiOrigin + "/api/projects/" + encodeURIComponent(botId) + "/broadcast/normalize"
      );
    }

    function tryUrl(index) {
      if (index >= urls.length) {
        return Promise.reject(new Error("API нормализации недоступен. Перезапустите BotBuilder."));
      }
      return fetch(urls[index], {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ html_content: rawHtml }),
      })
        .then(parseFetchResponse)
        .then(function (result) {
          if (result.status === 404 && index + 1 < urls.length) {
            return tryUrl(index + 1);
          }
          if (!result.ok) throw new Error(apiErrorMessage(result, "Ошибка нормализации HTML"));
          return (result.data && result.data.normalized_html) || "";
        });
    }

    return tryUrl(0);
  }

  function scheduleNormalize() {
    if (state.normalizeTimer) clearTimeout(state.normalizeTimer);
    state.normalizeTimer = setTimeout(function () {
      state.normalizeTimer = null;
      refreshNormalizedPreview();
    }, 300);
  }

  function syncHtmlPanelFromEditor() {
    var input = el("bc-html-modal-input");
    if (!input || !state.htmlPanelOpen) return;
    if (document.activeElement === input) return;
    if (state.htmlPanelDirty) return;
    input.value = state.normalizedHtml || "";
  }

  function markHtmlPanelDirty() {
    state.htmlPanelDirty = true;
  }

  function clearHtmlPanelDirty() {
    state.htmlPanelDirty = false;
  }

  function refreshNormalizedPreview() {
    var editor = el("bc-editor");
    if (!editor) return Promise.resolve();
    var raw = editor.innerHTML.trim();
    if (!raw) {
      state.normalizedHtml = "";
      renderPreviewMessages("");
      syncHtmlPanelFromEditor();
      return Promise.resolve();
    }
    return fetchNormalizedHtml(raw)
      .then(function (normalized) {
        state.normalizedHtml = normalized || "";
        renderPreviewMessages(state.normalizedHtml);
        syncHtmlPanelFromEditor();
      })
      .catch(function (err) {
        setStatus(err.message || "Ошибка нормализации", "error");
        renderPreviewMessages(normalizePreviewHtml(raw));
        syncHtmlPanelFromEditor();
      });
  }

  function applyNormalizedToEditor(rawHtml) {
    return fetchNormalizedHtml(rawHtml).then(function (normalized) {
      state.normalizedHtml = normalized || "";
      var editor = el("bc-editor");
      if (editor) editor.innerHTML = normalizedToEditorHtml(normalized);
      renderPreviewMessages(state.normalizedHtml);
      syncHtmlPanelFromEditor();
    });
  }

  function wrapSelection(tagName, attrs) {
    restoreSelection();
    var sel = global.getSelection();
    if (!sel || !sel.rangeCount) return false;
    var range = sel.getRangeAt(0);
    if (range.collapsed) return false;
    var node = document.createElement(tagName);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        node.setAttribute(key, attrs[key]);
      });
    }
    try {
      range.surroundContents(node);
    } catch (e) {
      node.appendChild(range.extractContents());
      range.insertNode(node);
    }
    sel.removeAllRanges();
    var after = document.createRange();
    after.selectNodeContents(node);
    after.collapse(false);
    sel.addRange(after);
    state.savedRange = after.cloneRange();
    return true;
  }

  function normalizePreviewHtml(rawHtml) {
    var container = document.createElement("div");
    container.innerHTML = rawHtml || "";
    container.querySelectorAll("script, style").forEach(function (node) {
      node.remove();
    });
    container.querySelectorAll("span, font").forEach(function (node) {
      var frag = document.createDocumentFragment();
      while (node.firstChild) frag.appendChild(node.firstChild);
      node.replaceWith(frag);
    });
    container.querySelectorAll("*").forEach(function (node) {
      Array.from(node.attributes).forEach(function (attr) {
        if (attr.name !== "href") node.removeAttribute(attr.name);
      });
      var tag = node.tagName.toLowerCase();
      if (tag === "strong") {
        var b = document.createElement("b");
        b.innerHTML = node.innerHTML;
        node.replaceWith(b);
      }
      if (tag === "em") {
        var i = document.createElement("i");
        i.innerHTML = node.innerHTML;
        node.replaceWith(i);
      }
      if (tag === "strike" || tag === "del") {
        var s = document.createElement("s");
        s.innerHTML = node.innerHTML;
        node.replaceWith(s);
      }
    });
    return container.innerHTML;
  }

  function telegramHtmlToPreviewHtml(normalized) {
    if (!normalized) return "";
    return normalizedToEditorHtml(normalized);
  }

  function bubbleMetaHtml() {
    var now = new Date();
    var hh = String(now.getHours()).padStart(2, "0");
    var mm = String(now.getMinutes()).padStart(2, "0");
    return (
      '<div class="bc-tg-meta"><span class="bc-tg-time">' +
      hh +
      ":" +
      mm +
      '</span><span class="bc-tg-checks" aria-hidden="true"><svg viewBox="0 0 16 11" width="16" height="11"><path fill="#4fc3f7" d="M11.071.653a.457.457 0 0 1 .644 0l1.003 1.003a.457.457 0 0 1 0 .644L4.987 10.03a.457.457 0 0 1-.644 0L.653 6.34a.457.457 0 0 1 0-.644l1.003-1.003a.457.457 0 0 1 .644 0l2.334 2.334L11.071.653z"/><path fill="#4fc3f7" d="M15.071.653a.457.457 0 0 1 .644 0l1.003 1.003a.457.457 0 0 1 0 .644L8.987 10.03a.457.457 0 0 1-.644 0L7.34 8.684l1.003-1.003 1.34 1.34L15.071.653z"/></svg></span></div>'
    );
  }

  function renderTextBubble(html) {
    return (
      '<div class="bc-tg-row bc-tg-row-out">' +
      '<div class="bc-tg-bubble bc-tg-bubble-text">' +
      '<div class="bc-tg-text">' +
      html +
      "</div>" +
      bubbleMetaHtml() +
      "</div></div>"
    );
  }

  function renderPhotoBubble(src, captionHtml) {
    var captionBlock = captionHtml
      ? '<div class="bc-tg-text bc-tg-caption">' + captionHtml + "</div>"
      : "";
    return (
      '<div class="bc-tg-row bc-tg-row-out">' +
      '<div class="bc-tg-bubble bc-tg-bubble-photo">' +
      '<img class="bc-tg-photo" src="' +
      escapeHtml(src) +
      '" alt="" />' +
      captionBlock +
      bubbleMetaHtml() +
      "</div></div>"
    );
  }

  function renderFileBubble(name) {
    return (
      '<div class="bc-tg-row bc-tg-row-out">' +
      '<div class="bc-tg-bubble bc-tg-bubble-file">' +
      '<div class="bc-tg-file-icon">📄</div>' +
      '<div class="bc-tg-file-body">' +
      '<div class="bc-tg-file-name">' +
      escapeHtml(name) +
      "</div>" +
      '<div class="bc-tg-file-sub">' + escapeHtml(tr("mailing.document")) + "</div>" +
      "</div>" +
      bubbleMetaHtml() +
      "</div></div>"
    );
  }

  function renderPreviewMessages(normalizedHtml) {
    var root = el("bc-preview-messages");
    if (!root) return;

    var textHtml = telegramHtmlToPreviewHtml(normalizedHtml);
    var hasText = stripHtml(normalizedHtml || textHtml).length > 0;
    var position = imagePosition();
    var parts = [];

    if (position === "before") {
      if (state.images.length) {
        state.images.forEach(function (img, index) {
          var caption = index === 0 && hasText ? textHtml : "";
          parts.push(renderPhotoBubble(img.previewUrl || "", caption));
        });
      } else if (hasText) {
        parts.push(renderTextBubble(textHtml));
      }
    } else {
      if (hasText) parts.push(renderTextBubble(textHtml));
      state.images.forEach(function (img) {
        parts.push(renderPhotoBubble(img.previewUrl || "", ""));
      });
    }

    state.files.forEach(function (file) {
      parts.push(renderFileBubble(file.name || file.path));
    });

    if (!parts.length) {
      root.innerHTML =
        '<div class="bc-tg-empty">' + escapeHtml(tr("mailing.preview_empty")) + "</div>";
      return;
    }

    root.innerHTML = parts.join("");
  }

  function updatePreview() {
    scheduleNormalize();
  }

  function toggleInlineTag(tagName) {
    var editor = el("bc-editor");
    restoreSelection();
    editor.focus();
    var sel = global.getSelection();
    if (!sel || !sel.rangeCount) return;
    var existing = findAncestorTag(sel.anchorNode, tagName, editor);
    if (existing) {
      unwrapElement(existing);
    } else {
      wrapSelection(tagName);
    }
    saveSelection();
    scheduleNormalize();
  }

  function toggleLink() {
    var editor = el("bc-editor");
    restoreSelection();
    editor.focus();
    var sel = global.getSelection();
    if (!sel || !sel.rangeCount) return;
    var link = findAncestorTag(sel.anchorNode, "a", editor);
    if (link) {
      if (global.confirm(tr("mailing.link_remove_confirm"))) {
        unwrapElement(link);
      } else {
        var newUrl = global.prompt(tr("mailing.link_new_url"), link.getAttribute("href") || "https://");
        if (newUrl && /^https?:\/\//i.test(newUrl)) link.setAttribute("href", newUrl);
      }
      saveSelection();
      scheduleNormalize();
      return;
    }
    var url = global.prompt(tr("mailing.link_prompt"), "https://");
    if (!url || !/^https?:\/\//i.test(url)) {
      if (url) setStatus(tr("mailing.link_invalid"), "error");
      return;
    }
    wrapSelection("a", { href: url });
    saveSelection();
    scheduleNormalize();
  }

  function toggleCode() {
    var editor = el("bc-editor");
    restoreSelection();
    editor.focus();
    var sel = global.getSelection();
    if (!sel || !sel.rangeCount) return;
    var pre = findAncestorTag(sel.anchorNode, "pre", editor);
    if (pre) {
      unwrapElement(pre);
      saveSelection();
      scheduleNormalize();
      return;
    }
    var code = findAncestorTag(sel.anchorNode, "code", editor);
    if (code) {
      unwrapElement(code);
      saveSelection();
      scheduleNormalize();
      return;
    }
    var text = sel.toString();
    if (text.indexOf("\n") >= 0) {
      document.execCommand(
        "insertHTML",
        false,
        "<pre>" + escapeHtml(text) + "</pre>"
      );
    } else if (text) {
      wrapSelection("code");
    } else {
      document.execCommand("insertHTML", false, "<code></code>");
    }
    saveSelection();
    scheduleNormalize();
  }

  function execCommand(cmd) {
    var editor = el("bc-editor");
    if (!editor) return;
    restoreSelection();
    editor.focus();

    if (cmd === "bold") {
      document.execCommand("bold", false, null);
    } else if (cmd === "italic") {
      document.execCommand("italic", false, null);
    } else if (cmd === "underline") {
      document.execCommand("underline", false, null);
    } else if (cmd === "strike") {
      toggleInlineTag("s");
      return;
    } else if (cmd === "code") {
      toggleCode();
      return;
    } else if (cmd === "link") {
      toggleLink();
      return;
    }

    saveSelection();
    scheduleNormalize();
  }

  function setHtmlPanelOpen(open) {
    var panel = el("bc-html-panel");
    var btn = el("bc-import-html-btn");
    state.htmlPanelOpen = !!open;
    if (panel) panel.hidden = !open;
    if (btn) btn.classList.toggle("bc-tool-btn-active", !!open);
  }

  function openHtmlPanel() {
    setHtmlPanelOpen(true);
    clearHtmlPanelDirty();
    refreshNormalizedPreview().then(syncHtmlPanelFromEditor);
  }

  function closeHtmlPanel() {
    setHtmlPanelOpen(false);
  }

  function toggleHtmlPanel() {
    if (state.htmlPanelOpen) closeHtmlPanel();
    else openHtmlPanel();
  }

  function applyHtmlFromModal() {
    var input = el("bc-html-modal-input");
    var editor = el("bc-editor");
    var raw = input ? input.value.trim() : "";
    if (!raw && editor) raw = editor.innerHTML.trim();
    if (!raw && state.normalizedHtml) raw = state.normalizedHtml.trim();
    if (!raw) {
      setStatus(tr("mailing.html_paste_field"), "error");
      return;
    }
    applyNormalizedToEditor(raw)
      .then(function () {
        clearHtmlPanelDirty();
        if (input) input.value = state.normalizedHtml || "";
      })
      .catch(function () {});
  }

  function importHtmlBlock() {
    toggleHtmlPanel();
  }

  function handlePaste(e) {
    var editor = el("bc-editor");
    if (!editor) return;
    var clip = e.clipboardData || window.clipboardData;
    if (!clip) return;
    var html = clip.getData("text/html");
    var plain = clip.getData("text/plain");
    if (html && html.indexOf("<") >= 0) {
      e.preventDefault();
      var isFullDoc = html.length > 400 || /<div|<table|<h1|<ul|<pre/i.test(html);
      if (isFullDoc || !stripHtml(editor.innerHTML)) {
        applyNormalizedToEditor(html).catch(function () {});
        return;
      }
      fetchNormalizedHtml(html)
        .then(function (normalized) {
          document.execCommand("insertHTML", false, normalizedToEditorHtml(normalized));
          saveSelection();
          scheduleNormalize();
        })
        .catch(function () {
          if (plain) document.execCommand("insertText", false, plain);
          scheduleNormalize();
        });
      return;
    }
    if (plain) {
      e.preventDefault();
      document.execCommand("insertText", false, plain);
      saveSelection();
      scheduleNormalize();
    }
  }

  function moveAttachment(kind, index, delta) {
    var list = kind === "image" ? state.images : state.files;
    var next = index + delta;
    if (next < 0 || next >= list.length) return;
    var tmp = list[index];
    list[index] = list[next];
    list[next] = tmp;
    renderAttachmentList();
    updatePreview();
  }

  function removeAttachment(kind, index) {
    if (kind === "image") {
      var removed = state.images.splice(index, 1)[0];
      if (removed && removed.previewUrl) URL.revokeObjectURL(removed.previewUrl);
    } else {
      state.files.splice(index, 1);
    }
    renderAttachmentList();
    updatePreview();
  }

  function renderAttachmentList() {
    var list = el("bc-attachment-list");
    if (!list) return;
    var rows = [];
    state.images.forEach(function (item, index) {
      rows.push({ kind: "image", index: index, item: item });
    });
    state.files.forEach(function (item, index) {
      rows.push({ kind: "file", index: index, item: item });
    });
    if (!rows.length) {
      list.innerHTML = "";
      return;
    }

    list.innerHTML = rows
      .map(function (row) {
        var icon = row.kind === "image" ? "🖼" : "📎";
        var listRef = row.kind === "image" ? state.images : state.files;
        var upDisabled = row.index === 0 ? " disabled" : "";
        var downDisabled = row.index === listRef.length - 1 ? " disabled" : "";
        return (
          '<div class="bc-attachment-item">' +
          '<div class="bc-attachment-main">' +
          (row.kind === "image" && row.item.previewUrl
            ? '<img class="bc-attachment-thumb" src="' + escapeHtml(row.item.previewUrl) + '" alt="" />'
            : "") +
          "<span>" +
          icon +
          " " +
          escapeHtml(row.item.name || row.item.path) +
          "</span></div>" +
          '<div class="bc-attachment-actions">' +
          '<button type="button" class="bc-move-btn" data-move-kind="' +
          row.kind +
          '" data-move-index="' +
          row.index +
          '" data-move-delta="-1"' +
          upDisabled +
          ">↑</button>" +
          '<button type="button" class="bc-move-btn" data-move-kind="' +
          row.kind +
          '" data-move-index="' +
          row.index +
          '" data-move-delta="1"' +
          downDisabled +
          ">↓</button>" +
          '<button type="button" class="bc-remove-btn" data-kind="' +
          row.kind +
          '" data-index="' +
          row.index +
          '">' + escapeHtml(tr("mailing.remove")) + "</button>" +
          "</div></div>"
        );
      })
      .join("");

    list.querySelectorAll(".bc-remove-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        removeAttachment(btn.getAttribute("data-kind"), parseInt(btn.getAttribute("data-index"), 10));
      });
    });
    list.querySelectorAll(".bc-move-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        moveAttachment(
          btn.getAttribute("data-move-kind"),
          parseInt(btn.getAttribute("data-move-index"), 10),
          parseInt(btn.getAttribute("data-move-delta"), 10)
        );
      });
    });
  }

  function uploadFile(file, asImage) {
    var botId = selectedBotId();
    if (!botId) {
      setStatus(tr("mailing.select_bot_first"), "error");
      return Promise.resolve();
    }
    var form = new FormData();
    form.append("file", file);
    return fetch(state.apiOrigin + "/api/bots/upload/" + encodeURIComponent(botId), {
      method: "POST",
      headers: authHeaders(),
      body: form,
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, "Ошибка загрузки файла"));
        var path = result.data && result.data.path;
        if (!path) throw new Error("Сервер не вернул путь к файлу");
        var entry = {
          kind: asImage ? "image" : "file",
          path: path,
          name: file.name,
          previewUrl: asImage ? URL.createObjectURL(file) : null,
        };
        if (asImage) state.images.push(entry);
        else state.files.push(entry);
        renderAttachmentList();
        updatePreview();
      })
      .catch(function (err) {
        setStatus(err.message || "Ошибка загрузки", "error");
      });
  }

  function handleFiles(fileList) {
    var files = Array.from(fileList || []);
    if (!files.length) return;
    files.forEach(function (file) {
      var asImage = IMAGE_EXT.test(file.name) || (file.type || "").indexOf("image/") === 0;
      uploadFile(file, asImage);
    });
  }

  function setSending(loading) {
    state.sending = loading;
    var btn = el("bc-send-btn");
    var spinner = el("bc-send-spinner");
    if (btn) btn.disabled = loading || !selectedBotId();
    if (spinner) spinner.hidden = !loading;
  }

  function pollJobStatus(botId, jobId) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(function () {
      fetch(
        state.apiOrigin +
          "/api/projects/" +
          encodeURIComponent(botId) +
          "/broadcast/status/" +
          encodeURIComponent(jobId),
        { headers: authHeaders() }
      )
        .then(parseFetchResponse)
        .then(function (result) {
          if (!result.ok) return;
          var job = result.data || {};
          if (!job.finished) return;
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          setSending(false);
          if (job.status === "failed") {
            setStatus("", "");
            return;
          }
          var sent = Number(job.sent) || 0;
          setStatus(tr("mailing.sent_success", { n: sent }), "success");
        })
        .catch(function () {});
    }, 1200);
  }

  function sendBroadcast() {
    var botId = selectedBotId();
    if (!botId || state.sending) return;
    var editor = el("bc-editor");
    var html = editor ? editor.innerHTML : "";
    if (!html.trim() && !state.images.length && !state.files.length) {
      return;
    }

    setSending(true);
    setStatus("", "");

    fetch(state.apiOrigin + "/api/projects/" + encodeURIComponent(botId) + "/broadcast/send", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({
        html_content: html,
        target_role: selectedFilterId(),
        image_paths: state.images.map(function (i) {
          return i.path;
        }),
        file_paths: state.files.map(function (f) {
          return f.path;
        }),
        image_position: imagePosition(),
      }),
    })
      .then(parseFetchResponse)
      .then(function (result) {
        if (!result.ok) throw new Error(apiErrorMessage(result, "Не удалось запустить рассылку"));
        var jobId = result.data && result.data.job_id;
        if (jobId) pollJobStatus(botId, jobId);
        else setSending(false);
      })
      .catch(function () {
        setSending(false);
        setStatus("", "");
      });
  }

  function bindEvents() {
    var botSel = el("bc-bot-select");
    var roleSel = el("bc-role-select");
    var editor = el("bc-editor");
    var dropzone = el("bc-dropzone");
    var fileInput = el("bc-file-input");
    var imageInput = el("bc-image-input");
    var positionSel = el("bc-image-position");

    if (botSel) {
      botSel.addEventListener("change", function () {
        state.images.forEach(function (img) {
          if (img.previewUrl) URL.revokeObjectURL(img.previewUrl);
        });
        state.images = [];
        state.files = [];
        renderAttachmentList();
        loadFilters();
        updatePreviewBotName();
        updatePreview();
      });
    }

    if (roleSel) roleSel.addEventListener("change", updateFilterMeta);
    if (positionSel) positionSel.addEventListener("change", updatePreview);

    el("bc-refresh-btn") &&
      el("bc-refresh-btn").addEventListener("click", function () {
        loadBots().then(loadFilters);
      });

    el("bc-send-btn") && el("bc-send-btn").addEventListener("click", sendBroadcast);

    document.querySelectorAll("#bc-editor-toolbar .bc-tool-btn[data-cmd]").forEach(function (btn) {
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault();
        saveSelection();
      });
      btn.addEventListener("click", function () {
        execCommand(btn.getAttribute("data-cmd"));
      });
    });

    el("bc-import-html-btn") &&
      el("bc-import-html-btn").addEventListener("click", importHtmlBlock);

    el("bc-html-modal-apply") &&
      el("bc-html-modal-apply").addEventListener("mousedown", function (e) {
        e.preventDefault();
      });
    el("bc-html-modal-apply") &&
      el("bc-html-modal-apply").addEventListener("click", applyHtmlFromModal);
    el("bc-html-panel-close") &&
      el("bc-html-panel-close").addEventListener("click", closeHtmlPanel);

    var htmlInput = el("bc-html-modal-input");
    if (htmlInput) {
      htmlInput.addEventListener("input", markHtmlPanelDirty);
    }

    el("bc-insert-image-btn") &&
      el("bc-insert-image-btn").addEventListener("click", function () {
        if (imageInput) imageInput.click();
      });

    if (imageInput) {
      imageInput.addEventListener("change", function () {
        handleFiles(imageInput.files);
        imageInput.value = "";
      });
    }

    if (dropzone && fileInput) {
      dropzone.addEventListener("click", function () {
        fileInput.click();
      });
      fileInput.addEventListener("change", function () {
        handleFiles(fileInput.files);
        fileInput.value = "";
      });
      ["dragenter", "dragover"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          dropzone.classList.add("bc-dropzone-drag");
        });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        dropzone.addEventListener(ev, function (e) {
          e.preventDefault();
          dropzone.classList.remove("bc-dropzone-drag");
        });
      });
      dropzone.addEventListener("drop", function (e) {
        handleFiles(e.dataTransfer && e.dataTransfer.files);
      });
    }

    if (editor) {
      editor.addEventListener("keyup", saveSelection);
      editor.addEventListener("mouseup", saveSelection);
      editor.addEventListener("focus", saveSelection);
      editor.addEventListener("input", function () {
        saveSelection();
        scheduleNormalize();
      });
      editor.addEventListener("paste", handlePaste);
    }
  }

  function init() {
    state.apiOrigin = getApiOrigin();
    bindEvents();
    loadBots().then(function () {
      loadFilters();
      refreshNormalizedPreview();
    });
    document.addEventListener("botbuilder:langchange", function () {
      loadBots().then(loadFilters);
      updatePreviewBotName();
      renderAttachmentList();
      updatePreview();
    });
  }

  global.BroadcastView = { init: init };
})(typeof window !== "undefined" ? window : globalThis);
