/**
 * Rewrite frontend absolute asset paths after shared/ reorganization.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "frontend");

// Longest / most specific first
const REPLACEMENTS = [
  ["/theme-surfaces.css", "/shared/css/theme-surfaces.css"],
  ["/app-shell.css", "/shared/css/app-shell.css"],
  ["/theme.css", "/shared/css/theme.css"],
  ["/theme.js", "/shared/js/theme.js"],
  ["/api-config.js", "/shared/js/api-config.js"],
  ["/plugin-constants.js", "/shared/js/plugin-constants.js"],
  ["/AnalyticsView.js", "/shared/js/AnalyticsView.js"],
  ["/BroadcastView.js", "/shared/js/BroadcastView.js"],
  ["/CanvasView.js", "/shared/js/CanvasView.js"],
  ["/DatabaseManagerView.js", "/shared/js/DatabaseManagerView.js"],
  ["/DeploymentView.js", "/shared/js/DeploymentView.js"],
  ["/PluginBuilderView.js", "/shared/js/PluginBuilderView.js"],
  ["/PluginManagerView.js", "/shared/js/PluginManagerView.js"],
  ["/SystemMonitorView.js", "/shared/js/SystemMonitorView.js"],
  ["/TemplateLibraryView.js", "/shared/js/TemplateLibraryView.js"],
  ["/TimelineBar.js", "/shared/js/TimelineBar.js"],
  ["/icons/", "/shared/icons/"],
];

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) walk(full, out);
    else if (/\.(html|js|css|webmanifest)$/i.test(name)) out.push(full);
  }
  return out;
}

function applyOnce(text, from, to) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const idx = text.indexOf(from, i);
    if (idx < 0) {
      out += text.slice(i);
      break;
    }
    // Skip if already rewritten to /shared/...
    const before = text.slice(Math.max(0, idx - 20), idx);
    if (before.includes("/shared/css") || before.includes("/shared/js") || before.includes("/shared/icons")) {
      out += text.slice(i, idx + from.length);
      i = idx + from.length;
      continue;
    }
    out += text.slice(i, idx) + to;
    i = idx + from.length;
  }
  return out;
}

let changedFiles = 0;
for (const file of walk(ROOT)) {
  let text = fs.readFileSync(file, "utf8");
  const original = text;
  for (const [from, to] of REPLACEMENTS) {
    text = applyOnce(text, from, to);
  }
  text = text
    .replaceAll("/shared/css/shared/css/", "/shared/css/")
    .replaceAll("/shared/js/shared/js/", "/shared/js/")
    .replaceAll("/shared/icons/shared/icons/", "/shared/icons/");

  if (text !== original) {
    fs.writeFileSync(file, text, "utf8");
    changedFiles += 1;
    console.log("updated", path.relative(ROOT, file));
  }
}
console.log("done, files changed:", changedFiles);
