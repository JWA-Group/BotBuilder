/**
 * Update all URLs after per-feature folder split.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");

const REPLACEMENTS = [
  // page shell
  ["/dashboard/style.css", "/shared/css/page-shell.css"],

  // feature pages (html)
  ["/dashboard/analytics.html", "/analytics/"],
  ["/dashboard/database.html", "/database/"],
  ["/dashboard/mailing.html", "/mailing/"],
  ["/dashboard/monitor.html", "/monitor/"],
  ["/dashboard/deployment.html", "/deployment/"],
  ["/dashboard/template-library.html", "/templates/"],
  ["/dashboard/plugins.html", "/plugins/"],
  ["/dashboard/plugin-builder.html", "/plugin-builder/"],

  // feature css (if any absolute refs remain)
  ["/dashboard/analytics.css", "/analytics/analytics.css"],
  ["/dashboard/database.css", "/database/database.css"],
  ["/dashboard/mailing.css", "/mailing/mailing.css"],
  ["/dashboard/monitor.css", "/monitor/monitor.css"],
  ["/dashboard/deployment.css", "/deployment/deployment.css"],
  ["/dashboard/plugins.css", "/plugins/plugins.css"],
  ["/dashboard/plugin-builder.css", "/plugin-builder/plugin-builder.css"],
  ["/dashboard/template-library.css", "/templates/template-library.css"],

  // feature js from old shared location
  ["/shared/js/AnalyticsView.js", "/analytics/AnalyticsView.js"],
  ["/shared/js/DatabaseManagerView.js", "/database/DatabaseManagerView.js"],
  ["/shared/js/BroadcastView.js", "/mailing/BroadcastView.js"],
  ["/shared/js/SystemMonitorView.js", "/monitor/SystemMonitorView.js"],
  ["/shared/js/DeploymentView.js", "/deployment/DeploymentView.js"],
  ["/shared/js/PluginManagerView.js", "/plugins/PluginManagerView.js"],
  ["/shared/js/PluginBuilderView.js", "/plugin-builder/PluginBuilderView.js"],
  ["/shared/js/TemplateLibraryView.js", "/templates/TemplateLibraryView.js"],
  ["/shared/js/CanvasView.js", "/editor/scenario/CanvasView.js"],
  ["/shared/js/TimelineBar.js", "/editor/scenario/TimelineBar.js"],
];

function walk(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) walk(full, out);
    else if (/\.(html|js|css|webmanifest)$/i.test(name)) out.push(full);
  }
  return out;
}

function rewriteFile(file) {
  let text = fs.readFileSync(file, "utf8");
  const original = text;
  for (const [from, to] of REPLACEMENTS) {
    if (text.includes(from)) text = text.split(from).join(to);
  }
  if (text !== original) {
    fs.writeFileSync(file, text, "utf8");
    console.log("updated", path.relative(ROOT, file));
    return true;
  }
  return false;
}

let n = 0;
for (const file of walk(path.join(ROOT, "frontend"))) {
  if (rewriteFile(file)) n++;
}
// Electron main process paths
if (rewriteFile(path.join(ROOT, "main.js"))) n++;

console.log("files changed:", n);
