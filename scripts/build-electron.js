/**
 * Run electron-builder NSIS x64 without code-signing tooling.
 * Avoids winCodeSign symlink errors on Windows without Developer Mode / Admin.
 */
const { spawnSync } = require("child_process");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

const env = {
  ...process.env,
  CSC_IDENTITY_AUTO_DISCOVERY: "false",
  WIN_CSC_LINK: "",
  CSC_LINK: "",
};

const result = spawnSync(
  "npx",
  ["electron-builder", "--win", "nsis", "--x64", "--publish", "never"],
  {
    cwd: ROOT,
    env,
    stdio: "inherit",
    shell: true,
  }
);

process.exit(result.status || 0);
