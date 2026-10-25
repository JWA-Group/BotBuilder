/**
 * Bot Workspace chrome — top mode header + collapsible repository drawer.
 * Modes: scenario | repository | database | run
 * Ctrl/Cmd+B toggles drawer overlay without leaving scenario mode.
 */
(function (global) {
  "use strict";

  var MODE_SCENARIO = "scenario";
  var MODE_REPO = "repository";
  var MODE_DB = "database";
  var MODE_RUN = "run";

  var REPO_TREE = [
    { folder: "Project" },
    { id: "scenario.json", label: "scenario.json", kind: "file" },
    { id: "main.py", label: "main.py", kind: "file" },
    { id: "config.json", label: "config.json", kind: "file" },
    { id: "user_data.db", label: "user_data.db", kind: "db" },
    { folder: "Runtime" },
    { id: "launcher.log", label: "launcher.log", kind: "log" },
    { id: "media/", label: "media/", kind: "folder" },
  ];

  function tr(key, fallback) {
    if (typeof global.t === "function") {
      var v = global.t(key);
      if (v && v !== key) return v;
    }
    return fallback || key;
  }

  function apiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    return global.location && global.location.origin
      ? global.location.origin
      : "http://127.0.0.1:8000";
  }

  function authHeaders() {
    var h = {};
    try {
      var token =
        (global.localStorage && global.localStorage.getItem("access_token")) ||
        (global.localStorage && global.localStorage.getItem("token")) ||
        "";
      if (token) h.Authorization = "Bearer " + token;
    } catch (e) {}
    return h;
  }

  function svgIcon(name) {
    var common =
      ' width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    if (name === "back") {
      return (
        "<svg" +
        common +
        '><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>'
      );
    }
    if (name === "scenario") {
      return (
        "<svg" +
        common +
        '><rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="3" y="14" width="7" height="7" rx="1"></rect><rect x="14" y="14" width="7" height="7" rx="1"></rect></svg>'
      );
    }
    if (name === "repo") {
      return (
        "<svg" +
        common +
        '><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>'
      );
    }
    if (name === "db") {
      return (
        "<svg" +
        common +
        '><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"></path><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"></path></svg>'
      );
    }
    if (name === "run") {
      return (
        "<svg" +
        common +
        '><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>'
      );
    }
    if (name === "ai") {
      return (
        "<svg" +
        common +
        '><path d="M12 2l1.8 5.5L19 9.3l-5.2 1.8L12 17l-1.8-5.9L5 9.3l5.2-1.8L12 2z"></path><circle cx="19" cy="18" r="2"></circle></svg>'
      );
    }
    if (name === "settings") {
      return (
        "<svg" +
        common +
        '><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c0 .7.4 1.3 1 1.5H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"></path></svg>'
      );
    }
    if (name === "file") {
      return (
        "<svg" +
        common +
        '><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>'
      );
    }
    return "";
  }

  function WorkspaceChrome(opts) {
    this.botId = (opts && opts.botId) || global.bot_id || "";
    this.mode = MODE_SCENARIO;
    this.drawerPinned = false;
    this.drawerOverlay = false;
    this._statusTimer = null;
    this._bound = false;
  }

  WorkspaceChrome.prototype.mount = function () {
    if (this._bound) return this;
    this._bound = true;
    document.body.classList.add("ws-ready", "ws-mode-scenario");
    this._ensureDom();
    this._bindEvents();
    this._applyChrome();
    this.refreshBotMeta();
    this.refreshStatus();
    this._statusTimer = global.setInterval(
      function () {
        this.refreshStatus();
      }.bind(this),
      5000
    );
    return this;
  };

  WorkspaceChrome.prototype._ensureDom = function () {
    if (document.getElementById("ws-header")) return;

    var editor = document.getElementById("editor");
    if (!editor) return;

    function modeBtn(mode, icon, label) {
      return (
        '<button type="button" class="ws-mode-btn' +
        (mode === MODE_SCENARIO ? " is-active" : "") +
        '" data-ws-mode="' +
        mode +
        '" role="tab" aria-selected="' +
        (mode === MODE_SCENARIO ? "true" : "false") +
        '">' +
        svgIcon(icon) +
        '<span class="ws-mode-label">' +
        escapeHtml(label) +
        "</span></button>"
      );
    }

    function stagePanel(mode, title, lead, bodyHtml) {
      if (mode === MODE_DB || mode === MODE_RUN || mode === MODE_REPO) {
        return (
          '<div class="ws-stage-panel ws-stage-panel--flush" data-ws-stage="' +
          mode +
          '">' +
          bodyHtml +
          "</div>"
        );
      }
      return (
        '<div class="ws-stage-panel" data-ws-stage="' +
        mode +
        '">' +
        (title
          ? '<h2 class="ws-stage-title">' + escapeHtml(title) + "</h2>"
          : "") +
        (lead ? '<p class="ws-stage-lead">' + escapeHtml(lead) + "</p>" : "") +
        bodyHtml +
        "</div>"
      );
    }

    var header = document.createElement("header");
    header.id = "ws-header";
    header.innerHTML =
      '<div class="ws-header-left">' +
      '<a class="ws-back-btn" id="ws-back-btn" href="/bots/index.html">' +
      svgIcon("back") +
      '<span class="ws-back-label">' +
      escapeHtml(tr("editor.back_short", "Back to bots")) +
      "</span></a>" +
      '<div class="ws-bot-meta">' +
      '<span class="ws-bot-name" id="ws-bot-name">' +
      escapeHtml(tr("editor.bot_untitled", "Bot")) +
      "</span>" +
      '<span class="ws-status-pill" id="ws-status-pill" title="">' +
      '<span class="ws-status-dot" aria-hidden="true"></span>' +
      '<span id="ws-status-label">' +
      escapeHtml(tr("bots.status_stopped", "Stopped")) +
      "</span></span>" +
      "</div></div>" +
      '<div class="ws-header-center" role="tablist" aria-label="Workspace modes">' +
      '<div class="ws-mode-seg">' +
      modeBtn(MODE_SCENARIO, "scenario", tr("workspace.mode.scenario", "Scenario")) +
      modeBtn(MODE_REPO, "repo", tr("workspace.mode.repository", "Repository")) +
      modeBtn(MODE_DB, "db", tr("workspace.mode.database", "Database")) +
      modeBtn(MODE_RUN, "run", tr("workspace.mode.run", "Run & Logs")) +
      "</div></div>" +
      '<div class="ws-header-right">' +
      '<button type="button" class="ws-icon-btn" id="ws-ai-btn" title="' +
      escapeAttr(tr("ai.title", "AI Copilot")) +
      '">' +
      svgIcon("ai") +
      "<span>" +
      escapeHtml(tr("editor.ai", "AI")) +
      "</span></button>" +
      '<button type="button" class="ws-icon-btn" id="ws-settings-btn" title="' +
      escapeAttr(tr("settings.title", "Settings")) +
      '">' +
      svgIcon("settings") +
      "<span>" +
      escapeHtml(tr("workspace.settings", "Settings")) +
      "</span></button>" +
      "</div>";

    var shell = document.createElement("div");
    shell.id = "ws-shell";

    var drawer = document.createElement("aside");
    drawer.id = "ws-drawer";
    drawer.setAttribute("aria-hidden", "true");
    drawer.innerHTML =
      '<div id="ws-drawer-inner">' +
      '<div class="ws-drawer-head">' +
      '<span class="ws-drawer-title" id="ws-drawer-title">' +
      escapeHtml(tr("workspace.drawer.repo", "Repository")) +
      "</span>" +
      '<span class="ws-drawer-hint" id="ws-drawer-hint">Ctrl+B</span>' +
      "</div>" +
      '<div class="ws-drawer-body" id="ws-drawer-body"></div>' +
      "</div>";

    var main = document.createElement("div");
    main.id = "ws-main";

    var stage = document.createElement("div");
    stage.id = "ws-stage";
    stage.innerHTML =
      stagePanel(MODE_REPO, "", "", '<div id="rs-root" class="rs-root"></div>') +
      stagePanel(MODE_DB, "", "", '<div id="ds-root" class="ds-root"></div>') +
      stagePanel(MODE_RUN, "", "", '<div id="rl-root" class="rl-root"></div>');


    var parent = editor.parentNode;
    parent.insertBefore(header, editor);
    parent.insertBefore(shell, editor);
    shell.appendChild(drawer);
    shell.appendChild(main);
    main.appendChild(editor);
    main.appendChild(stage);

    var ai = document.getElementById("ai-sidebar");
    if (ai && ai.parentNode !== document.body) {
      document.body.appendChild(ai);
    }
  };

  WorkspaceChrome.prototype._bindEvents = function () {
    var self = this;
    document.querySelectorAll("[data-ws-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        self.setMode(btn.getAttribute("data-ws-mode"));
      });
    });

    var aiBtn = document.getElementById("ws-ai-btn");
    if (aiBtn) {
      aiBtn.addEventListener("click", function () {
        if (global.aiPanel && typeof global.aiPanel.toggle === "function") {
          global.aiPanel.toggle();
        }
      });
    }

    var settingsBtn = document.getElementById("ws-settings-btn");
    if (settingsBtn) {
      settingsBtn.addEventListener("click", function () {
        if (global.electronAPI && typeof global.electronAPI.openSettings === "function") {
          global.electronAPI.openSettings();
          return;
        }
        global.location.href = "/setup/settings.html";
      });
    }

    document.addEventListener("keydown", function (e) {
      var key = (e.key || "").toLowerCase();
      if ((e.ctrlKey || e.metaKey) && key === "b") {
        var tag = (e.target && e.target.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) {
          return;
        }
        e.preventDefault();
        self.toggleDrawerOverlay();
      }
    });

    var dbLink = document.getElementById("ws-open-db-link");
    if (dbLink && this.botId) {
      dbLink.href = "/database/?bot_id=" + encodeURIComponent(this.botId);
    }
  };

  WorkspaceChrome.prototype.setMode = function (mode) {
    var next = mode || MODE_SCENARIO;
    if (
      next !== MODE_SCENARIO &&
      next !== MODE_REPO &&
      next !== MODE_DB &&
      next !== MODE_RUN
    ) {
      next = MODE_SCENARIO;
    }
    this.mode = next;
    // Leaving overlay when changing modes
    this.drawerOverlay = false;
    this.drawerPinned = false;
    this._applyChrome();
    if (next === MODE_REPO) this._mountRepositoryStudio();
    if (next === MODE_DB) this._mountDatabaseStudio();
    if (next === MODE_RUN) this._mountRunLogsStudio();
    if (next !== MODE_RUN && this._runStudio) {
      this._runStudio.destroy();
      this._runStudio = null;
    }
    if (next !== MODE_REPO && this._repoStudio) {
      this._repoStudio.destroy();
      this._repoStudio = null;
    }
  };

  WorkspaceChrome.prototype._mountRepositoryStudio = function () {
    var root = document.getElementById("rs-root");
    if (!root) return;
    if (typeof global.RepositoryStudio !== "function") {
      root.innerHTML =
        '<div class="ws-stage-card" style="margin:20px">RepositoryStudio failed to load.</div>';
      return;
    }
    if (this._repoStudio) {
      this._repoStudio.destroy();
      this._repoStudio = null;
    }
    this._repoStudio = new global.RepositoryStudio({ botId: this.botId });
    this._repoStudio.mount(root);
  };

  WorkspaceChrome.prototype._mountDatabaseStudio = function () {
    var root = document.getElementById("ds-root");
    if (!root) return;
    if (typeof global.DatabaseStudio !== "function") {
      root.innerHTML =
        '<div class="ws-stage-card" style="margin:20px">DatabaseStudio failed to load.</div>';
      return;
    }
    if (!this._dbStudio) {
      this._dbStudio = new global.DatabaseStudio({ botId: this.botId });
    } else {
      this._dbStudio.botId = this.botId;
    }
    this._dbStudio.mount(root);
  };

  WorkspaceChrome.prototype._mountRunLogsStudio = function () {
    var root = document.getElementById("rl-root");
    if (!root) return;
    if (typeof global.RunLogsStudio !== "function") {
      root.innerHTML =
        '<div class="ws-stage-card" style="margin:20px">RunLogsStudio failed to load.</div>';
      return;
    }
    if (this._runStudio) {
      this._runStudio.destroy();
      this._runStudio = null;
    }
    this._runStudio = new global.RunLogsStudio({ botId: this.botId });
    this._runStudio.mount(root);
    this.refreshStatus();
  };

  WorkspaceChrome.prototype.toggleDrawerOverlay = function () {
    if (this.mode !== MODE_SCENARIO) {
      // In non-scenario modes drawer is already pinned — Ctrl+B returns to scenario overlay toggle semantics
      this.setMode(MODE_SCENARIO);
      this.drawerOverlay = true;
      this._renderRepoDrawer();
      this._applyChrome();
      return;
    }
    this.drawerOverlay = !this.drawerOverlay;
    if (this.drawerOverlay) this._renderRepoDrawer();
    this._applyChrome();
  };

  WorkspaceChrome.prototype._applyChrome = function () {
    var body = document.body;
    body.classList.toggle("ws-mode-scenario", this.mode === MODE_SCENARIO);
    body.classList.toggle("ws-mode-repository", this.mode === MODE_REPO);
    body.classList.toggle("ws-mode-database", this.mode === MODE_DB);
    body.classList.toggle("ws-mode-run", this.mode === MODE_RUN);

    var drawerOpen =
      this.drawerPinned || (this.mode === MODE_SCENARIO && this.drawerOverlay);
    body.classList.toggle("ws-drawer-open", drawerOpen && !this.drawerOverlay);
    body.classList.toggle("ws-drawer-overlay", !!this.drawerOverlay);

    var drawer = document.getElementById("ws-drawer");
    if (drawer) drawer.setAttribute("aria-hidden", drawerOpen || this.drawerOverlay ? "false" : "true");

    document.querySelectorAll("[data-ws-mode]").forEach(function (btn) {
      var on = btn.getAttribute("data-ws-mode") === this.mode;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }, this);

    document.querySelectorAll("[data-ws-stage]").forEach(function (panel) {
      panel.classList.toggle(
        "is-active",
        panel.getAttribute("data-ws-stage") === this.mode
      );
    }, this);

    var title = document.getElementById("ws-drawer-title");
    if (title) {
      title.textContent = tr("workspace.drawer.repo", "Repository");
    }

    var hint = document.getElementById("ws-drawer-hint");
    if (hint) {
      hint.textContent =
        this.mode === MODE_SCENARIO
          ? tr("workspace.drawer.overlay_hint", "Ctrl+B")
          : "";
    }

    // Notify canvas to reflow after layout change
    try {
      global.dispatchEvent(new Event("resize"));
    } catch (e) {}
  };

  WorkspaceChrome.prototype._renderRepoDrawer = function () {
    var body = document.getElementById("ws-drawer-body");
    if (!body) return;
    var self = this;
    var html = '<ul class="ws-tree">';
    REPO_TREE.forEach(function (item) {
      if (item.folder) {
        html +=
          '<li class="ws-tree-folder">' + escapeHtml(item.folder) + "</li>";
        return;
      }
      html +=
        '<li><button type="button" class="ws-tree-item" data-ws-file="' +
        escapeAttr(item.id) +
        '">' +
        svgIcon("file") +
        "<span>" +
        escapeHtml(item.label) +
        "</span></button></li>";
    });
    html += "</ul>";
    body.innerHTML = html;
    body.querySelectorAll("[data-ws-file]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        body.querySelectorAll(".ws-tree-item").forEach(function (el) {
          el.classList.remove("is-active");
        });
        btn.classList.add("is-active");
        var id = btn.getAttribute("data-ws-file");
        var detail = document.getElementById("ws-repo-detail");
        if (detail) {
          detail.textContent =
            tr("workspace.repo.selected", "Selected") + ": " + id +
            (self.botId ? "  ·  bot_" + self.botId : "");
        }
        if (self.mode === MODE_SCENARIO && self.drawerOverlay) {
          /* stay overlay; detail only visible in repo mode */
        } else if (self.mode !== MODE_REPO) {
          self.setMode(MODE_REPO);
        }
      });
    });
  };

  WorkspaceChrome.prototype._renderDbDrawer = function () {
    var body = document.getElementById("ws-drawer-body");
    if (!body) return;
    var self = this;
    body.innerHTML =
      '<p class="ws-drawer-hint" style="padding:6px 4px">' +
      escapeHtml(tr("workspace.db.loading", "Loading tables…")) +
      "</p>";
    if (!this.botId) {
      body.innerHTML =
        "<p class=\"ws-drawer-hint\" style=\"padding:6px 4px\">" +
        escapeHtml(tr("editor.db.no_bot_id", "No bot_id in URL")) +
        "</p>";
      return;
    }
    fetch(apiOrigin() + "/api/projects/" + encodeURIComponent(this.botId) + "/db/tables", {
      headers: authHeaders(),
    })
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        var tables = Array.isArray(data)
          ? data
          : data.tables || data.items || [];
        if (!tables.length) {
          body.innerHTML =
            '<p class="ws-drawer-hint" style="padding:6px 4px">' +
            escapeHtml(tr("workspace.db.empty", "No tables found.")) +
            "</p>";
          return;
        }
        var html = '<ul class="ws-table-list">';
        tables.forEach(function (t) {
          var name = typeof t === "string" ? t : t.name || t.table || String(t);
          html +=
            '<li><button type="button" class="ws-table-item" data-ws-table="' +
            escapeAttr(name) +
            '">' +
            svgIcon("db") +
            "<span>" +
            escapeHtml(name) +
            "</span></button></li>";
        });
        html += "</ul>";
        body.innerHTML = html;
        body.querySelectorAll("[data-ws-table]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            body.querySelectorAll(".ws-table-item").forEach(function (el) {
              el.classList.remove("is-active");
            });
            btn.classList.add("is-active");
            var name = btn.getAttribute("data-ws-table");
            var detail = document.getElementById("ws-db-detail");
            if (detail) {
              detail.innerHTML =
                "<strong>" +
                escapeHtml(name) +
                "</strong><br><span style=\"color:var(--text-muted);font-size:12px\">" +
                escapeHtml(
                  tr(
                    "workspace.db.hint",
                    "Use Database Manager for the full grid and ERD tools."
                  )
                ) +
                "</span>";
            }
          });
        });
      })
      .catch(function () {
        body.innerHTML =
          '<p class="ws-drawer-hint" style="padding:6px 4px">' +
          escapeHtml(tr("workspace.db.error", "Could not load tables.")) +
          "</p>";
      });
  };

  WorkspaceChrome.prototype.refreshBotMeta = function () {
    var nameEl = document.getElementById("ws-bot-name");
    if (!nameEl) return;
    if (!this.botId) {
      nameEl.textContent = tr("editor.bot_untitled", "Bot");
      return;
    }
    var self = this;
    var uid = "";
    try {
      uid = (global.localStorage && global.localStorage.getItem("user_id")) || "";
    } catch (e) {}
    var q = uid ? "?user_id=" + encodeURIComponent(uid) : "";
    fetch(apiOrigin() + "/api/bots/my" + q, { headers: authHeaders() })
      .then(function (r) {
        return r.json().catch(function () {
          return [];
        });
      })
      .then(function (bots) {
        if (!Array.isArray(bots)) return;
        var found = bots.find(function (b) {
          return String(b.id) === String(self.botId);
        });
        if (found && found.name) nameEl.textContent = found.name;
        else nameEl.textContent = "Bot #" + self.botId;
      })
      .catch(function () {
        nameEl.textContent = "Bot #" + self.botId;
      });
  };

  WorkspaceChrome.prototype.refreshStatus = function () {
    var pill = document.getElementById("ws-status-pill");
    var label = document.getElementById("ws-status-label");
    if (!pill || !label) return Promise.resolve();
    if (!this.botId) {
      pill.classList.remove("is-running");
      label.textContent = tr("bots.status_stopped", "Stopped");
      return Promise.resolve();
    }
    return fetch(apiOrigin() + "/api/bots/status/" + encodeURIComponent(this.botId), {
      headers: authHeaders(),
    })
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (data) {
        var running = !!(data && data.running);
        pill.classList.toggle("is-running", running);
        label.textContent = running
          ? tr("bots.status_running", "Running")
          : tr("bots.status_stopped", "Stopped");
      })
      .catch(function () {});
  };

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  global.WorkspaceChrome = WorkspaceChrome;
})(typeof window !== "undefined" ? window : this);
