const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "frontend");
const inject =
  '    <script src="/shared/js/locales.js"></script>\n' +
  '    <script src="/shared/js/i18n.js"></script>\n';

const files = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (entry.name.endsWith(".html")) files.push(full);
  }
}
walk(root);

for (const file of files) {
  let html = fs.readFileSync(file, "utf8");
  if (html.includes("/shared/js/i18n.js")) continue;
  if (!html.includes('/shared/js/theme.js"></script>')) continue;
  html = html.replace(
    '<script src="/shared/js/theme.js"></script>',
    '<script src="/shared/js/theme.js"></script>\n' + inject
  );
  fs.writeFileSync(file, html, "utf8");
  console.log("patched", path.relative(root, file));
}
