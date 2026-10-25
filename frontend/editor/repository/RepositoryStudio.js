/**
 * RepositoryStudio — bot-scoped file explorer + multi-type FileViewer.
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

  function apiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    return (global.location && global.location.origin) || "http://127.0.0.1:8000";
  }

  function authHeaders(json) {
    var h = { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    try {
      var token =
        (global.localStorage &&
          (global.localStorage.getItem("access_token") ||
            global.localStorage.getItem("token"))) ||
        "";
      if (token) h.Authorization = "Bearer " + token;
    } catch (e) {}
    return h;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function svgIcon(name) {
    var c =
      ' width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    if (name === "file-plus") {
      return (
        "<svg" +
        c +
        '><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="12" y1="18" x2="12" y2="12"></line><line x1="9" y1="15" x2="15" y2="15"></line></svg>'
      );
    }
    if (name === "folder-plus") {
      return (
        "<svg" +
        c +
        '><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>'
      );
    }
    if (name === "upload") {
      return (
        "<svg" +
        c +
        '><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>'
      );
    }
    if (name === "refresh") {
      return (
        "<svg" +
        c +
        '><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>'
      );
    }
    if (name === "folder") {
      return (
        "<svg" +
        c +
        '><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>'
      );
    }
    if (name === "folder-open") {
      return (
        "<svg" +
        c +
        '><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><path d="M2 10h20"></path></svg>'
      );
    }
    if (name === "code") {
      return (
        "<svg" +
        c +
        '><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>'
      );
    }
    if (name === "image") {
      return (
        "<svg" +
        c +
        '><rect x="3" y="3" width="18" height="18" rx="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>'
      );
    }
    if (name === "log") {
      return (
        "<svg" +
        c +
        '><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="8" y1="13" x2="16" y2="13"></line><line x1="8" y1="17" x2="14" y2="17"></line></svg>'
      );
    }
    if (name === "db") {
      return (
        "<svg" +
        c +
        '><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"></path><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"></path></svg>'
      );
    }
    if (name === "file") {
      return (
        "<svg" +
        c +
        '><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>'
      );
    }
    if (name === "chevron") {
      return (
        "<svg" +
        c +
        ' class="rs-chevron"><polyline points="9 18 15 12 9 6"></polyline></svg>'
      );
    }
    if (name === "to-root") {
      return (
        "<svg" +
        c +
        '><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'
      );
    }
    return "";
  }

  function iconForNode(node) {
    if (!node) return svgIcon("file");
    if (node.type === "dir") return svgIcon("folder");
    var kind = node.kind || "";
    var ext = (node.ext || "").toLowerCase();
    if (kind === "image" || [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"].indexOf(ext) >= 0) {
      return svgIcon("image");
    }
    if (kind === "log" || ext === ".log") return svgIcon("log");
    if (kind === "database" || [".db", ".sqlite"].indexOf(ext) >= 0) return svgIcon("db");
    if (
      [".py", ".js", ".json", ".md", ".canvas", ".css", ".html", ".env", ".yaml", ".yml"].indexOf(
        ext
      ) >= 0
    ) {
      return svgIcon("code");
    }
    return svgIcon("file");
  }

  function parentDirOf(path) {
    var p = String(path || "");
    if (!p || p.indexOf("/") < 0) return "";
    return p.split("/").slice(0, -1).join("/");
  }

  function isCircularMove(sourcePath, targetDir, sourceIsDir) {
    if (!sourcePath) return true;
    if (sourcePath === targetDir) return true;
    if (
      sourceIsDir &&
      targetDir &&
      (targetDir === sourcePath || targetDir.indexOf(sourcePath + "/") === 0)
    ) {
      return true;
    }
    return false;
  }

  function isSameParentMove(sourcePath, targetDir) {
    return parentDirOf(sourcePath) === (targetDir || "");
  }

  function RepositoryStudio(opts) {
    this.botId = String((opts && opts.botId) || global.bot_id || "");
    this.rootEl = null;
    this.tree = null;
    this.expanded = { "": true };
    this.selectedPath = "";
    this.uploadFolder = "";
    this.viewer = null;
    this._ctx = null;
    this._inline = null;
    this._dragPath = null;
    this._dragIsDir = false;
    this._inlineCommiting = false;
    this._mounted = false;
    this._onDocClick = this._onDocClick.bind(this);
    this._onDocCtx = this._onDocCtx.bind(this);
  }

  RepositoryStudio.prototype.mount = function (root) {
    var self = this;
    var el =
      typeof root === "string"
        ? document.querySelector(root)
        : root || document.getElementById("rs-root");
    if (!el) return this;
    this.rootEl = el;
    this._mounted = true;
    el.classList.add("rs-root");
    el.innerHTML = this._shellHtml();
    this._bindShell();
    if (typeof global.FileViewer === "function") {
      this.viewer = new global.FileViewer({
        onSave: this._saveFile.bind(this),
      });
      this.viewer.mount(el.querySelector("#rs-viewer"));
    }
    document.addEventListener("click", this._onDocClick);
    document.addEventListener("contextmenu", this._onDocCtx);
    this._onRepositoryUpdated = function (ev) {
      if (!self._mounted) return;
      if (ev && ev.type === "workspace-updated" && !(ev.detail && ev.detail.refresh_repo)) return;
      // Both events can fire for one AI reply; coalesce into a single tree reload.
      clearTimeout(self._treeReloadTimer);
      self._treeReloadTimer = setTimeout(function () {
        if (self._mounted) self.reloadTree();
      }, 60);
    };
    window.addEventListener("repository-updated", this._onRepositoryUpdated);
    window.addEventListener("workspace-updated", this._onRepositoryUpdated);
    this.reloadTree();
    return this;
  };

  RepositoryStudio.prototype.destroy = function () {
    this._mounted = false;
    document.removeEventListener("click", this._onDocClick);
    document.removeEventListener("contextmenu", this._onDocCtx);
    if (this._onRepositoryUpdated) {
      window.removeEventListener("repository-updated", this._onRepositoryUpdated);
      window.removeEventListener("workspace-updated", this._onRepositoryUpdated);
      this._onRepositoryUpdated = null;
    }
    if (this._treeReloadTimer) {
      clearTimeout(this._treeReloadTimer);
      this._treeReloadTimer = null;
    }
    this._hideContext();
    if (this.viewer) {
      this.viewer.destroy();
      this.viewer = null;
    }
    if (this.rootEl) this.rootEl.innerHTML = "";
  };

  RepositoryStudio.prototype._shellHtml = function () {
    return (
      '<aside class="rs-sidebar">' +
      '<div class="rs-toolbar">' +
      '<button type="button" class="rs-tool" id="rs-new-file" title="' +
      escapeHtml(tr("repo.new_file", "New File")) +
      '">' +
      svgIcon("file-plus") +
      "<span>" +
      escapeHtml(tr("repo.new_file_short", "File")) +
      "</span></button>" +
      '<button type="button" class="rs-tool" id="rs-new-folder" title="' +
      escapeHtml(tr("repo.new_folder", "New Folder")) +
      '">' +
      svgIcon("folder-plus") +
      "<span>" +
      escapeHtml(tr("repo.new_folder_short", "Folder")) +
      "</span></button>" +
      '<button type="button" class="rs-tool" id="rs-upload" title="' +
      escapeHtml(tr("repo.upload", "Upload")) +
      '">' +
      svgIcon("upload") +
      "<span>" +
      escapeHtml(tr("repo.upload_short", "Upload")) +
      "</span></button>" +
      '<button type="button" class="rs-tool" id="rs-refresh" title="' +
      escapeHtml(tr("repo.refresh", "Refresh")) +
      '">' +
      svgIcon("refresh") +
      "</button>" +
      '<input type="file" id="rs-file-input" hidden multiple />' +
      "</div>" +
      '<div class="rs-tree-head">' +
      escapeHtml(tr("repo.explorer", "Files")) +
      "</div>" +
      '<div class="rs-tree-wrap" id="repo-tree-container">' +
      '<button type="button" class="rs-root-node tree-node-row" id="rs-root-node" ' +
      'data-path="" data-is-dir="true" data-parent-dir="" title="' +
      escapeHtml(tr("repo.root_hint", "Drop files here to move to project root")) +
      '">' +
      svgIcon("folder-open") +
      '<span class="rs-root-label">' +
      escapeHtml(tr("repo.root", "Root")) +
      "</span>" +
      '<span class="rs-root-slash">/</span>' +
      "</button>" +
      '<div class="rs-tree" id="repo-tree-background" role="tree"></div>' +
      "</div>" +
      '<div class="rs-status" id="rs-status"></div>' +
      "</aside>" +
      '<section class="rs-main">' +
      '<div id="rs-viewer" class="fv-root"></div>' +
      "</section>" +
      '<div class="rs-ctx" id="rs-ctx" hidden></div>'
    );
  };

  RepositoryStudio.prototype._bindShell = function () {
    var self = this;
    var newFile = document.getElementById("rs-new-file");
    var newFolder = document.getElementById("rs-new-folder");
    var upload = document.getElementById("rs-upload");
    var refresh = document.getElementById("rs-refresh");
    var input = document.getElementById("rs-file-input");

    if (newFile) {
      newFile.addEventListener("click", function () {
        self._createFile();
      });
    }
    if (newFolder) {
      newFolder.addEventListener("click", function () {
        self._createFolder();
      });
    }
    if (upload) {
      upload.addEventListener("click", function () {
        if (input) input.click();
      });
    }
    if (refresh) {
      refresh.addEventListener("click", function () {
        self.reloadTree();
      });
    }
    if (input) {
      input.addEventListener("change", function () {
        self._uploadFiles(input.files);
        input.value = "";
      });
    }
  };

  RepositoryStudio.prototype.setStatus = function (msg, isError) {
    var el = document.getElementById("rs-status");
    if (!el) return;
    el.textContent = msg || "";
    el.classList.toggle("is-error", !!isError);
  };

  RepositoryStudio.prototype._targetFolder = function () {
    var sel = this.selectedPath || "";
    if (!sel) return "";
    var node = this._findNode(sel);
    if (node && node.type === "dir") return sel;
    var parts = sel.split("/");
    parts.pop();
    return parts.join("/") || "";
  };

  RepositoryStudio.prototype._parentFolder = function () {
    return this._targetFolder();
  };

  RepositoryStudio.prototype._findNode = function (path, nodes) {
    var list = nodes || (this.tree && this.tree.children) || [];
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (n.path === path) return n;
      if (n.children) {
        var found = this._findNode(path, n.children);
        if (found) return found;
      }
    }
    return null;
  };

  RepositoryStudio.prototype._folderDepth = function (folderPath) {
    if (!folderPath) return 0;
    return folderPath.split("/").filter(Boolean).length;
  };

  RepositoryStudio.prototype.reloadTree = function () {
    var self = this;
    if (!this.botId) {
      this.setStatus(tr("editor.db.no_bot_id", "No bot_id in URL"), true);
      return Promise.resolve();
    }
    this.setStatus(tr("repo.loading", "Loading…"));
    return fetch(
      apiOrigin() +
        "/api/repository/tree?bot_id=" +
        encodeURIComponent(this.botId),
      { headers: authHeaders() }
    )
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.setStatus(
            (res.data && (res.data.detail || res.data.error)) ||
              tr("repo.load_error", "Failed to load tree"),
            true
          );
          return;
        }
        self.tree = res.data;
        self.setStatus(
          tr("repo.files_count", "{n} items").replace(
            "{n}",
            String(res.data.count || 0)
          )
        );
        self._renderTree();
      })
      .catch(function (err) {
        self.setStatus((err && err.message) || String(err), true);
      });
  };

  RepositoryStudio.prototype._applyTreeData = function (tree) {
    if (!tree) return;
    this.tree = tree;
    this.setStatus(
      tr("repo.files_count", "{n} items").replace(
        "{n}",
        String(tree.count || 0)
      )
    );
    this._renderTree();
  };

  RepositoryStudio.prototype._renderTree = function () {
    var host = document.getElementById("repo-tree-background");
    if (!host) return;
    var children = (this.tree && this.tree.children) || [];
    var html = "";
    if (!children.length && !(this._inline && this._inline.mode !== "rename")) {
      html =
        '<div class="rs-tree-empty">' +
        escapeHtml(tr("repo.tree_empty", "No files yet.")) +
        "</div>";
    } else {
      html = this._renderNodes(children, 0);
    }
    if (
      this._inline &&
      (this._inline.mode === "file" || this._inline.mode === "folder") &&
      !this._inline.folder
    ) {
      html =
        '<ul class="rs-node-list" role="group">' +
        this._inlineRowHtml(0) +
        "</ul>" +
        html;
    }
    host.innerHTML = html;
    this._bindTree(host);
    this._focusInlineInput();
  };

  RepositoryStudio.prototype._inlineRowHtml = function (depth) {
    var mode = this._inline && this._inline.mode;
    var placeholder =
      mode === "folder"
        ? tr("repo.prompt_folder", "New folder name")
        : mode === "rename"
          ? tr("repo.prompt_rename", "Rename to")
          : tr("repo.prompt_file", "New file name");
    var value = (this._inline && this._inline.value) || "";
    var ico =
      mode === "folder"
        ? svgIcon("folder")
        : mode === "rename"
          ? svgIcon("file")
          : svgIcon("code");
    return (
      '<li class="rs-node rs-inline-node" role="treeitem">' +
      '<div class="rs-node-row rs-inline-row" style="padding-left:' +
      (8 + depth * 14) +
      'px">' +
      '<span class="rs-twist rs-twist-spacer"></span>' +
      '<span class="rs-ico">' +
      ico +
      "</span>" +
      '<input type="text" class="tree-rename-input" spellcheck="false" placeholder="' +
      escapeHtml(placeholder) +
      '" value="' +
      escapeHtml(value) +
      '" />' +
      "</div></li>"
    );
  };

  RepositoryStudio.prototype._renderNodes = function (nodes, depth) {
    var self = this;
    var html = '<ul class="rs-node-list" role="group">';
    nodes.forEach(function (node) {
      var isDir = node.type === "dir";
      var expanded = !!self.expanded[node.path];
      var selected = self.selectedPath === node.path ? " is-selected" : "";
      var open = isDir && expanded ? " is-open" : "";
      var renaming =
        self._inline &&
        self._inline.mode === "rename" &&
        self._inline.path === node.path;

      html +=
        '<li class="rs-node' +
        open +
        '" role="treeitem" aria-expanded="' +
        (isDir ? (expanded ? "true" : "false") : "false") +
        '" data-rs-li-path="' +
        escapeHtml(node.path) +
        '">';

      if (renaming) {
        html +=
          '<div class="rs-node-row rs-inline-row" style="padding-left:' +
          (8 + depth * 14) +
          'px">' +
          (isDir
            ? '<span class="rs-twist">' + svgIcon("chevron") + "</span>"
            : '<span class="rs-twist rs-twist-spacer"></span>') +
          '<span class="rs-ico">' +
          iconForNode(node) +
          "</span>" +
          '<input type="text" class="tree-rename-input" spellcheck="false" value="' +
          escapeHtml(self._inline.value || node.name) +
          '" />' +
          "</div>";
      } else {
        var parent = parentDirOf(node.path);
        html +=
          '<button type="button" class="rs-node-row tree-node-row' +
          selected +
          '" draggable="true" data-path="' +
          escapeHtml(node.path) +
          '" data-is-dir="' +
          (isDir ? "true" : "false") +
          '" data-parent-dir="' +
          escapeHtml(parent) +
          '" data-rs-path="' +
          escapeHtml(node.path) +
          '" data-rs-type="' +
          escapeHtml(node.type) +
          '" style="padding-left:' +
          (8 + depth * 14) +
          'px">' +
          (isDir
            ? '<span class="rs-twist">' + svgIcon("chevron") + "</span>"
            : '<span class="rs-twist rs-twist-spacer"></span>') +
          '<span class="rs-ico">' +
          iconForNode(node) +
          "</span>" +
          '<span class="rs-name" title="' +
          escapeHtml(node.path) +
          '">' +
          escapeHtml(node.name) +
          "</span>" +
          (node.size_label
            ? '<span class="rs-size">' + escapeHtml(node.size_label) + "</span>"
            : "") +
          "</button>";
      }

      if (isDir && expanded) {
        var childHtml = "";
        if (
          self._inline &&
          (self._inline.mode === "file" || self._inline.mode === "folder") &&
          self._inline.folder === node.path
        ) {
          childHtml += self._inlineRowHtml(depth + 1);
        }
        if (node.children && node.children.length) {
          // Inject create row at top of children list
          var kids = self._renderNodes(node.children, depth + 1);
          if (childHtml) {
            kids = kids.replace(
              '<ul class="rs-node-list" role="group">',
              '<ul class="rs-node-list" role="group">' + childHtml
            );
            html += kids;
          } else {
            html += kids;
          }
        } else if (childHtml) {
          html +=
            '<ul class="rs-node-list" role="group">' + childHtml + "</ul>";
        } else {
          html +=
            '<ul class="rs-node-list"><li class="rs-tree-empty" style="padding-left:' +
            (24 + depth * 14) +
            'px">' +
            escapeHtml(tr("repo.folder_empty", "Empty")) +
            "</li></ul>";
        }
      }
      html += "</li>";
    });
    html += "</ul>";
    return html;
  };

  RepositoryStudio.prototype._focusInlineInput = function () {
    var input = this.rootEl && this.rootEl.querySelector(".tree-rename-input");
    if (!input) return;
    var self = this;
    global.setTimeout(function () {
      input.focus();
      input.select();
    }, 20);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        self._commitInline(input.value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        self._cancelInline();
      }
    });
    input.addEventListener("blur", function () {
      global.setTimeout(function () {
        if (self._inlineCommiting) return;
        if (self._inline) self._cancelInline();
      }, 120);
    });
    input.addEventListener("mousedown", function (e) {
      e.stopPropagation();
    });
    input.addEventListener("click", function (e) {
      e.stopPropagation();
    });
  };

  RepositoryStudio.prototype._startInlineCreate = function (mode) {
    var folder = this._targetFolder();
    if (folder) this.expanded[folder] = true;
    this._inline = {
      mode: mode === "folder" ? "folder" : "file",
      folder: folder,
      value: mode === "folder" ? "new-folder" : "untitled.py",
    };
    this._hideContext();
    this._renderTree();
  };

  RepositoryStudio.prototype._startInlineRename = function (path) {
    if (!path) return;
    var base = path.split("/").pop();
    this._inline = {
      mode: "rename",
      path: path,
      value: base,
    };
    this._hideContext();
    this._renderTree();
  };

  RepositoryStudio.prototype._cancelInline = function () {
    if (!this._inline) return;
    this._inline = null;
    this._renderTree();
  };

  RepositoryStudio.prototype._commitInline = function (rawName) {
    var self = this;
    var inline = this._inline;
    if (!inline || this._inlineCommiting) return;
    var name = String(rawName || "")
      .trim()
      .replace(/[\\\/]/g, "");
    if (!name || !/^[A-Za-z0-9._\- ()\[\]]+$/.test(name)) {
      this.setStatus(tr("repo.invalid_name", "Invalid name"), true);
      var input = this.rootEl && this.rootEl.querySelector(".tree-rename-input");
      if (input) input.focus();
      return;
    }

    this._inlineCommiting = true;

    if (inline.mode === "rename") {
      this._inline = null;
      fetch(apiOrigin() + "/api/repository/rename", {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          bot_id: Number(this.botId),
          path: inline.path,
          new_name: name,
        }),
      })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          self._inlineCommiting = false;
          if (!res.ok) {
            self.setStatus(
              (res.data && res.data.detail) ||
                tr("repo.rename_error", "Rename failed"),
              true
            );
            self._renderTree();
            return;
          }
          if (self.viewer) {
            self.viewer.renamePath(inline.path, res.data.path, res.data.name);
          }
          self.selectedPath = res.data.path;
          return self.reloadTree();
        })
        .catch(function (err) {
          self._inlineCommiting = false;
          self.setStatus((err && err.message) || String(err), true);
          self._renderTree();
        });
      return;
    }

    var folder = inline.folder || "";
    var path = folder ? folder + "/" + name : name;
    var isFolder = inline.mode === "folder";
    this._inline = null;

    var req = isFolder
      ? fetch(apiOrigin() + "/api/repository/folder", {
          method: "POST",
          headers: authHeaders(true),
          body: JSON.stringify({ bot_id: Number(this.botId), path: path }),
        })
      : fetch(apiOrigin() + "/api/repository/file", {
          method: "POST",
          headers: authHeaders(true),
          body: JSON.stringify({
            bot_id: Number(this.botId),
            path: path,
            content: "",
          }),
        });

    req
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        self._inlineCommiting = false;
        if (!res.ok) {
          self.setStatus(
            (res.data && res.data.detail) ||
              tr("repo.create_error", "Create failed"),
            true
          );
          self._renderTree();
          return;
        }
        if (folder) self.expanded[folder] = true;
        if (isFolder) self.expanded[path] = true;
        self.selectedPath = path;
        return self.reloadTree().then(function () {
          if (!isFolder) self.openFile(path);
        });
      })
      .catch(function (err) {
        self._inlineCommiting = false;
        self.setStatus((err && err.message) || String(err), true);
        self._renderTree();
      });
  };

  RepositoryStudio.prototype._bindTree = function (host) {
    var self = this;
    var container = document.getElementById("repo-tree-container");
    var rootNode = document.getElementById("rs-root-node");
    var background = document.getElementById("repo-tree-background") || host;

    // Click handlers on rows
    host.querySelectorAll(".tree-node-row[data-path]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        if (self._inline) return;
        var path = btn.getAttribute("data-path") || "";
        var isDir = btn.getAttribute("data-is-dir") === "true";
        self.selectedPath = path;
        if (isDir) {
          if (path) {
            self.expanded[path] = !self.expanded[path];
            self.uploadFolder = path;
          } else {
            self.uploadFolder = "";
          }
          self._renderTree();
          return;
        }
        self.uploadFolder = self._targetFolder();
        self._renderTree();
        self.openFile(path);
      });

      btn.addEventListener("dragstart", function (e) {
        var path = btn.getAttribute("data-path") || "";
        var isDir = btn.getAttribute("data-is-dir") === "true";
        self._dragPath = path;
        self._dragIsDir = isDir;
        try {
          e.dataTransfer.setData("text/plain", path);
          e.dataTransfer.setData(
            "application/json",
            JSON.stringify({ path: path, isDir: isDir })
          );
          e.dataTransfer.effectAllowed = "move";
        } catch (err) {}
        btn.classList.add("is-dragging");
        if (container) container.classList.add("is-dragging-active");
      });

      btn.addEventListener("dragend", function () {
        self._dragPath = null;
        self._dragIsDir = false;
        self._clearDropHover();
        if (container) container.classList.remove("is-dragging-active");
        document.querySelectorAll(".is-dragging").forEach(function (el) {
          el.classList.remove("is-dragging");
        });
      });

      // Per-row dragover / dragenter / drop with strict stopPropagation
      ["dragover", "dragenter"].forEach(function (evtName) {
        btn.addEventListener(evtName, function (e) {
          e.preventDefault();
          e.stopPropagation();
          self._onRowDragOver(e, btn);
        });
      });

      btn.addEventListener("dragleave", function (e) {
        e.stopPropagation();
        var related = e.relatedTarget;
        if (related && btn.contains(related)) return;
        btn.classList.remove("drop-target-active");
      });

      btn.addEventListener("drop", function (e) {
        e.preventDefault();
        e.stopPropagation();
        self._onRowDrop(e, btn);
      });
    });

    if (rootNode && !rootNode._rsClickBound) {
      rootNode._rsClickBound = true;
      rootNode.addEventListener("click", function () {
        self.selectedPath = "";
        self.uploadFolder = "";
        self._renderTree();
      });
      ["dragover", "dragenter"].forEach(function (evtName) {
        rootNode.addEventListener(evtName, function (e) {
          e.preventDefault();
          e.stopPropagation();
          self._onRowDragOver(e, rootNode);
        });
      });
      rootNode.addEventListener("dragleave", function (e) {
        e.stopPropagation();
        if (e.relatedTarget && rootNode.contains(e.relatedTarget)) return;
        rootNode.classList.remove("drop-target-active");
      });
      rootNode.addEventListener("drop", function (e) {
        e.preventDefault();
        e.stopPropagation();
        self._onRowDrop(e, rootNode);
      });
      rootNode.addEventListener("dragend", function () {
        self._clearDropHover();
      });
    }

    // Background = root fallback (only if child rows did not stopPropagation)
    if (background && !background._rsBgDropBound) {
      background._rsBgDropBound = true;
      background.addEventListener("dragover", function (e) {
        var source = self._dragPath || self._peekDragPath(e);
        if (!source) return;
        // If over a tree-node-row, that row handles it
        if (e.target.closest && e.target.closest(".tree-node-row")) return;
        e.preventDefault();
        if (isSameParentMove(source, "")) {
          try {
            e.dataTransfer.dropEffect = "none";
          } catch (err) {}
          self._clearDropHover();
          return;
        }
        try {
          e.dataTransfer.dropEffect = "move";
        } catch (err) {}
        self._clearDropHover();
        background.classList.add("root-drop-active");
        if (container) container.classList.add("root-drop-active");
      });
      background.addEventListener("dragleave", function (e) {
        if (e.relatedTarget && background.contains(e.relatedTarget)) return;
        background.classList.remove("root-drop-active");
        if (container) container.classList.remove("root-drop-active");
      });
      background.addEventListener("drop", function (e) {
        if (e.target.closest && e.target.closest(".tree-node-row")) return;
        e.preventDefault();
        self._clearDropHover();
        var source = self._dragPath || self._readDragPath(e) || "";
        self._dragPath = null;
        if (container) container.classList.remove("is-dragging-active");
        if (!source) return;
        self._movePath(source, "");
      });
    }
  };

  RepositoryStudio.prototype._resolveEffectiveTarget = function (row) {
    if (!row) return "";
    var isDir = row.getAttribute("data-is-dir") === "true";
    if (isDir) return row.getAttribute("data-path") || "";
    return row.getAttribute("data-parent-dir") || "";
  };

  RepositoryStudio.prototype._highlightTargetFolder = function (targetDir) {
    this._clearDropHover();
    if (!this.rootEl) return;
    if (!targetDir) {
      var rootNode = document.getElementById("rs-root-node");
      if (rootNode) rootNode.classList.add("drop-target-active");
      return;
    }
    var rows = this.rootEl.querySelectorAll('.tree-node-row[data-is-dir="true"]');
    for (var i = 0; i < rows.length; i++) {
      if ((rows[i].getAttribute("data-path") || "") === targetDir) {
        rows[i].classList.add("drop-target-active");
        return;
      }
    }
  };

  RepositoryStudio.prototype._onRowDragOver = function (e, row) {
    var source = this._dragPath || this._peekDragPath(e);
    if (!source) return;
    var sourceIsDir = !!this._dragIsDir;
    var targetDir = this._resolveEffectiveTarget(row);

    if (
      isCircularMove(source, targetDir, sourceIsDir) ||
      isSameParentMove(source, targetDir)
    ) {
      try {
        e.dataTransfer.dropEffect = "none";
      } catch (err) {}
      this._clearDropHover();
      return;
    }

    try {
      e.dataTransfer.dropEffect = "move";
    } catch (err) {}
    this._highlightTargetFolder(targetDir);
  };

  RepositoryStudio.prototype._onRowDrop = function (e, row) {
    this._clearDropHover();
    var source = this._dragPath || this._readDragPath(e) || "";
    var sourceIsDir = !!this._dragIsDir;
    this._dragPath = null;
    this._dragIsDir = false;
    var container = document.getElementById("repo-tree-container");
    if (container) container.classList.remove("is-dragging-active");
    if (!source) return;

    var targetDir = this._resolveEffectiveTarget(row);
    if (
      isCircularMove(source, targetDir, sourceIsDir) ||
      isSameParentMove(source, targetDir)
    ) {
      return;
    }
    this._movePath(source, targetDir);
  };

  RepositoryStudio.prototype._peekDragPath = function (e) {
    // During dragover, getData is empty in many browsers — rely on _dragPath
    return this._dragPath || "";
  };

  RepositoryStudio.prototype._readDragPath = function (e) {
    try {
      var raw = (e.dataTransfer && e.dataTransfer.getData("text/plain")) || "";
      if (raw) return raw;
      var json = e.dataTransfer && e.dataTransfer.getData("application/json");
      if (json) {
        var parsed = JSON.parse(json);
        return (parsed && parsed.path) || "";
      }
    } catch (err) {}
    return this._dragPath || "";
  };

  RepositoryStudio.prototype._clearDropHover = function () {
    if (!this.rootEl) return;
    this.rootEl
      .querySelectorAll(
        ".drop-target-active, .root-drop-active, .drag-hover, .root-drop-hover"
      )
      .forEach(function (el) {
        el.classList.remove("drop-target-active");
        el.classList.remove("root-drop-active");
        el.classList.remove("drag-hover");
        el.classList.remove("root-drop-hover");
      });
  };

  RepositoryStudio.prototype._movePath = function (sourcePath, targetFolder) {
    var self = this;
    if (!sourcePath) return;
    if (targetFolder == null || targetFolder === "/" || targetFolder === ".") {
      targetFolder = "";
    }
    if (isCircularMove(sourcePath, targetFolder, true)) {
      this.setStatus(
        tr("repo.move_into_self", "Cannot move a folder into itself"),
        true
      );
      return;
    }
    if (isSameParentMove(sourcePath, targetFolder)) {
      this.setStatus(tr("repo.already_in_folder", "Already in this folder"));
      return;
    }

    this.setStatus(tr("repo.moving", "Moving…"));
    fetch(apiOrigin() + "/api/repository/move", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        bot_id: Number(this.botId),
        source_path: sourcePath,
        target_dir: targetFolder,
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.setStatus(
            (res.data && res.data.detail) || tr("repo.move_error", "Move failed"),
            true
          );
          return;
        }
        if (self.viewer && res.data.path && res.data.source_path) {
          self.viewer.renamePath(
            res.data.source_path,
            res.data.path,
            res.data.name
          );
        }
        self.selectedPath = res.data.path || sourcePath;
        if (targetFolder) self.expanded[targetFolder] = true;
        if (res.data.tree) {
          self._applyTreeData(res.data.tree);
        } else {
          return self.reloadTree();
        }
        if (res.data.moved === false) {
          self.setStatus(tr("repo.already_in_folder", "Already in this folder"));
        } else {
          self.setStatus(
            tr("repo.moved", "Moved") + ": " + (res.data.path || sourcePath)
          );
        }
      })
      .catch(function (err) {
        self.setStatus((err && err.message) || String(err), true);
      });
  };

  RepositoryStudio.prototype.openFile = function (path) {
    var self = this;
    if (!path || !this.botId) return;
    this.setStatus(tr("repo.opening", "Opening…"));
    fetch(
      apiOrigin() +
        "/api/repository/file?bot_id=" +
        encodeURIComponent(this.botId) +
        "&path=" +
        encodeURIComponent(path),
      { headers: authHeaders() }
    )
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.setStatus(
            (res.data && (res.data.detail || res.data.error)) ||
              tr("repo.open_error", "Failed to open file"),
            true
          );
          return;
        }
        if (self.viewer) self.viewer.open(res.data);
        self.setStatus(res.data.path || path);
      })
      .catch(function (err) {
        self.setStatus((err && err.message) || String(err), true);
      });
  };

  RepositoryStudio.prototype._saveFile = function (path, content) {
    var self = this;
    return fetch(apiOrigin() + "/api/repository/file", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        bot_id: Number(this.botId),
        path: path,
        content: content,
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.setStatus(
            (res.data && (res.data.detail || res.data.error)) ||
              tr("repo.save_error", "Save failed"),
            true
          );
          return false;
        }
        self.setStatus(tr("repo.saved", "Saved") + ": " + path);
        return true;
      })
      .catch(function (err) {
        self.setStatus((err && err.message) || String(err), true);
        return false;
      });
  };

  RepositoryStudio.prototype._createFile = function () {
    this._startInlineCreate("file");
  };

  RepositoryStudio.prototype._createFolder = function () {
    this._startInlineCreate("folder");
  };

  RepositoryStudio.prototype._uploadFiles = function (fileList) {
    var self = this;
    if (!fileList || !fileList.length) return;
    var folder = this._targetFolder() || "assets";
    this.uploadFolder = folder;
    var chain = Promise.resolve();
    Array.prototype.forEach.call(fileList, function (file) {
      chain = chain.then(function () {
        var fd = new FormData();
        fd.append("bot_id", String(self.botId));
        fd.append("folder", folder || "assets");
        fd.append("file", file, file.name);
        return fetch(apiOrigin() + "/api/repository/upload", {
          method: "POST",
          headers: authHeaders(),
          body: fd,
        })
          .then(function (r) {
            return r.json().then(function (data) {
              return { ok: r.ok, data: data };
            });
          })
          .then(function (res) {
            if (!res.ok) {
              self.setStatus(
                (res.data && res.data.detail) ||
                  tr("repo.upload_error", "Upload failed"),
                true
              );
              return;
            }
            self.setStatus(
              tr("repo.uploaded", "Uploaded") + ": " + (res.data.path || file.name)
            );
            if (folder) self.expanded[folder] = true;
            else self.expanded.assets = true;
            self.selectedPath = res.data.path;
            return self.reloadTree().then(function () {
              if (res.data.path) self.openFile(res.data.path);
            });
          });
      });
    });
    chain.catch(function (err) {
      self.setStatus((err && err.message) || String(err), true);
    });
  };

  RepositoryStudio.prototype._deletePath = function (path) {
    var self = this;
    if (!path) return;
    if (
      !global.confirm(
        tr("repo.confirm_delete", "Delete this item?") + "\n" + path
      )
    ) {
      return;
    }
    fetch(apiOrigin() + "/api/repository/file", {
      method: "DELETE",
      headers: authHeaders(true),
      body: JSON.stringify({ bot_id: Number(this.botId), path: path }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          self.setStatus(
            (res.data && res.data.detail) ||
              tr("repo.delete_error", "Delete failed"),
            true
          );
          return;
        }
        if (self.viewer) self.viewer.close(path);
        if (self.selectedPath === path) self.selectedPath = "";
        return self.reloadTree();
      })
      .catch(function (err) {
        self.setStatus((err && err.message) || String(err), true);
      });
  };

  RepositoryStudio.prototype._renamePath = function (path) {
    this._startInlineRename(path);
  };

  RepositoryStudio.prototype._copyPath = function (path) {
    var text = path || "";
    var self = this;
    function done() {
      self.setStatus(tr("repo.path_copied", "Path copied") + ": " + text);
    }
    if (
      global.navigator &&
      global.navigator.clipboard &&
      global.navigator.clipboard.writeText
    ) {
      global.navigator.clipboard
        .writeText(text)
        .then(done)
        .catch(function () {
          fallback(text);
          done();
        });
    } else {
      fallback(text);
      done();
    }
    function fallback(t) {
      try {
        var ta = document.createElement("textarea");
        ta.value = t;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } catch (e) {}
    }
  };

  RepositoryStudio.prototype._showContext = function (x, y, path, type) {
    var menu = document.getElementById("rs-ctx");
    if (!menu) return;
    var self = this;
    this._ctx = { path: path, type: type };
    var nested = !!(path && path.indexOf("/") >= 0);
    menu.hidden = false;
    menu.innerHTML =
      '<button type="button" data-rs-act="open">' +
      escapeHtml(tr("repo.ctx.open", "Open in Tab")) +
      "</button>" +
      '<button type="button" data-rs-act="new-file">' +
      escapeHtml(tr("repo.new_file", "New File")) +
      "</button>" +
      '<button type="button" data-rs-act="new-folder">' +
      escapeHtml(tr("repo.new_folder", "New Folder")) +
      "</button>" +
      (nested
        ? '<button type="button" data-rs-act="to-root" class="rs-ctx-move">' +
          svgIcon("to-root") +
          "<span>" +
          escapeHtml(tr("repo.ctx.to_root", "Move to Root")) +
          "</span></button>"
        : "") +
      '<button type="button" data-rs-act="rename">' +
      escapeHtml(tr("repo.ctx.rename", "Rename")) +
      "</button>" +
      '<button type="button" data-rs-act="delete">' +
      escapeHtml(tr("repo.ctx.delete", "Delete")) +
      "</button>" +
      '<button type="button" data-rs-act="copy">' +
      escapeHtml(tr("repo.ctx.copy", "Copy Relative Path")) +
      "</button>";
    menu.style.left = Math.min(x, global.innerWidth - 200) + "px";
    menu.style.top = Math.min(y, global.innerHeight - 220) + "px";
    menu.querySelectorAll("[data-rs-act]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var act = btn.getAttribute("data-rs-act");
        var p = self._ctx && self._ctx.path;
        var t = self._ctx && self._ctx.type;
        self._hideContext();
        if (act === "new-file") {
          if (p) {
            self.selectedPath = p;
            if (t === "dir") self.expanded[p] = true;
          }
          self._startInlineCreate("file");
          return;
        }
        if (act === "new-folder") {
          if (p) {
            self.selectedPath = p;
            if (t === "dir") self.expanded[p] = true;
          }
          self._startInlineCreate("folder");
          return;
        }
        if (act === "to-root") {
          if (p) self._movePath(p, "");
          return;
        }
        if (!p) return;
        if (act === "open") {
          if (t === "dir") {
            self.expanded[p] = true;
            self.selectedPath = p;
            self._renderTree();
          } else {
            self.openFile(p);
          }
        } else if (act === "rename") {
          self._renamePath(p);
        } else if (act === "delete") {
          self._deletePath(p);
        } else if (act === "copy") {
          self._copyPath(p);
        }
      });
    });
  };

  RepositoryStudio.prototype._hideContext = function () {
    var menu = document.getElementById("rs-ctx");
    if (menu) {
      menu.hidden = true;
      menu.innerHTML = "";
    }
    this._ctx = null;
  };

  RepositoryStudio.prototype._onDocClick = function (e) {
    if (e.target && e.target.closest && e.target.closest(".tree-rename-input")) {
      return;
    }
    if (e.target && e.target.closest && e.target.closest("#rs-ctx")) {
      return;
    }
    this._hideContext();
  };

  RepositoryStudio.prototype._onDocCtx = function (e) {
    if (!this.rootEl || !this.rootEl.contains(e.target)) return;
    if (e.target.closest && e.target.closest(".tree-rename-input")) return;
    var row = e.target.closest(".tree-node-row");
    if (!row || row.getAttribute("data-path") == null) {
      this._hideContext();
      return;
    }
    e.preventDefault();
    var path = row.getAttribute("data-path") || "";
    var type = row.getAttribute("data-is-dir") === "true" ? "dir" : "file";
    // Root header has empty path — skip context on root chrome
    if (row.id === "rs-root-node") {
      this._hideContext();
      return;
    }
    this.selectedPath = path;
    this._showContext(e.clientX, e.clientY, path, type);
  };

  global.RepositoryStudio = RepositoryStudio;
})(typeof window !== "undefined" ? window : this);
