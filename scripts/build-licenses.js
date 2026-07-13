/**
 * Generate consolidated license bundle for the shipped Electron app.
 *
 * Part 1 — BotBuilder EULA (backend/build/LICENSE.txt)
 * Part 2 — Third-party npm notices (no build-machine paths)
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, "build");
const OUT_FILE = path.join(OUT_DIR, "ThirdPartyNotices.txt");
const EULA_SRC = path.join(ROOT, "backend", "build", "LICENSE.txt");
const EULA_OUT = path.join(OUT_DIR, "LICENSE.txt");

const licenseCheckerBin =
  process.platform === "win32"
    ? path.join(ROOT, "node_modules", ".bin", "license-checker.cmd")
    : path.join(ROOT, "node_modules", ".bin", "license-checker");

function readEula() {
  if (!fs.existsSync(EULA_SRC)) {
    console.error("EULA not found:", EULA_SRC);
    console.error("Place your license at backend/build/LICENSE.txt before building.");
    process.exit(1);
  }
  return fs.readFileSync(EULA_SRC, "utf8").trim();
}

function scanThirdPartyJson() {
  const args = [
    "--start",
    ROOT,
    "--direct",
    "0",
    "--development",
    "--excludePrivate",
    "botbuilder-desktop",
    "--json",
  ];

  const result = spawnSync(licenseCheckerBin, args, {
    cwd: ROOT,
    encoding: "utf8",
    shell: process.platform === "win32",
  });

  if (result.status !== 0) {
    console.error(result.stderr || result.stdout || "license-checker failed");
    process.exit(result.status || 1);
  }

  try {
    return JSON.parse(result.stdout || "{}");
  } catch (err) {
    console.error("Failed to parse license-checker JSON:", err.message);
    process.exit(1);
  }
}

function formatThirdPartyNotices(packages) {
  const names = Object.keys(packages).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" })
  );

  const lines = [];
  for (const name of names) {
    const info = packages[name] || {};
    const license = String(info.licenses || "UNKNOWN").trim();
    const repository = String(info.repository || "").trim();
    const publisher = String(info.publisher || "").trim();
    const url = String(info.url || "").trim();

    lines.push(`├─ ${name}`);
    lines.push(`│  ├─ License: ${license}`);
    if (repository) {
      lines.push(`│  ├─ Repository: ${repository}`);
    }
    if (publisher) {
      lines.push(`│  ├─ Publisher: ${publisher}`);
    }
    if (url) {
      lines.push(`│  └─ URL: ${url}`);
    } else if (repository || publisher) {
      lines.push(`│  └─`);
    }
  }

  return { text: lines.join("\n"), count: names.length };
}

function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const eula = readEula();
  fs.writeFileSync(EULA_OUT, eula + "\n", "utf8");

  const packages = scanThirdPartyJson();
  const { text: thirdParty, count } = formatThirdPartyNotices(packages);

  const document = [
    "================================================================================",
    "BotBuilder — License and Third-Party Notices",
    "Generated automatically during production build. Do not edit by hand.",
    "================================================================================",
    "",
    "PART 1 — BOT BUILDER END USER LICENSE AGREEMENT (EULA)",
    "--------------------------------------------------------------------------------",
    "",
    eula,
    "",
    "",
    "PART 2 — THIRD-PARTY OPEN SOURCE NOTICES",
    "The desktop app bundles Electron, Chromium, and other npm packages.",
    "Each entry lists the component name, SPDX/license type, and source repository.",
    "No local file paths are included — paths differ on every installation machine.",
    "--------------------------------------------------------------------------------",
    "",
    thirdParty,
    "",
  ].join("\n");

  fs.writeFileSync(OUT_FILE, document, "utf8");
  console.log("LICENSE.txt copied to:", EULA_OUT);
  console.log(
    `ThirdPartyNotices.txt written (EULA + ${count} third-party entries):`,
    OUT_FILE
  );
}

main();
