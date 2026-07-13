/**
 * Writes build stamp into frontend for health-check / debugging after install.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const pkg = require(path.join(ROOT, "package.json"));
const out = path.join(ROOT, "frontend", "shared", "build-stamp.json");

const stamp = {
  version: pkg.version,
  builtAt: new Date().toISOString(),
};

fs.writeFileSync(out, JSON.stringify(stamp, null, 2) + "\n", "utf8");
console.log("build stamp:", out, stamp);
