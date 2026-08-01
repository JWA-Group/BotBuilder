/* global t, applyI18n */
(function (global) {
  "use strict";

  var TAG_COLORS = [
    "indigo", "emerald", "amber", "rose", "sky", "purple", "teal", "orange",
  ];

  var TAG_THEME = {
    indigo: "ps-tag-indigo",
    emerald: "ps-tag-emerald",
    amber: "ps-tag-amber",
    rose: "ps-tag-rose",
    sky: "ps-tag-sky",
    purple: "ps-tag-purple",
    teal: "ps-tag-teal",
    orange: "ps-tag-orange",
  };

  var state = {
    apiOrigin: "",
    botId: null,
    channelId: "",
    channelTitle: "",
    mode: "visual",
    media: [],
    keyboard: [],
    tags: [],
    tagColor: "indigo",
    autoDeleteEnabled: false,
    editId: null,
    editStatus: null,
    posts: [],
    historyQuery: "",
    historyTagFilter: "",
    expandedPosts: {},
    deleteTarget: null,
    deletePurge: false,
    autoDeleteTarget: null,
    syncingHtml: false,
    savedRange: null,
  };

  function tr(key) {
    try {
      return typeof t === "function" ? t(key) : key;
    } catch (e) {
      return key;
    }
  }

  function el(id) {
    return document.getElementById(id);
  }

  function authHeaders() {
    var h = {};
    try {
      var tok = localStorage.getItem("access_token") || localStorage.getItem("token");
      if (tok) h.Authorization = "Bearer " + tok;
    } catch (e) {}
    return h;
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), opts.headers || {});
    if (opts.body instanceof FormData) {
      delete headers["Content-Type"];
    }
    return fetch(state.apiOrigin + path, {
      method: opts.method || "GET",
      headers: headers,
      body: opts.body,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var detail = data && (data.detail || data.message);
          if (Array.isArray(detail)) detail = detail.map(function (x) { return x.msg || x; }).join("; ");
          throw new Error(detail || ("HTTP " + res.status));
        }
        return data;
      });
    });
  }

  function toast(msg, kind) {
    if (!msg) return;
    var existing = document.getElementById("ps-toast");
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
    var isError = kind === "err" || kind === "error";
    var node = document.createElement("div");
    node.id = "ps-toast";
    node.className = "ps-toast" + (isError ? " ps-toast-err" : " ps-toast-ok");
    node.setAttribute("role", "status");
    node.innerHTML =
      '<span class="ps-toast-icon" aria-hidden="true">' +
      (isError ? "!" : "✓") +
      '</span><span class="ps-toast-text"></span>';
    node.querySelector(".ps-toast-text").textContent = msg;
    document.body.appendChild(node);
    requestAnimationFrame(function () {
      node.classList.add("visible");
    });
    clearTimeout(toast._t);
    toast._t = setTimeout(function () {
      node.classList.remove("visible");
      setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
      }, 320);
    }, isError ? 4200 : 2600);
  }

  function sanitizeTelegramHtml(raw) {
    var tmp = document.createElement("div");
    tmp.innerHTML = raw || "";
    var allowed = {
      B: "b", STRONG: "b", I: "i", EM: "i", U: "u", INS: "u",
      S: "s", STRIKE: "s", DEL: "s", A: "a", CODE: "code", PRE: "pre",
      BLOCKQUOTE: "blockquote", BR: "br",
    };

    function walk(node) {
      if (node.nodeType === 3) return node.textContent;
      if (node.nodeType !== 1) return "";
      var tag = node.tagName;
      if (tag === "BR") return "\n";
      if (tag === "DIV" || tag === "P" || /^H[1-6]$/.test(tag)) {
        var innerBlock = Array.prototype.map.call(node.childNodes, walk).join("");
        return innerBlock + (innerBlock.endsWith("\n") ? "" : "\n");
      }
      if (tag === "SPAN" && (node.classList.contains("tg-spoiler") || node.getAttribute("class") === "tg-spoiler")) {
        return "<tg-spoiler>" + Array.prototype.map.call(node.childNodes, walk).join("") + "</tg-spoiler>";
      }
      var mapped = allowed[tag];
      if (!mapped) {
        return Array.prototype.map.call(node.childNodes, walk).join("");
      }
      if (mapped === "a") {
        var href = (node.getAttribute("href") || "").trim();
        if (!/^(https?:\/\/|tg:\/\/)/i.test(href)) {
          return Array.prototype.map.call(node.childNodes, walk).join("");
        }
        return '<a href="' + href.replace(/"/g, "&quot;") + '">' +
          Array.prototype.map.call(node.childNodes, walk).join("") + "</a>";
      }
      return "<" + mapped + ">" + Array.prototype.map.call(node.childNodes, walk).join("") + "</" + mapped + ">";
    }

    return Array.prototype.map.call(tmp.childNodes, walk).join("").replace(/\n{3,}/g, "\n\n").trim();
  }

  function editorHtml() {
    if (state.mode === "html") return el("ps-html-input").value || "";
    return sanitizeTelegramHtml(el("ps-editor").innerHTML || "");
  }

  function setEditorHtml(html) {
    state.syncingHtml = true;
    el("ps-html-input").value = html || "";
    el("ps-editor").innerHTML = previewHtml(html || "");
    state.syncingHtml = false;
    updatePreview();
  }

  function previewHtml(html) {
    var s = (html || "")
      .replace(/<tg-spoiler>/gi, '<span class="tg-spoiler">')
      .replace(/<\/tg-spoiler>/gi, "</span>");
    return s;
  }

  function uid(prefix) {
    return (prefix || "t") + "_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 7);
  }

  function autoDeleteUnix() {
    if (!state.autoDeleteEnabled) return null;
    var input = el("ps-autodelete-at");
    if (!input || !input.value) return null;
    var ms = new Date(input.value).getTime();
    if (!ms || isNaN(ms)) return null;
    return Math.floor(ms / 1000);
  }

  function toDatetimeLocalValue(unix) {
    if (!unix) return "";
    var d = new Date(Number(unix) * 1000);
    if (isNaN(d.getTime())) return "";
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function formatDateTime(unix) {
    if (!unix) return "";
    var d = new Date(Number(unix) * 1000);
    if (isNaN(d.getTime())) return "";
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear() +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function statusLabel(status) {
    var key = "publisher.status_" + String(status || "");
    var label = tr(key);
    return label === key ? String(status || "") : label;
  }

  function plainText(html) {
    return String(html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  }

  function currentPayload() {
    return {
      bot_id: Number(state.botId),
      channel_id: state.channelId,
      channel_title: state.channelTitle || "",
      text_html: editorHtml(),
      media_files: state.media.map(function (m) {
        return { path: m.path, name: m.name };
      }),
      inline_keyboard: state.keyboard,
      // App-only metadata — backend stores them but never sends to Telegram API.
      tags: state.tags.map(function (tag) {
        return { id: tag.id, name: tag.name, color: tag.color };
      }),
      auto_delete_at: autoDeleteUnix(),
      post_id: state.editId || null,
    };
  }

  function renderTagColors() {
    var root = el("ps-tag-colors");
    if (!root) return;
    root.innerHTML = "";
    TAG_COLORS.forEach(function (color) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ps-color-dot " + (TAG_THEME[color] || "") + (state.tagColor === color ? " is-active" : "");
      btn.setAttribute("data-color", color);
      btn.setAttribute("aria-label", color);
      btn.title = color;
      btn.onclick = function () {
        state.tagColor = color;
        renderTagColors();
      };
      root.appendChild(btn);
    });
  }

  function renderTagList() {
    var root = el("ps-tag-list");
    if (!root) return;
    root.innerHTML = "";
    state.tags.forEach(function (tag, idx) {
      var pill = document.createElement("span");
      pill.className = "ps-tag-pill " + (TAG_THEME[tag.color] || TAG_THEME.indigo);
      pill.innerHTML = '<span class="ps-tag-pill-name"></span><button type="button" class="ps-tag-pill-x" aria-label="Remove">✕</button>';
      pill.querySelector(".ps-tag-pill-name").textContent = tag.name;
      pill.querySelector(".ps-tag-pill-x").onclick = function () {
        state.tags.splice(idx, 1);
        renderTagList();
      };
      root.appendChild(pill);
    });
  }

  function addTagFromInput() {
    var input = el("ps-tag-input");
    var name = ((input && input.value) || "").trim();
    if (!name) return;
    var exists = state.tags.some(function (t) {
      return t.name.toLowerCase() === name.toLowerCase();
    });
    if (exists) {
      if (input) input.value = "";
      return;
    }
    state.tags.push({
      id: uid("tag"),
      name: name.slice(0, 48),
      color: state.tagColor || "indigo",
    });
    if (input) input.value = "";
    renderTagList();
  }

  function syncAutoDeleteUi() {
    var enabled = el("ps-autodelete-enabled");
    var fields = el("ps-autodelete-fields");
    var chip = el("ps-autodelete-chip");
    var at = el("ps-autodelete-at");
    state.autoDeleteEnabled = !!(enabled && enabled.checked);
    if (fields) fields.hidden = !state.autoDeleteEnabled;
    if (!chip) return;
    var unix = autoDeleteUnix();
    if (state.autoDeleteEnabled && unix) {
      chip.hidden = false;
      chip.textContent = tr("publisher.autodelete_chip").replace("{when}", formatDateTime(unix));
    } else {
      chip.hidden = true;
      chip.textContent = "";
    }
    if (at && state.autoDeleteEnabled && !at.value) {
      // keep empty until user picks
    }
  }

  function setAutoDeleteFromPost(post) {
    var unix = post && post.auto_delete_at ? Number(post.auto_delete_at) : null;
    var enabled = el("ps-autodelete-enabled");
    var at = el("ps-autodelete-at");
    state.autoDeleteEnabled = !!(unix && unix > 0);
    if (enabled) enabled.checked = state.autoDeleteEnabled;
    if (at) at.value = state.autoDeleteEnabled ? toDatetimeLocalValue(unix) : "";
    syncAutoDeleteUi();
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll(".ps-mode-btn").forEach(function (btn) {
      btn.classList.toggle("ps-mode-active", btn.getAttribute("data-mode") === mode);
    });
    el("ps-visual-wrap").hidden = mode !== "visual";
    el("ps-html-wrap").hidden = mode !== "html";
    if (mode === "html") {
      el("ps-html-input").value = sanitizeTelegramHtml(el("ps-editor").innerHTML || "");
    } else {
      el("ps-editor").innerHTML = previewHtml(el("ps-html-input").value || "");
    }
    updatePreview();
  }

  function execCmd(cmd) {
    restoreSelection();
    el("ps-editor").focus();
    restoreSelection();
    if (cmd === "bold") document.execCommand("bold");
    else if (cmd === "italic") document.execCommand("italic");
    else if (cmd === "underline") document.execCommand("underline");
    else if (cmd === "strike") document.execCommand("strikeThrough");
    else if (cmd === "code") wrapSelection("code");
    else if (cmd === "blockquote") wrapSelection("blockquote");
    else if (cmd === "spoiler") wrapSelection("span", { className: "tg-spoiler" });
    else if (cmd === "link") {
      openLinkModal();
      return;
    }
    saveSelection();
    updatePreview();
  }

  function saveSelection() {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    var range = sel.getRangeAt(0);
    var editor = el("ps-editor");
    if (!editor || !editor.contains(range.commonAncestorContainer)) return;
    state.savedRange = range.cloneRange();
  }

  function restoreSelection() {
    if (!state.savedRange) return;
    var sel = window.getSelection();
    if (!sel) return;
    sel.removeAllRanges();
    try {
      sel.addRange(state.savedRange);
    } catch (e) {
      /* stale range */
    }
  }

  function findLinkAncestor(node) {
    var editor = el("ps-editor");
    while (node && node !== editor) {
      if (node.nodeType === 1 && node.tagName === "A") return node;
      node = node.parentNode;
    }
    return null;
  }

  function openLinkModal() {
    restoreSelection();
    var sel = window.getSelection();
    var existing = null;
    if (sel && sel.anchorNode) existing = findLinkAncestor(sel.anchorNode);
    var modal = el("ps-link-modal");
    var input = el("ps-link-url");
    if (!modal || !input) return;
    input.value = existing ? (existing.getAttribute("href") || "https://") : "https://";
    modal.hidden = false;
    setTimeout(function () {
      input.focus();
      input.select();
    }, 30);
  }

  function closeLinkModal() {
    var modal = el("ps-link-modal");
    if (modal) modal.hidden = true;
  }

  function applyLinkFromModal() {
    var input = el("ps-link-url");
    var url = ((input && input.value) || "").trim();
    if (!url || !/^(https?:\/\/|tg:\/\/)/i.test(url) || /^https?:\/\/$/i.test(url)) {
      toast(tr("publisher.link_invalid"), "err");
      return;
    }
    closeLinkModal();
    restoreSelection();
    el("ps-editor").focus();
    restoreSelection();

    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) {
      toast(tr("publisher.link_need_selection"), "err");
      return;
    }
    var existing = findLinkAncestor(sel.anchorNode);
    if (existing) {
      existing.setAttribute("href", url);
      saveSelection();
      updatePreview();
      return;
    }
    if (sel.isCollapsed) {
      toast(tr("publisher.link_need_selection"), "err");
      return;
    }
    wrapSelection("a", { href: url });
    saveSelection();
    updatePreview();
  }

  function wrapSelection(tag, opts) {
    opts = opts || {};
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount || sel.isCollapsed) return;
    var range = sel.getRangeAt(0);
    var node = document.createElement(tag);
    if (opts.className) node.className = opts.className;
    if (opts.href) node.setAttribute("href", opts.href);
    try {
      range.surroundContents(node);
    } catch (e) {
      node.appendChild(range.extractContents());
      range.insertNode(node);
    }
    sel.removeAllRanges();
    var next = document.createRange();
    next.selectNodeContents(node);
    next.collapse(false);
    sel.addRange(next);
  }

  function renderMedia() {
    var list = el("ps-media-list");
    var mode = el("ps-media-mode");
    list.innerHTML = "";
    state.media.forEach(function (item, idx) {
      var row = document.createElement("div");
      row.className = "ps-media-item";
      var thumb = document.createElement("div");
      thumb.className = "ps-media-thumb";
      var lower = (item.name || "").toLowerCase();
      if (/\.(jpg|jpeg|png|webp|gif)$/.test(lower) && item.previewUrl) {
        thumb.innerHTML = '<img alt="" src="' + item.previewUrl + '" />';
      } else if (/\.(mp4|mov|webm)$/.test(lower) && item.previewUrl) {
        thumb.innerHTML = '<video muted src="' + item.previewUrl + '"></video>';
      } else {
        thumb.textContent = "FILE";
      }
      var meta = document.createElement("div");
      meta.innerHTML = "<strong>" + escapeHtml(item.name || item.path) + "</strong><div class='ps-hint'>" +
        escapeHtml(item.path) + "</div>";
      var actions = document.createElement("div");
      actions.className = "ps-media-actions";
      actions.innerHTML =
        '<button type="button" class="db-btn-secondary" data-act="up">↑</button>' +
        '<button type="button" class="db-btn-secondary" data-act="down">↓</button>' +
        '<button type="button" class="ps-icon-btn" data-act="del" aria-label="Remove">×</button>';
      actions.onclick = function (e) {
        var btn = e.target.closest("button");
        if (!btn) return;
        var act = btn.getAttribute("data-act");
        if (act === "del") state.media.splice(idx, 1);
        if (act === "up" && idx > 0) {
          var tmp = state.media[idx - 1];
          state.media[idx - 1] = state.media[idx];
          state.media[idx] = tmp;
        }
        if (act === "down" && idx < state.media.length - 1) {
          var tmp2 = state.media[idx + 1];
          state.media[idx + 1] = state.media[idx];
          state.media[idx] = tmp2;
        }
        renderMedia();
        updatePreview();
      };
      row.appendChild(thumb);
      row.appendChild(meta);
      row.appendChild(actions);
      list.appendChild(row);
    });
    var n = state.media.length;
    if (n === 0) {
      mode.textContent = "";
      mode.hidden = true;
    } else {
      mode.hidden = false;
      mode.textContent = n === 1
        ? tr("publisher.media_single")
        : tr("publisher.media_album").replace("{n}", String(n));
    }
    var reorder = el("ps-reorder-hint");
    if (reorder) reorder.disabled = n < 2;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function uploadFiles(fileList) {
    if (!state.botId) {
      toast(tr("common.select_bot"), "err");
      return;
    }
    var files = Array.prototype.slice.call(fileList || []);
    var room = 10 - state.media.length;
    files.slice(0, room).forEach(function (file) {
      var form = new FormData();
      form.append("file", file);
      fetch(state.apiOrigin + "/api/bots/upload/" + encodeURIComponent(state.botId), {
        method: "POST",
        headers: authHeaders(),
        body: form,
      })
        .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
        .then(function (pack) {
          if (!pack.ok) throw new Error((pack.data && pack.data.detail) || "Upload failed");
          state.media.push({
            path: pack.data.path,
            name: pack.data.filename || file.name,
            previewUrl: URL.createObjectURL(file),
          });
          renderMedia();
          updatePreview();
        })
        .catch(function (err) { toast(err.message || String(err), "err"); });
    });
  }

  function renderKeyboard() {
    var root = el("ps-keyboard");
    root.innerHTML = "";
    state.keyboard.forEach(function (row, rIdx) {
      var box = document.createElement("div");
      box.className = "ps-kb-row";
      var head = document.createElement("div");
      head.className = "ps-kb-row-head";
      var title = document.createElement("span");
      title.className = "ps-kb-row-title";
      title.textContent = tr("publisher.row") + " " + (rIdx + 1);
      var delRow = document.createElement("button");
      delRow.type = "button";
      delRow.className = "ps-icon-btn";
      delRow.setAttribute("aria-label", "Remove row");
      delRow.textContent = "×";
      delRow.onclick = function () {
        state.keyboard.splice(rIdx, 1);
        renderKeyboard();
        updatePreview();
      };
      head.appendChild(title);
      head.appendChild(delRow);
      box.appendChild(head);
      (row || []).forEach(function (btn, bIdx) {
        var line = document.createElement("div");
        line.className = "ps-kb-btn";
        line.innerHTML =
          '<input class="db-input" data-f="text" placeholder="' + escapeHtml(tr("publisher.btn_text")) + '" />' +
          '<select class="db-input" data-f="type">' +
          '<option value="url">' + escapeHtml(tr("publisher.btn_url")) + "</option>" +
          '<option value="callback">' + escapeHtml(tr("publisher.btn_callback")) + "</option>" +
          "</select>" +
          '<input class="db-input" data-f="value" placeholder="' + escapeHtml(tr("publisher.btn_value")) + '" />' +
          '<button type="button" class="ps-icon-btn" data-act="del" aria-label="Remove">×</button>';
        line.querySelector('[data-f="text"]').value = btn.text || "";
        line.querySelector('[data-f="type"]').value = btn.type === "callback" ? "callback" : "url";
        line.querySelector('[data-f="value"]').value = btn.value || "";
        line.onchange = line.oninput = function () {
          state.keyboard[rIdx][bIdx] = {
            text: line.querySelector('[data-f="text"]').value,
            type: line.querySelector('[data-f="type"]').value,
            value: line.querySelector('[data-f="value"]').value,
          };
          updatePreview();
        };
        line.querySelector('[data-act="del"]').onclick = function () {
          state.keyboard[rIdx].splice(bIdx, 1);
          renderKeyboard();
          updatePreview();
        };
        box.appendChild(line);
      });
      var addWrap = document.createElement("div");
      addWrap.className = "ps-kb-add-wrap";
      var addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "ps-kb-add-btn";
      addBtn.textContent = tr("publisher.add_button");
      addBtn.onclick = function () {
        state.keyboard[rIdx].push({ text: "", type: "url", value: "" });
        renderKeyboard();
        updatePreview();
      };
      addWrap.appendChild(addBtn);
      box.appendChild(addWrap);
      root.appendChild(box);
    });
  }

  function updatePreview() {
    var html = editorHtml();
    var textNode = el("ps-preview-text");
    textNode.innerHTML = previewHtml(html) || '<span style="opacity:.5">' + escapeHtml(tr("publisher.preview_empty")) + "</span>";
    textNode.querySelectorAll(".tg-spoiler").forEach(function (sp) {
      sp.onclick = function () { sp.classList.toggle("ps-spoiler-open"); };
    });

    el("ps-preview-name").textContent = state.channelTitle || tr("publisher.preview_channel");
    var avatar = (state.channelTitle || "TG").trim().slice(0, 2).toUpperCase();
    el("ps-preview-avatar").textContent = avatar || "TG";
    var now = new Date();
    el("ps-preview-time").textContent =
      String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");

    var mediaBox = el("ps-preview-media");
    mediaBox.innerHTML = "";
    if (!state.media.length) {
      mediaBox.hidden = true;
    } else {
      mediaBox.hidden = false;
      mediaBox.className = "ps-tg-media" + (state.media.length > 1 ? " ps-album-" + Math.min(state.media.length, 4) : "");
      state.media.forEach(function (m) {
        var lower = (m.name || "").toLowerCase();
        if (/\.(jpg|jpeg|png|webp|gif)$/.test(lower) && m.previewUrl) {
          mediaBox.innerHTML += '<img alt="" src="' + m.previewUrl + '" />';
        } else if (/\.(mp4|mov|webm)$/.test(lower) && m.previewUrl) {
          mediaBox.innerHTML += '<video muted controls src="' + m.previewUrl + '"></video>';
        } else {
          mediaBox.innerHTML += '<div class="ps-media-thumb">DOC</div>';
        }
      });
    }

    var btns = el("ps-preview-buttons");
    btns.innerHTML = "";
    state.keyboard.forEach(function (row) {
      var rowEl = document.createElement("div");
      rowEl.className = "ps-tg-btn-row";
      (row || []).forEach(function (b) {
        if (!(b && b.text)) return;
        var bEl = document.createElement("div");
        bEl.className = "ps-tg-btn";
        bEl.textContent = b.text;
        rowEl.appendChild(bEl);
      });
      if (rowEl.childNodes.length) btns.appendChild(rowEl);
    });
  }

  function startNewPost(opts) {
    opts = opts || {};
    setEditorHtml("");
    state.media = [];
    state.keyboard = [];
    state.tags = [];
    state.editId = null;
    state.editStatus = null;
    if (el("ps-schedule-at")) el("ps-schedule-at").value = "";
    setAutoDeleteFromPost(null);
    setEditMode(null);
    renderMedia();
    renderKeyboard();
    renderTagList();
    updatePreview();
    if (opts.toast !== false) {
      toast(tr(opts.toastKey || "publisher.new_post_ok"), "ok");
    }
    switchTab("studio");
  }

  function setEditMode(post) {
    state.editId = post ? post.id : null;
    state.editStatus = post ? post.status : null;
    var hint = el("ps-edit-banner-text");
    var updateBtn = el("ps-update-tg");
    var scheduleRow = el("ps-footer-schedule");
    var sendBtn = el("ps-send");
    var draftBtn = el("ps-save-draft");
    var isPublished = !!(post && post.status === "published");
    if (!post) {
      if (hint) {
        hint.hidden = true;
        hint.textContent = "";
      }
    } else if (hint) {
      hint.hidden = false;
      hint.textContent = tr("publisher.editing_banner").replace("{id}", String(post.id));
    }
    if (updateBtn) {
      updateBtn.hidden = false;
      updateBtn.disabled = !isPublished;
    }
    if (scheduleRow) scheduleRow.hidden = isPublished;
    if (sendBtn) sendBtn.hidden = isPublished;
    if (draftBtn) draftBtn.hidden = isPublished;
  }

  function loadPostIntoEditor(post) {
    if (!post || post.status === "deleted") {
      toast(tr("publisher.deleted_cannot_edit"), "err");
      return;
    }
    state.channelId = String(post.channel_id || state.channelId);
    state.channelTitle = post.channel_title || state.channelTitle;
    if (el("ps-channel-select")) el("ps-channel-select").value = state.channelId;
    setEditorHtml(post.text_html || "");
    state.media = (post.media_files || []).map(function (m) {
      var path = m.path || m;
      var name = m.name || String(path).split(/[\\/]/).pop();
      return {
        path: path,
        name: name,
        previewUrl: mediaFileUrl(path),
      };
    });
    state.keyboard = Array.isArray(post.inline_keyboard) ? JSON.parse(JSON.stringify(post.inline_keyboard)) : [];
    if (!state.keyboard.length) state.keyboard = [];
    state.tags = Array.isArray(post.tags)
      ? post.tags.map(function (tag) {
          return {
            id: tag.id || uid("tag"),
            name: String(tag.name || "").trim(),
            color: TAG_THEME[tag.color] ? tag.color : "indigo",
          };
        }).filter(function (tag) { return !!tag.name; })
      : [];
    setAutoDeleteFromPost(post);
    setEditMode(post);
    renderMedia();
    renderKeyboard();
    renderTagList();
    updatePreview();
    switchTab("studio");
  }

  function switchTab(tab) {
    document.querySelectorAll(".ps-tab-btn").forEach(function (btn) {
      btn.classList.toggle("ps-tab-active", btn.getAttribute("data-tab") === tab);
    });
    el("ps-tab-studio").hidden = tab !== "studio";
    el("ps-tab-history").hidden = tab !== "history";
    if (tab === "history") refreshHistory();
  }

  function refreshHistory() {
    if (!state.botId) return;
    api("/api/publisher/posts?bot_id=" + encodeURIComponent(state.botId)).then(function (data) {
      state.posts = data.posts || [];
      renderHistory();
    }).catch(function (err) { toast(err.message || String(err), "err"); });
  }

  function collectHistoryTags() {
    var map = {};
    state.posts.forEach(function (post) {
      (post.tags || []).forEach(function (tag) {
        if (!tag || !tag.name) return;
        var key = String(tag.name).toLowerCase();
        if (!map[key]) {
          map[key] = {
            name: tag.name,
            color: TAG_THEME[tag.color] ? tag.color : "indigo",
          };
        }
      });
    });
    return Object.keys(map).sort().map(function (k) { return map[k]; });
  }

  function renderHistoryTagCloud() {
    var root = el("ps-history-tag-cloud");
    if (!root) return;
    root.innerHTML = "";
    var tags = collectHistoryTags();
    if (!tags.length) {
      root.hidden = true;
      return;
    }
    root.hidden = false;
    tags.forEach(function (tag) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ps-tag-pill ps-tag-filter " + (TAG_THEME[tag.color] || TAG_THEME.indigo) +
        (state.historyTagFilter.toLowerCase() === String(tag.name).toLowerCase() ? " is-active" : "");
      btn.textContent = tag.name;
      btn.onclick = function () {
        if (state.historyTagFilter.toLowerCase() === tag.name.toLowerCase()) {
          state.historyTagFilter = "";
          if (el("ps-history-search") && state.historyQuery === tag.name) {
            el("ps-history-search").value = "";
            state.historyQuery = "";
          }
        } else {
          state.historyTagFilter = tag.name;
          state.historyQuery = tag.name;
          if (el("ps-history-search")) el("ps-history-search").value = tag.name;
        }
        syncHistorySearchClear();
        renderHistory();
      };
      root.appendChild(btn);
    });
  }

  function syncHistorySearchClear() {
    var clearBtn = el("ps-history-search-clear");
    if (clearBtn) clearBtn.hidden = !(state.historyQuery || state.historyTagFilter);
  }

  function filteredPosts() {
    var raw = String(state.historyQuery || "").trim().toLowerCase();
    var tagFilter = String(state.historyTagFilter || "").trim().toLowerCase();
    return state.posts.filter(function (post) {
      var tags = post.tags || [];
      var tagNames = tags.map(function (t) { return String(t.name || "").toLowerCase(); });
      if (tagFilter && tagNames.indexOf(tagFilter) === -1) return false;
      if (!raw) return true;
      var idOnly = raw.charAt(0) === "#";
      var qId = raw.replace(/^#+/, "").trim();
      var studioId = String(post.id || "");
      var tgId = String(post.telegram_message_id || "");
      var idHit =
        !!qId &&
        (studioId === qId ||
          tgId === qId ||
          ("#" + studioId) === raw ||
          ("#" + tgId) === raw);
      if (idOnly) return idHit;
      if (idHit) return true;
      var hay = [
        plainText(post.text_html),
        String(post.channel_title || ""),
        String(post.channel_id || ""),
        String(post.status || ""),
        studioId,
        "#" + studioId,
        tgId,
        "#" + tgId,
        tagNames.join(" "),
      ].join(" ").toLowerCase();
      return hay.indexOf(raw) !== -1 || (qId && hay.indexOf(qId) !== -1);
    });
  }

  /** Public media URL for <img>/<video> — /api/bots/media does not need Authorization. */
  function mediaFileUrl(relPath) {
    if (!state.botId || !relPath) return "";
    var name = String(relPath).replace(/\\/g, "/").split("/").filter(Boolean).pop();
    if (!name || name === "." || name === "..") return "";
    return (state.apiOrigin || "") +
      "/api/bots/media/" + encodeURIComponent(state.botId) + "/" + encodeURIComponent(name);
  }

  function historyMediaPreviewHtml(mediaFiles) {
    var media = mediaFiles || [];
    if (!media.length) return "";
    var albumClass = media.length > 1 ? " ps-album-" + Math.min(media.length, 4) : "";
    var parts = media.map(function (m) {
      var path = (m && (m.path || m)) || "";
      var name = (m && m.name) || String(path).split(/[\\/]/).pop() || "file";
      var lower = String(name || path).toLowerCase();
      var url = mediaFileUrl(path);
      if (/\.(jpg|jpeg|png|webp|gif)$/.test(lower) && url) {
        return '<img class="ps-hist-media-img" alt="" src="' + escapeHtml(url) +
          '" title="' + escapeHtml(name) + '" loading="lazy" />';
      }
      if (/\.(mp4|mov|webm|avi|mkv)$/.test(lower) && url) {
        return '<video class="ps-hist-media-img" muted controls preload="metadata" src="' +
          escapeHtml(url) + '" title="' + escapeHtml(name) + '"></video>';
      }
      return '<div class="ps-hist-media-thumb ps-hist-media-doc" title="' + escapeHtml(name) + '">DOC</div>';
    });
    return '<div class="ps-hist-media-grid' + albumClass + '">' + parts.join("") + "</div>";
  }

  function historyKeyboardPreviewHtml(keyboard) {
    var rows = keyboard || [];
    if (!rows.length) return "";
    var html = '<div class="ps-tg-buttons ps-hist-buttons">';
    rows.forEach(function (row) {
      var cells = (row || []).filter(function (b) { return b && b.text; });
      if (!cells.length) return;
      html += '<div class="ps-tg-btn-row">';
      cells.forEach(function (b) {
        html += '<div class="ps-tg-btn">' + escapeHtml(b.text) + "</div>";
      });
      html += "</div>";
    });
    html += "</div>";
    return html;
  }

  function renderHistory() {
    var root = el("ps-history-list");
    if (!root) return;
    root.innerHTML = "";
    renderHistoryTagCloud();
    syncHistorySearchClear();
    if (!state.posts.length) {
      root.innerHTML = '<p class="ps-hint">' + escapeHtml(tr("publisher.history_empty")) + "</p>";
      return;
    }
    var posts = filteredPosts();
    if (!posts.length) {
      root.innerHTML = '<p class="ps-hint">' + escapeHtml(tr("publisher.history_no_matches")) + "</p>";
      return;
    }
    posts.forEach(function (post) {
      var expanded = !!state.expandedPosts[post.id];
      var isDeleted = post.status === "deleted";
      var card = document.createElement("article");
      card.className = "ps-history-card ps-glass" +
        (expanded ? " is-expanded" : "") +
        (isDeleted ? " is-deleted" : "");
      card.setAttribute("data-post-id", String(post.id));

      var fullSnippet = plainText(post.text_html) || tr("publisher.no_text");
      var snippet = fullSnippet.length > 36 ? fullSnippet.slice(0, 36).trimEnd() + "…" : fullSnippet;
      var postIdHtml =
        '<span class="ps-history-post-id" title="ID ' + escapeHtml(String(post.id)) + '">#' +
        escapeHtml(String(post.id)) + "</span>";
      var tagsHtml = (post.tags || []).map(function (tag) {
        var cls = TAG_THEME[tag.color] || TAG_THEME.indigo;
        return '<span class="ps-tag-pill ' + cls + '"><span class="ps-tag-pill-name">' +
          escapeHtml(tag.name) + "</span></span>";
      }).join("");

      var statusHtml = "";
      var rightBadges = "";
      if (isDeleted) {
        statusHtml =
          '<span class="ps-status ps-status-deleted">' + escapeHtml(tr("publisher.status_deleted")) + "</span>";
        if (post.deleted_by === "auto" && post.deleted_at) {
          rightBadges =
            '<span class="ps-autodelete-badge ps-autodeleted-badge">' +
            "⏳ " + escapeHtml(tr("publisher.autodeleted_badge").replace("{when}", formatDateTime(post.deleted_at))) +
            "</span>";
        } else if (post.deleted_at) {
          rightBadges =
            '<span class="ps-deleted-when">' +
            escapeHtml(tr("publisher.deleted_at").replace("{when}", formatDateTime(post.deleted_at))) +
            "</span>";
        }
      } else {
        statusHtml =
          '<span class="ps-status ps-status-' + escapeHtml(post.status) + '">' +
          escapeHtml(statusLabel(post.status)) + "</span>";
        if (post.auto_delete_at) {
          rightBadges =
            '<span class="ps-autodelete-badge" title="' + escapeHtml(tr("publisher.autodelete_title")) + '">' +
            "⏳ " + escapeHtml(tr("publisher.autodelete_badge").replace("{when}", formatDateTime(post.auto_delete_at))) +
            "</span>";
        }
      }

      var actionsHtml = "";
      if (isDeleted) {
        actionsHtml =
          '<button type="button" class="db-btn-secondary" data-act="purge">' +
          escapeHtml(tr("publisher.remove_from_logs")) + "</button>";
      } else {
        actionsHtml =
          '<button type="button" class="db-btn-secondary" data-act="edit">' + escapeHtml(tr("publisher.edit")) + "</button>" +
          '<button type="button" class="db-btn-danger" data-act="delete">' + escapeHtml(tr("publisher.delete_now")) + "</button>" +
          '<button type="button" class="db-btn-secondary" data-act="autodelete">' + escapeHtml(tr("publisher.autodelete_update")) + "</button>";
      }

      var bodyHtml = "";
      if (expanded) {
        bodyHtml =
          '<div class="ps-history-body">' +
            '<div class="ps-hist-tg-bubble">' +
              historyMediaPreviewHtml(post.media_files) +
              '<div class="ps-tg-text ps-hist-tg-text">' +
                (previewHtml(post.text_html || "") ||
                  '<span class="ps-hist-empty">' + escapeHtml(tr("publisher.no_text")) + "</span>") +
              "</div>" +
              historyKeyboardPreviewHtml(post.inline_keyboard) +
            "</div>" +
            '<div class="ps-history-meta-row">' +
              '<span class="ps-hint">' + escapeHtml(post.channel_title || post.channel_id || "") + "</span>" +
            "</div>" +
            (post.error_message && !isDeleted
              ? '<div class="ps-hint ps-history-error">' + escapeHtml(post.error_message) + "</div>"
              : "") +
            '<div class="ps-history-actions">' + actionsHtml + "</div>" +
          "</div>";
      }

      card.innerHTML =
        '<div class="ps-history-head">' +
          '<div class="ps-history-head-left">' +
            statusHtml +
            '<span class="ps-history-title" title="' + escapeHtml(fullSnippet) + '">' +
              escapeHtml(snippet) + "</span>" +
          "</div>" +
          '<div class="ps-history-head-right">' +
            (tagsHtml ? '<div class="ps-history-head-tags">' + tagsHtml + "</div>" : "") +
            rightBadges +
            postIdHtml +
            '<button type="button" class="ps-history-chevron" data-act="toggle" aria-expanded="' +
            (expanded ? "true" : "false") + '">' + (expanded ? "▲" : "▼") + "</button>" +
          "</div>" +
        "</div>" +
        bodyHtml;

      card.querySelectorAll("[data-act]").forEach(function (btn) {
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          var act = btn.getAttribute("data-act");
          if (act === "toggle") {
            state.expandedPosts[post.id] = !state.expandedPosts[post.id];
            renderHistory();
          } else if (act === "edit") {
            if (post.status === "deleted") return;
            loadPostIntoEditor(post);
          } else if (act === "delete") {
            openDeleteModal(post, false);
          } else if (act === "purge") {
            openDeleteModal(post, true);
          } else if (act === "autodelete") {
            if (post.status === "deleted") return;
            openAutoDeleteModal(post);
          }
        });
      });
      card.querySelector(".ps-history-head").addEventListener("click", function (e) {
        if (e.target.closest("[data-act]")) return;
        state.expandedPosts[post.id] = !state.expandedPosts[post.id];
        renderHistory();
      });
      if (expanded) {
        card.querySelectorAll(".ps-hist-tg-text .tg-spoiler").forEach(function (sp) {
          sp.onclick = function (e) {
            e.stopPropagation();
            sp.classList.toggle("ps-spoiler-open");
          };
        });
      }
      root.appendChild(card);
    });
  }

  function openAutoDeleteModal(post) {
    state.autoDeleteTarget = post;
    var modal = el("ps-autodelete-modal");
    var input = el("ps-autodelete-modal-at");
    if (input) input.value = post.auto_delete_at ? toDatetimeLocalValue(post.auto_delete_at) : "";
    if (modal) modal.hidden = false;
  }

  function closeAutoDeleteModal() {
    state.autoDeleteTarget = null;
    var modal = el("ps-autodelete-modal");
    if (modal) modal.hidden = true;
  }

  function saveAutoDeleteModal() {
    var post = state.autoDeleteTarget;
    if (!post || !state.botId) return;
    var input = el("ps-autodelete-modal-at");
    var value = input && input.value ? Math.floor(new Date(input.value).getTime() / 1000) : null;
    api("/api/publisher/posts/" + post.id + "/auto-delete", {
      method: "PATCH",
      body: JSON.stringify({ bot_id: Number(state.botId), auto_delete_at: value }),
    })
      .then(function () {
        toast(tr("publisher.autodelete_saved"), "ok");
        closeAutoDeleteModal();
        refreshHistory();
      })
      .catch(function (err) { toast(err.message || String(err), "err"); });
  }

  function openDeleteModal(post, purge) {
    state.deleteTarget = post;
    state.deletePurge = !!purge;
    var title = el("ps-confirm-title");
    var text = el("ps-confirm-text");
    var ok = el("ps-confirm-ok");
    if (state.deletePurge) {
      if (title) title.textContent = tr("publisher.purge_title");
      if (text) text.textContent = tr("publisher.purge_text");
      if (ok) ok.textContent = tr("publisher.remove_from_logs");
    } else {
      if (title) title.textContent = tr("publisher.delete_title");
      if (text) text.textContent = tr("publisher.delete_text");
      if (ok) ok.textContent = tr("publisher.delete");
    }
    el("ps-confirm-modal").hidden = false;
  }

  function closeDeleteModal() {
    state.deleteTarget = null;
    state.deletePurge = false;
    el("ps-confirm-modal").hidden = true;
  }

  function confirmDelete() {
    var post = state.deleteTarget;
    if (!post || !state.botId) return;
    var purge = !!state.deletePurge;
    var url = "/api/publisher/posts/" + post.id + "?bot_id=" + encodeURIComponent(state.botId) +
      (purge ? "&purge=true" : "");
    api(url, { method: "DELETE" })
      .then(function () {
        toast(tr(purge ? "publisher.purged_ok" : "publisher.deleted_ok"), "ok");
        closeDeleteModal();
        if (state.editId === post.id) {
          startNewPost({ toast: false });
        }
        refreshHistory();
      })
      .catch(function (err) { toast(err.message || String(err), "err"); });
  }

  function loadBots() {
    return api("/api/publisher/bots").then(function (data) {
      var sel = el("ps-bot-select");
      sel.innerHTML = '<option value="">' + escapeHtml(tr("common.select_bot")) + "</option>";
      (data.bots || []).forEach(function (b) {
        var opt = document.createElement("option");
        opt.value = b.id;
        opt.textContent = b.name || ("Bot #" + b.id);
        sel.appendChild(opt);
      });
      try {
        var saved = localStorage.getItem("ps_bot_id");
        if (saved) sel.value = saved;
      } catch (e) {}
      if (sel.value) onBotChange(sel.value);
    });
  }

  function onBotChange(botId) {
    state.botId = botId ? Number(botId) : null;
    try { localStorage.setItem("ps_bot_id", botId || ""); } catch (e) {}
    var ch = el("ps-channel-select");
    ch.innerHTML = "";
    if (!state.botId) return;
    api("/api/publisher/" + state.botId + "/channels").then(function (data) {
      var channels = data.channels || [];
      if (!channels.length) {
        ch.innerHTML = '<option value="">' + escapeHtml(tr("publisher.no_channels")) + "</option>";
        return;
      }
      channels.forEach(function (c) {
        var opt = document.createElement("option");
        opt.value = String(c.chat_id);
        opt.textContent = (c.title || c.username || c.chat_id) + (c.username ? " @" + c.username : "");
        ch.appendChild(opt);
      });
      onChannelChange(ch.value);
    }).catch(function (err) { toast(err.message || String(err), "err"); });
  }

  function onChannelChange(cid) {
    state.channelId = cid || "";
    var sel = el("ps-channel-select");
    var opt = sel.options[sel.selectedIndex];
    state.channelTitle = opt ? opt.textContent : "";
    updatePreview();
  }

  function bind() {
    document.querySelectorAll(".ps-tab-btn").forEach(function (btn) {
      btn.onclick = function () { switchTab(btn.getAttribute("data-tab")); };
    });
    document.querySelectorAll(".ps-mode-btn").forEach(function (btn) {
      btn.onclick = function () { setMode(btn.getAttribute("data-mode")); };
    });
    document.querySelectorAll("#ps-editor-toolbar .ps-tool").forEach(function (btn) {
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault();
        saveSelection();
      });
      btn.addEventListener("click", function () {
        execCmd(btn.getAttribute("data-cmd"));
      });
    });
    var editor = el("ps-editor");
    if (editor) {
      editor.addEventListener("mouseup", saveSelection);
      editor.addEventListener("keyup", saveSelection);
      editor.addEventListener("input", function () {
        saveSelection();
        if (!state.syncingHtml) updatePreview();
      });
    }
    el("ps-html-input").addEventListener("input", function () {
      if (!state.syncingHtml) updatePreview();
    });
    el("ps-bot-select").onchange = function () { onBotChange(this.value); };
    el("ps-channel-select").onchange = function () { onChannelChange(this.value); };

    if (el("ps-link-apply")) el("ps-link-apply").onclick = applyLinkFromModal;
    if (el("ps-link-cancel")) el("ps-link-cancel").onclick = closeLinkModal;
    var linkModal = el("ps-link-modal");
    if (linkModal) {
      linkModal.querySelectorAll("[data-close]").forEach(function (n) {
        n.onclick = closeLinkModal;
      });
      var linkInput = el("ps-link-url");
      if (linkInput) {
        linkInput.addEventListener("keydown", function (e) {
          if (e.key === "Enter") {
            e.preventDefault();
            applyLinkFromModal();
          }
          if (e.key === "Escape") closeLinkModal();
        });
      }
    }

    var drop = el("ps-dropzone");
    var fileInput = el("ps-file-input");
    drop.onclick = function () { fileInput.click(); };
    drop.ondragover = function (e) { e.preventDefault(); drop.classList.add("ps-drop-active"); };
    drop.ondragleave = function () { drop.classList.remove("ps-drop-active"); };
    drop.ondrop = function (e) {
      e.preventDefault();
      drop.classList.remove("ps-drop-active");
      uploadFiles(e.dataTransfer.files);
    };
    fileInput.onchange = function () { uploadFiles(fileInput.files); fileInput.value = ""; };
    if (el("ps-add-media")) {
      el("ps-add-media").onclick = function () { fileInput.click(); };
    }
    if (el("ps-reorder-hint")) {
      el("ps-reorder-hint").onclick = function () {
        if (state.media.length < 2) return;
        toast(tr("publisher.reorder_hint"), "ok");
      };
    }
    if (el("ps-new-post")) {
      el("ps-new-post").onclick = function () {
        startNewPost();
      };
    }
    if (el("ps-clear-all")) {
      el("ps-clear-all").onclick = function () {
        startNewPost({ toastKey: "publisher.cleared" });
      };
    }
    document.querySelectorAll(".ps-section-toggle").forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.getAttribute("data-collapse");
        var section = btn.closest(".ps-section");
        if (!section) return;
        var open = !section.classList.contains("is-collapsed");
        section.classList.toggle("is-collapsed", open);
        btn.setAttribute("aria-expanded", open ? "false" : "true");
      };
    });

    el("ps-add-row").onclick = function () {
      state.keyboard.push([{ text: "", type: "url", value: "" }]);
      renderKeyboard();
      updatePreview();
    };

    el("ps-save-draft").onclick = function () {
      var body = currentPayload();
      if (!body.bot_id || !body.channel_id) return toast(tr("publisher.need_channel"), "err");
      api("/api/publisher/draft", { method: "POST", body: JSON.stringify(body) })
        .then(function (data) {
          toast(tr("publisher.draft_saved"), "ok");
          if (data.post) setEditMode(data.post);
        })
        .catch(function (err) { toast(err.message || String(err), "err"); });
    };

    el("ps-schedule").onclick = function () {
      var body = currentPayload();
      var local = el("ps-schedule-at").value;
      if (!local) return toast(tr("publisher.need_schedule"), "err");
      body.scheduled_at = Math.floor(new Date(local).getTime() / 1000);
      if (!body.bot_id || !body.channel_id) return toast(tr("publisher.need_channel"), "err");
      api("/api/publisher/schedule", { method: "POST", body: JSON.stringify(body) })
        .then(function (data) {
          toast(tr("publisher.scheduled_ok"), "ok");
          refreshHistory();
          startNewPost({ toast: false });
        })
        .catch(function (err) { toast(err.message || String(err), "err"); });
    };

    el("ps-send").onclick = function () {
      var body = currentPayload();
      if (!body.bot_id || !body.channel_id) return toast(tr("publisher.need_channel"), "err");
      api("/api/publisher/send-now", { method: "POST", body: JSON.stringify(body) })
        .then(function (data) {
          toast(tr("publisher.sent_ok"), "ok");
          refreshHistory();
          startNewPost({ toast: false });
        })
        .catch(function (err) { toast(err.message || String(err), "err"); });
    };

    el("ps-update-tg").onclick = function () {
      if (!state.editId) return;
      var body = currentPayload();
      api("/api/publisher/posts/" + state.editId, { method: "PUT", body: JSON.stringify(body) })
        .then(function () {
          toast(tr("publisher.updated_ok"), "ok");
          refreshHistory();
        })
        .catch(function (err) { toast(err.message || String(err), "err"); });
    };

    el("ps-refresh-history").onclick = refreshHistory;
    el("ps-confirm-cancel").onclick = closeDeleteModal;
    el("ps-confirm-ok").onclick = confirmDelete;
    el("ps-confirm-modal").querySelector("[data-close]").onclick = closeDeleteModal;

    if (el("ps-tag-add")) el("ps-tag-add").onclick = addTagFromInput;
    if (el("ps-tag-input")) {
      el("ps-tag-input").addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          addTagFromInput();
        }
      });
    }
    if (el("ps-autodelete-enabled")) {
      el("ps-autodelete-enabled").onchange = syncAutoDeleteUi;
    }
    if (el("ps-autodelete-at")) {
      el("ps-autodelete-at").addEventListener("input", syncAutoDeleteUi);
      el("ps-autodelete-at").addEventListener("change", syncAutoDeleteUi);
    }

    var search = el("ps-history-search");
    if (search) {
      search.addEventListener("input", function () {
        state.historyQuery = search.value || "";
        var q = state.historyQuery.trim().toLowerCase();
        if (!q || q !== String(state.historyTagFilter || "").toLowerCase()) {
          state.historyTagFilter = "";
        }
        renderHistory();
      });
    }
    if (el("ps-history-search-clear")) {
      el("ps-history-search-clear").onclick = function () {
        state.historyQuery = "";
        state.historyTagFilter = "";
        if (search) search.value = "";
        renderHistory();
      };
    }

    if (el("ps-autodelete-modal-cancel")) el("ps-autodelete-modal-cancel").onclick = closeAutoDeleteModal;
    if (el("ps-autodelete-modal-save")) el("ps-autodelete-modal-save").onclick = saveAutoDeleteModal;
    var adModal = el("ps-autodelete-modal");
    if (adModal) {
      adModal.querySelectorAll("[data-close]").forEach(function (n) {
        n.onclick = closeAutoDeleteModal;
      });
    }
  }

  function init() {
    state.apiOrigin = "";
    if (typeof applyI18n === "function") applyI18n(document);
    bind();
    renderTagColors();
    renderTagList();
    syncAutoDeleteUi();
    renderMedia();
    renderKeyboard();
    updatePreview();
    loadBots().catch(function (err) { toast(err.message || String(err), "err"); });
  }

  global.PostStudioView = { init: init };
})(window);
