/**
 * FileViewer — multi-tab viewer for code, images, and logs inside RepositoryStudio.
 */
(function (global) {
  "use strict";

  function tr(key, fallback) {
    if (typeof global.t === "function") {
      var v = global.t(key);
      if (v && v !== key) return v;
    }
    return fallback || key;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function svg(name) {
    var c =
      ' width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    if (name === "close") {
      return "<svg" + c + '><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
    }
    if (name === "search") {
      return (
        "<svg" +
        c +
        '><circle cx="11" cy="11" r="7"></circle><line x1="16.65" y1="16.65" x2="21" y2="21"></line></svg>'
      );
    }
    if (name === "save") {
      return (
        "<svg" +
        c +
        '><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>'
      );
    }
    if (name === "wrap") {
      return (
        "<svg" +
        c +
        '><path d="M3 6h18M3 12h12a3 3 0 0 1 0 6h-3"></path><polyline points="15 15 12 18 15 21"></polyline></svg>'
      );
    }
    if (name === "scroll") {
      return (
        "<svg" +
        c +
        '><polyline points="7 13 12 18 17 13"></polyline><polyline points="7 6 12 11 17 6"></polyline></svg>'
      );
    }
    return "";
  }

  /* Lightweight syntax highlight — returns HTML (escaped text + spans) */
  function highlightCode(text, ext) {
    var src = String(text == null ? "" : text);
    var escaped = escapeHtml(src);
    var e = (ext || "").toLowerCase();
    if (e === ".json") {
      return escaped.replace(
        /(&quot;[^&]*&quot;)(\s*:)?|(\btrue\b|\bfalse\b|\bnull\b)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
        function (m, str, colon, lit, num) {
          if (str) {
            return (
              '<span class="fv-tok-str">' +
              str +
              "</span>" +
              (colon || "")
            );
          }
          if (lit) return '<span class="fv-tok-kw">' + lit + "</span>";
          if (num) return '<span class="fv-tok-num">' + num + "</span>";
          return m;
        }
      );
    }
    if (e === ".py" || e === ".js" || e === ".ts") {
      return escaped
        .replace(
          /(#.*$|\/\/.*$)/gm,
          '<span class="fv-tok-cmt">$1</span>'
        )
        .replace(
          /(&quot;[^&]*&quot;|&#39;[^&]*&#39;|`[^`]*`)/g,
          '<span class="fv-tok-str">$1</span>'
        )
        .replace(
          /\b(def|class|return|import|from|as|if|elif|else|for|while|try|except|finally|with|yield|async|await|pass|break|continue|raise|True|False|None|and|or|not|in|is|lambda|global|nonlocal|function|const|let|var|new|this)\b/g,
          '<span class="fv-tok-kw">$1</span>'
        );
    }
    if (e === ".md") {
      return escaped
        .replace(/^(#{1,6}\s.+)$/gm, '<span class="fv-tok-kw">$1</span>')
        .replace(/(`[^`]+`)/g, '<span class="fv-tok-str">$1</span>');
    }
    return escaped;
  }

  function FileViewer(opts) {
    this.host = null;
    this.tabs = [];
    this.activePath = null;
    this.onSave = (opts && opts.onSave) || null;
    this.onTabsChange = (opts && opts.onTabsChange) || null;
    this._keyBound = false;
    this._onKey = this._onKey.bind(this);
    this._findQuery = "";
    this._findIndex = 0;
    this._findCase = false;
    this._findMatches = [];
    this._findOpen = false;
  }

  FileViewer.prototype.mount = function (host) {
    this.host = typeof host === "string" ? document.querySelector(host) : host;
    if (!this.host) return this;
    this.host.classList.add("fv-root");
    this.host.innerHTML =
      '<div class="fv-tabs" id="fv-tabs"></div>' +
      '<div class="fv-body" id="fv-body"></div>';
    if (!this._keyBound) {
      document.addEventListener("keydown", this._onKey, true);
      this._keyBound = true;
    }
    this.render();
    return this;
  };

  FileViewer.prototype.destroy = function () {
    if (this._keyBound) {
      document.removeEventListener("keydown", this._onKey, true);
      this._keyBound = false;
    }
    if (this.host) this.host.innerHTML = "";
    this.tabs = [];
    this.activePath = null;
  };

  FileViewer.prototype._onKey = function (e) {
    if (!this.host || !this.host.offsetParent) return;
    var key = (e.key || "").toLowerCase();
    var findOpen = !!(this.host.querySelector(".fv-find-bar.is-open"));
    if (key === "escape" && findOpen) {
      e.preventDefault();
      this.closeFind();
      return;
    }
    if (key === "f3") {
      if (!this._findQuery) return;
      e.preventDefault();
      if (e.shiftKey) this.findPrev();
      else this.findNext();
      return;
    }
    if (!(e.ctrlKey || e.metaKey)) return;
    if (key === "f") {
      e.preventDefault();
      e.stopPropagation();
      if (this._findOpen) {
        var findInput = this.host.querySelector("#fv-find-input");
        if (findInput) findInput.focus();
      } else {
        this.openFind();
      }
      return;
    }
    if (key !== "s") return;
    var tab = this.getActive();
    if (!tab || !tab.editable) return;
    e.preventDefault();
    e.stopPropagation();
    this.saveActive();
  };

  FileViewer.prototype.getActive = function () {
    var self = this;
    return this.tabs.find(function (t) {
      return t.path === self.activePath;
    });
  };

  FileViewer.prototype.open = function (file) {
    if (!file || !file.path) return;
    var existing = this.tabs.find(function (t) {
      return t.path === file.path;
    });
    if (existing) {
      existing.meta = Object.assign({}, existing.meta, file);
      if (file.content != null && !existing.dirty) {
        existing.content = file.content;
        existing.savedContent = file.content;
      }
      this.activePath = existing.path;
      this.render();
      return existing;
    }
    var kind = file.kind || "text";
    var editable = !!file.editable && (kind === "text" || kind === "log");
    var tab = {
      path: file.path,
      name: file.name || file.path.split("/").pop(),
      kind: kind,
      ext: file.ext || "",
      size: file.size || 0,
      size_label: file.size_label || "",
      mime: file.mime || "",
      content: file.content,
      savedContent: file.content,
      editable: editable,
      dirty: false,
      wordWrap: kind === "log",
      autoScroll: kind === "log",
      meta: file,
    };
    this.tabs.push(tab);
    this.activePath = tab.path;
    this.render();
    if (typeof this.onTabsChange === "function") this.onTabsChange(this.tabs);
    return tab;
  };

  FileViewer.prototype.close = function (path) {
    var idx = this.tabs.findIndex(function (t) {
      return t.path === path;
    });
    if (idx < 0) return;
    var wasActive = this.activePath === path;
    this.tabs.splice(idx, 1);
    if (wasActive) {
      var next = this.tabs[idx] || this.tabs[idx - 1] || null;
      this.activePath = next ? next.path : null;
    }
    this.render();
    if (typeof this.onTabsChange === "function") this.onTabsChange(this.tabs);
  };

  FileViewer.prototype.renamePath = function (oldPath, newPath, newName) {
    var tab = this.tabs.find(function (t) {
      return t.path === oldPath;
    });
    if (!tab) return;
    tab.path = newPath;
    tab.name = newName || newPath.split("/").pop();
    if (this.activePath === oldPath) this.activePath = newPath;
    this.renderTabs();
  };

  FileViewer.prototype.render = function () {
    this.renderTabs();
    this.renderBody();
  };

  FileViewer.prototype.renderTabs = function () {
    var bar = this.host && this.host.querySelector("#fv-tabs");
    if (!bar) return;
    var self = this;
    if (!this.tabs.length) {
      bar.innerHTML = "";
      return;
    }
    bar.innerHTML = this.tabs
      .map(function (t) {
        var active = t.path === self.activePath ? " is-active" : "";
        var dirty = t.dirty ? " is-dirty" : "";
        return (
          '<div class="fv-tab' +
          active +
          dirty +
          '" data-fv-path="' +
          escapeHtml(t.path) +
          '" title="' +
          escapeHtml(t.path) +
          '">' +
          '<button type="button" class="fv-tab-label">' +
          escapeHtml(t.name) +
          (t.dirty ? " •" : "") +
          "</button>" +
          '<button type="button" class="fv-tab-close" data-fv-close="' +
          escapeHtml(t.path) +
          '" title="' +
          escapeHtml(tr("repo.close", "Close")) +
          '">' +
          svg("close") +
          "</button></div>"
        );
      })
      .join("");

    bar.querySelectorAll(".fv-tab").forEach(function (el) {
      el.addEventListener("click", function (e) {
        if (e.target.closest("[data-fv-close]")) return;
        self.activePath = el.getAttribute("data-fv-path");
        self.render();
      });
    });
    bar.querySelectorAll("[data-fv-close]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var p = btn.getAttribute("data-fv-close");
        var tab = self.tabs.find(function (t) {
          return t.path === p;
        });
        if (tab && tab.dirty) {
          if (
            !global.confirm(
              tr("repo.unsaved", "Discard unsaved changes?")
            )
          ) {
            return;
          }
        }
        self.close(p);
      });
    });
  };

  FileViewer.prototype.renderBody = function () {
    var body = this.host && this.host.querySelector("#fv-body");
    if (!body) return;
    var tab = this.getActive();
    if (!tab) {
      body.innerHTML =
        '<div class="fv-empty">' +
        escapeHtml(
          tr("repo.viewer_empty", "Open a file from the repository tree.")
        ) +
        "</div>";
      return;
    }
    if (tab.kind === "image") {
      this._renderImage(body, tab);
      return;
    }
    if (tab.content == null && tab.kind === "binary") {
      body.innerHTML =
        '<div class="fv-empty">' +
        escapeHtml(
          tr("repo.binary", "Binary file — preview not available.")
        ) +
        "</div>";
      return;
    }
    if (tab.kind === "log" || tab.ext === ".log" || tab.ext === ".txt") {
      this._renderLog(body, tab);
      return;
    }
    this._renderCode(body, tab);
  };

  FileViewer.prototype._renderCode = function (body, tab) {
    var self = this;
    var lines = String(tab.content == null ? "" : tab.content).split("\n");
    var lineHtml = lines
      .map(function (_, i) {
        return '<span class="fv-ln">' + (i + 1) + "</span>";
      })
      .join("");
    var highlighted = highlightCode(tab.content, tab.ext);
    body.innerHTML =
      '<div class="fv-code-toolbar">' +
      '<span class="fv-meta">' +
      escapeHtml(tab.path) +
      (tab.size_label ? " · " + escapeHtml(tab.size_label) : "") +
      (tab.dirty ? " · " + escapeHtml(tr("repo.modified", "Modified")) : "") +
      "</span>" +
      '<div class="fv-log-actions">' +
      this._findBarHtml() +
      '<button type="button" class="fv-tool-btn fv-icon-btn" id="fv-find-btn" title="Ctrl+F" aria-label="' +
      escapeHtml(tr("repo.find", "Find")) +
      '">' +
      svg("search") +
      "</button>" +
      '<button type="button" class="fv-tool-btn" id="fv-save-btn"' +
      (tab.editable ? "" : " disabled") +
      ">" +
      svg("save") +
      "<span>" +
      escapeHtml(tr("repo.save", "Save")) +
      "</span></button></div></div>" +
      '<div class="fv-code-wrap">' +
      '<div class="fv-gutter" aria-hidden="true">' +
      lineHtml +
      "</div>" +
      '<div class="fv-code-pane">' +
      '<pre class="fv-code-pre" id="fv-code-pre">' +
      highlighted +
      "</pre>" +
      '<textarea class="fv-code-input" id="fv-code-input" spellcheck="false"' +
      (tab.editable ? "" : " readonly") +
      ">" +
      escapeHtml(tab.content == null ? "" : tab.content) +
      "</textarea></div></div>";

    var input = body.querySelector("#fv-code-input");
    var pre = body.querySelector("#fv-code-pre");
    var gutter = body.querySelector(".fv-gutter");
    var pane = body.querySelector(".fv-code-pane");

    function syncScroll() {
      if (pre) pre.scrollTop = input.scrollTop;
      if (pre) pre.scrollLeft = input.scrollLeft;
      if (gutter) gutter.scrollTop = input.scrollTop;
    }
    if (input) {
      input.addEventListener("scroll", syncScroll);
      input.addEventListener("input", function () {
        tab.content = input.value;
        tab.dirty = tab.content !== tab.savedContent;
        if (pre) pre.innerHTML = highlightCode(tab.content, tab.ext);
        if (self._findQuery) self.runFind(self._findQuery, { keepIndex: true });
        var newLines = tab.content.split("\n");
        if (gutter) {
          gutter.innerHTML = newLines
            .map(function (_, i) {
              return '<span class="fv-ln">' + (i + 1) + "</span>";
            })
            .join("");
        }
        self.renderTabs();
      });
      // Match textarea height to content min
      input.style.height = "100%";
    }
    var saveBtn = body.querySelector("#fv-save-btn");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        self.saveActive();
      });
    }
    var findBtn = body.querySelector("#fv-find-btn");
    if (findBtn) {
      findBtn.addEventListener("click", function () {
        if (self._findOpen) self.closeFind();
        else self.openFind();
      });
    }
    this._bindFindBar(body);
    if (this._findOpen) {
      this._setFindOpen(true);
      if (this._findQuery) this.runFind(this._findQuery, { keepIndex: true, keepFocus: true });
    }
  };

  FileViewer.prototype._renderImage = function (body, tab) {
    body.innerHTML =
      '<div class="fv-img-toolbar">' +
      '<span class="fv-meta" id="fv-img-meta">' +
      escapeHtml(tab.path) +
      (tab.size_label ? " · " + escapeHtml(tab.size_label) : "") +
      "</span></div>" +
      '<div class="fv-img-stage">' +
      '<img class="fv-img" id="fv-img" alt="' +
      escapeHtml(tab.name) +
      '" src="' +
      escapeHtml(tab.content || "") +
      '" /></div>';
    var img = body.querySelector("#fv-img");
    var meta = body.querySelector("#fv-img-meta");
    if (img && meta) {
      img.addEventListener("load", function () {
        var w = img.naturalWidth || 0;
        var h = img.naturalHeight || 0;
        meta.textContent =
          tab.path +
          (tab.size_label ? " · " + tab.size_label : "") +
          (w && h ? " · " + w + " × " + h : "");
      });
    }
  };

  FileViewer.prototype._renderLog = function (body, tab) {
    var self = this;
    body.innerHTML =
      '<div class="fv-log-toolbar">' +
      '<span class="fv-meta">' +
      escapeHtml(tab.path) +
      (tab.size_label ? " · " + escapeHtml(tab.size_label) : "") +
      "</span>" +
      '<div class="fv-log-actions">' +
      '<button type="button" class="fv-tool-btn' +
      (tab.autoScroll ? " is-on" : "") +
      '" id="fv-autoscroll">' +
      svg("scroll") +
      "<span>" +
      escapeHtml(tr("repo.autoscroll", "Auto-scroll")) +
      "</span></button>" +
      '<button type="button" class="fv-tool-btn' +
      (tab.wordWrap ? " is-on" : "") +
      '" id="fv-wrap">' +
      svg("wrap") +
      "<span>" +
      escapeHtml(tr("repo.wordwrap", "Word wrap")) +
      "</span></button>" +
      (tab.editable
        ? '<button type="button" class="fv-tool-btn" id="fv-save-btn">' +
          svg("save") +
          "<span>" +
          escapeHtml(tr("repo.save", "Save")) +
          "</span></button>"
        : "") +
      "</div></div>" +
      '<pre class="fv-log-view' +
      (tab.wordWrap ? " is-wrap" : "") +
      '" id="fv-log-view" contenteditable="' +
      (tab.editable ? "true" : "false") +
      '" spellcheck="false">' +
      escapeHtml(tab.content == null ? "" : tab.content) +
      "</pre>";

    var view = body.querySelector("#fv-log-view");
    var autoBtn = body.querySelector("#fv-autoscroll");
    var wrapBtn = body.querySelector("#fv-wrap");
    var saveBtn = body.querySelector("#fv-save-btn");

    if (tab.autoScroll && view) {
      view.scrollTop = view.scrollHeight;
    }
    if (autoBtn) {
      autoBtn.addEventListener("click", function () {
        tab.autoScroll = !tab.autoScroll;
        autoBtn.classList.toggle("is-on", tab.autoScroll);
        if (tab.autoScroll && view) view.scrollTop = view.scrollHeight;
      });
    }
    if (wrapBtn) {
      wrapBtn.addEventListener("click", function () {
        tab.wordWrap = !tab.wordWrap;
        wrapBtn.classList.toggle("is-on", tab.wordWrap);
        if (view) view.classList.toggle("is-wrap", tab.wordWrap);
      });
    }
    if (view && tab.editable) {
      view.addEventListener("input", function () {
        tab.content = view.innerText;
        tab.dirty = tab.content !== tab.savedContent;
        self.renderTabs();
      });
    }
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        self.saveActive();
      });
    }
  };

  FileViewer.prototype._findBarHtml = function () {
    return (
      '<div class="fv-find-bar" id="fv-find-bar">' +
      '<input type="text" class="fv-find-input" id="fv-find-input" autocomplete="off" spellcheck="false" placeholder="' +
      escapeHtml(tr("repo.find_placeholder", "Find in file")) +
      '" />' +
      '<span class="fv-find-count" id="fv-find-count"></span>' +
      '<button type="button" class="fv-tool-btn fv-icon-btn" id="fv-find-prev" title="Shift+F3" aria-label="' +
      escapeHtml(tr("repo.find_prev", "Prev")) +
      '">&#9650;</button>' +
      '<button type="button" class="fv-tool-btn fv-icon-btn" id="fv-find-next" title="F3" aria-label="' +
      escapeHtml(tr("repo.find_next", "Next")) +
      '">&#9660;</button></div>'
    );
  };

  FileViewer.prototype._setFindOpen = function (open) {
    this._findOpen = !!open;
    var bar = this.host && this.host.querySelector(".fv-find-bar");
    var btn = this.host && this.host.querySelector("#fv-find-btn");
    if (bar) bar.classList.toggle("is-open", this._findOpen);
    if (btn) {
      btn.innerHTML = this._findOpen ? svg("close") : svg("search");
      var label = this._findOpen
        ? tr("repo.close", "Close")
        : tr("repo.find", "Find");
      btn.title = this._findOpen ? "Esc" : "Ctrl+F";
      btn.setAttribute("aria-label", label);
      btn.classList.toggle("is-on", this._findOpen);
    }
  };

  FileViewer.prototype._bindFindBar = function (body) {
    var self = this;
    var input = body.querySelector("#fv-find-input");
    var prev = body.querySelector("#fv-find-prev");
    var next = body.querySelector("#fv-find-next");
    if (input) {
      input.value = this._findQuery || "";
      input.addEventListener("input", function () {
        self.runFind(input.value, { keepFocus: true });
      });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          if (e.shiftKey) self.findPrev();
          else self.findNext();
        }
        if (e.key === "Escape") {
          e.preventDefault();
          self.closeFind();
        }
        e.stopPropagation();
      });
    }
    if (prev) prev.addEventListener("click", function () { self.findPrev(); });
    if (next) next.addEventListener("click", function () { self.findNext(); });
  };

  FileViewer.prototype.openFind = function () {
    var input = this.host && this.host.querySelector("#fv-find-input");
    this._setFindOpen(true);
    if (input) {
      input.focus();
      if (input.value) this.runFind(input.value, { keepIndex: true, keepFocus: true });
    }
  };

  FileViewer.prototype.closeFind = function () {
    this._setFindOpen(false);
    this._findQuery = "";
    this._findIndex = 0;
    this._findMatches = [];
    var tab = this.getActive();
    var pre = this.host && this.host.querySelector("#fv-code-pre");
    if (tab && pre) pre.innerHTML = highlightCode(tab.content, tab.ext);
    var count = this.host && this.host.querySelector("#fv-find-count");
    if (count) count.textContent = "";
    var findInput = this.host && this.host.querySelector("#fv-find-input");
    if (findInput) findInput.value = "";
    var input = this.host && this.host.querySelector("#fv-code-input");
    if (input) input.focus();
  };

  FileViewer.prototype.runFind = function (query, opts) {
    opts = opts || {};
    this._findQuery = String(query || "");
    var tab = this.getActive();
    var pre = this.host && this.host.querySelector("#fv-code-pre");
    var input = this.host && this.host.querySelector("#fv-code-input");
    var count = this.host && this.host.querySelector("#fv-find-count");
    if (!tab || !pre) return;
    pre.innerHTML = highlightCode(tab.content, tab.ext);
    this._findMatches = [];
    var q = this._findQuery;
    if (!q) {
      if (count) count.textContent = "";
      return;
    }
    var text = String(tab.content == null ? "" : tab.content);
    var hay = text.toLowerCase();
    var needle = q.toLowerCase();
    var from = 0;
    while (from <= hay.length - needle.length) {
      var at = hay.indexOf(needle, from);
      if (at < 0) break;
      this._findMatches.push({ start: at, end: at + q.length });
      from = at + (q.length || 1);
    }
    if (!this._findMatches.length) {
      this._findIndex = 0;
      if (count) count.textContent = tr("repo.find_no_results", "No results");
      return;
    }
    if (!opts.keepIndex || this._findIndex >= this._findMatches.length) {
      this._findIndex = 0;
    }
    this._paintFindHits(pre);
    this._revealFindMatch(input, this._findMatches[this._findIndex], opts);
    if (count) {
      count.textContent = tr("repo.find_results", "{current} of {total}")
        .replace("{current}", String(this._findIndex + 1))
        .replace("{total}", String(this._findMatches.length));
    }
  };

  FileViewer.prototype._paintFindHits = function (pre) {
    var q = this._findQuery;
    if (!q || !pre) return;
    var current = this._findIndex;
    var seq = 0;
    var escNeedle = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    var re = new RegExp(escNeedle, "gi");
    function wrapText(node) {
      var value = node.nodeValue;
      if (!value || !re.test(value)) {
        re.lastIndex = 0;
        return;
      }
      re.lastIndex = 0;
      var frag = document.createDocumentFragment();
      var last = 0;
      var m;
      while ((m = re.exec(value))) {
        if (m.index > last) frag.appendChild(document.createTextNode(value.slice(last, m.index)));
        var mark = document.createElement("mark");
        mark.className = "fv-find-hit" + (seq === current ? " is-current" : "");
        mark.textContent = m[0];
        frag.appendChild(mark);
        seq += 1;
        last = m.index + m[0].length;
        if (!m[0].length) re.lastIndex += 1;
      }
      if (last < value.length) frag.appendChild(document.createTextNode(value.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
    var walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(wrapText);
  };

  FileViewer.prototype._revealFindMatch = function (input, match, opts) {
    opts = opts || {};
    if (!match) return;
    if (input) {
      var text = input.value || "";
      var before = text.slice(0, match.start);
      var line = before.split("\n").length;
      input.scrollTop = Math.max(0, (line - 4) * 18);
      var pre = this.host && this.host.querySelector("#fv-code-pre");
      if (pre) {
        pre.scrollTop = input.scrollTop;
        pre.scrollLeft = input.scrollLeft;
      }
    }
    var cur = this.host && this.host.querySelector(".fv-find-hit.is-current");
    if (cur && cur.scrollIntoView) {
      cur.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    if (!opts.keepFocus && input) {
      try {
        input.focus();
        input.setSelectionRange(match.start, match.end);
      } catch (e) {}
    }
  };

  FileViewer.prototype.findNext = function () {
    if (!this._findMatches.length) {
      this.runFind(this._findQuery, { keepFocus: true });
      return;
    }
    this._findIndex = (this._findIndex + 1) % this._findMatches.length;
    this.runFind(this._findQuery, { keepIndex: true, keepFocus: true });
  };

  FileViewer.prototype.findPrev = function () {
    if (!this._findMatches.length) {
      this.runFind(this._findQuery, { keepFocus: true });
      return;
    }
    this._findIndex =
      (this._findIndex - 1 + this._findMatches.length) % this._findMatches.length;
    this.runFind(this._findQuery, { keepIndex: true, keepFocus: true });
  };

  FileViewer.prototype.saveActive = function () {
    var tab = this.getActive();
    if (!tab || !tab.editable) return Promise.resolve();
    var self = this;
    if (typeof this.onSave !== "function") return Promise.resolve();
    return Promise.resolve(this.onSave(tab.path, tab.content)).then(function (ok) {
      if (ok === false) return;
      tab.savedContent = tab.content;
      tab.dirty = false;
      self.renderTabs();
      var meta = self.host && self.host.querySelector(".fv-meta");
      if (meta && tab.kind !== "image") {
        meta.textContent =
          tab.path +
          (tab.size_label ? " · " + tab.size_label : "") +
          " · " +
          tr("repo.saved", "Saved");
      }
    });
  };

  global.FileViewer = FileViewer;
})(typeof window !== "undefined" ? window : this);
