/**
 * Split dashboard dump into per-feature folders.
 * Each feature gets its own html + css + js.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "frontend");

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function move(src, dest) {
  const from = path.join(ROOT, src);
  const to = path.join(ROOT, dest);
  if (!fs.existsSync(from)) {
    console.warn("skip missing", src);
    return;
  }
  ensureDir(path.dirname(to));
  if (fs.existsSync(to)) fs.rmSync(to, { recursive: true, force: true });
  fs.renameSync(from, to);
  console.log("move", src, "->", dest);
}

function copy(src, dest) {
  const from = path.join(ROOT, src);
  const to = path.join(ROOT, dest);
  ensureDir(path.dirname(to));
  fs.copyFileSync(from, to);
}

// Feature modules
const features = [
  {
    dir: "analytics",
    html: "dashboard/analytics.html",
    css: "dashboard/analytics.css",
    js: "shared/js/AnalyticsView.js",
    htmlName: "index.html",
    cssName: "analytics.css",
    jsName: "AnalyticsView.js",
  },
  {
    dir: "database",
    html: "dashboard/database.html",
    css: "dashboard/database.css",
    js: "shared/js/DatabaseManagerView.js",
    htmlName: "index.html",
    cssName: "database.css",
    jsName: "DatabaseManagerView.js",
  },
  {
    dir: "mailing",
    html: "dashboard/mailing.html",
    css: "dashboard/mailing.css",
    js: "shared/js/BroadcastView.js",
    htmlName: "index.html",
    cssName: "mailing.css",
    jsName: "BroadcastView.js",
  },
  {
    dir: "monitor",
    html: "dashboard/monitor.html",
    css: "dashboard/monitor.css",
    js: "shared/js/SystemMonitorView.js",
    htmlName: "index.html",
    cssName: "monitor.css",
    jsName: "SystemMonitorView.js",
  },
  {
    dir: "deployment",
    html: "dashboard/deployment.html",
    css: "dashboard/deployment.css",
    js: "shared/js/DeploymentView.js",
    htmlName: "index.html",
    cssName: "deployment.css",
    jsName: "DeploymentView.js",
  },
  {
    dir: "plugins",
    html: "dashboard/plugins.html",
    css: "dashboard/plugins.css",
    js: "shared/js/PluginManagerView.js",
    htmlName: "index.html",
    cssName: "plugins.css",
    jsName: "PluginManagerView.js",
  },
  {
    dir: "plugin-builder",
    html: "dashboard/plugin-builder.html",
    css: "dashboard/plugin-builder.css",
    js: "shared/js/PluginBuilderView.js",
    htmlName: "index.html",
    cssName: "plugin-builder.css",
    jsName: "PluginBuilderView.js",
  },
  {
    dir: "templates",
    html: "dashboard/template-library.html",
    css: "dashboard/template-library.css",
    js: "shared/js/TemplateLibraryView.js",
    htmlName: "index.html",
    cssName: "template-library.css",
    jsName: "TemplateLibraryView.js",
  },
];

for (const f of features) {
  ensureDir(path.join(ROOT, f.dir));
  move(f.html, path.join(f.dir, f.htmlName));
  move(f.css, path.join(f.dir, f.cssName));
  move(f.js, path.join(f.dir, f.jsName));
}

// Scenario-owned shared editor helpers
move("shared/js/CanvasView.js", "editor/scenario/CanvasView.js");
move("shared/js/TimelineBar.js", "editor/scenario/TimelineBar.js");

// Page shell CSS used by hub + bots + plugins — keep under shared
move("dashboard/style.css", "shared/css/page-shell.css");

console.log("filesystem moves done");
