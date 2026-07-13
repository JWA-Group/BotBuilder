/**
 * Fix feature pages: use shared page-shell instead of missing local style.css,
 * and prefer local relative paths for each feature's own css/js.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "frontend");

const FEATURES = [
  { dir: "analytics", css: "analytics.css", js: "AnalyticsView.js" },
  { dir: "database", css: "database.css", js: "DatabaseManagerView.js" },
  { dir: "mailing", css: "mailing.css", js: "BroadcastView.js" },
  { dir: "monitor", css: "monitor.css", js: "SystemMonitorView.js" },
  { dir: "deployment", css: "deployment.css", js: "DeploymentView.js" },
  { dir: "templates", css: "template-library.css", js: "TemplateLibraryView.js" },
  { dir: "plugins", css: "plugins.css", js: "PluginManagerView.js" },
  { dir: "plugin-builder", css: "plugin-builder.css", js: "PluginBuilderView.js" },
];

function fixDashboardHub() {
  const file = path.join(ROOT, "dashboard", "index.html");
  let text = fs.readFileSync(file, "utf8");
  text = text.replace(
    '<link rel="stylesheet" href="style.css" />',
    '<link rel="stylesheet" href="/shared/css/page-shell.css" />'
  );
  fs.writeFileSync(file, text, "utf8");
  console.log("fixed dashboard hub");
}

function fixFeature(f) {
  const file = path.join(ROOT, f.dir, "index.html");
  if (!fs.existsSync(file)) return;
  let text = fs.readFileSync(file, "utf8");

  // Replace broken relative dashboard style.css with shared page-shell
  text = text.replace(
    /<link rel="stylesheet" href="style\.css"\s*\/?>/g,
    '<link rel="stylesheet" href="/shared/css/page-shell.css" />'
  );

  // Prefer local relative css
  text = text.replace(
    new RegExp(`href="/${f.dir}/${f.css}[^"]*"`, "g"),
    `href="${f.css}"`
  );
  text = text.replace(
    new RegExp(`href="/dashboard/${f.css}[^"]*"`, "g"),
    `href="${f.css}"`
  );

  // Prefer local relative js (keep query cache-bust if present)
  text = text.replace(
    new RegExp(`src="/${f.dir}/${f.js}(\\?[^"]*)?"`, "g"),
    `src="${f.js}$1"`
  );
  text = text.replace(
    new RegExp(`src="/shared/js/${f.js}(\\?[^"]*)?"`, "g"),
    `src="${f.js}$1"`
  );

  // Absolute feature css that should be local
  text = text.replace(
    new RegExp(`href="/${f.css}"`, "g"),
    `href="${f.css}"`
  );

  fs.writeFileSync(file, text, "utf8");
  console.log("fixed", f.dir);
}

fixDashboardHub();
FEATURES.forEach(fixFeature);

// Scenario: use relative CanvasView / TimelineBar
const scenario = path.join(ROOT, "editor", "scenario", "index.html");
let s = fs.readFileSync(scenario, "utf8");
s = s
  .replace('/editor/scenario/CanvasView.js', 'CanvasView.js')
  .replace('/editor/scenario/TimelineBar.js', 'TimelineBar.js');
fs.writeFileSync(scenario, s, "utf8");
console.log("fixed scenario");

// Templates also loads CanvasView from scenario
const templates = path.join(ROOT, "templates", "index.html");
if (fs.existsSync(templates)) {
  let t = fs.readFileSync(templates, "utf8");
  t = t.replace(
    /src="\/editor\/scenario\/CanvasView\.js"/g,
    'src="/editor/scenario/CanvasView.js"'
  );
  t = t.replace(/src="CanvasView\.js"/g, 'src="/editor/scenario/CanvasView.js"');
  // if it still points to shared, fix:
  t = t.replace(
    /src="\/shared\/js\/CanvasView\.js"/g,
    'src="/editor/scenario/CanvasView.js"'
  );
  fs.writeFileSync(templates, t, "utf8");
  console.log("fixed templates canvas ref");
}

console.log("done");
