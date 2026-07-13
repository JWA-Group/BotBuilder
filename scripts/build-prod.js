/**
 * BotBuilder production helpers: clean + PyInstaller backend freeze.
 * Electron NSIS packaging is invoked directly via package.json "build:electron".
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const { ensurePythonEmbed } = require("./ensure-python-embed");

const ROOT = path.resolve(__dirname, "..");
const BACKEND_DIST = path.join(ROOT, "backend", "dist");
const BACKEND_BUILD = path.join(ROOT, "backend", "build");
const BACKEND_OUT = path.join(BACKEND_DIST, "botbuilder-backend");
const BACKEND_EXE = path.join(
  BACKEND_OUT,
  process.platform === "win32" ? "botbuilder-backend.exe" : "botbuilder-backend"
);

function run(command, args, opts = {}) {
  console.log(`\n> ${command} ${args.join(" ")}\n`);
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: "inherit",
    shell: process.platform === "win32",
    ...opts,
  });
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function rmrf(target) {
  const full = path.isAbsolute(target) ? target : path.join(ROOT, target);
  if (!fs.existsSync(full)) return;
  fs.rmSync(full, { recursive: true, force: true });
  console.log("cleaned", path.relative(ROOT, full) || full);
}

function resolvePython() {
  const candidates = [
    path.join(ROOT, "venv", "Scripts", "python.exe"),
    path.join(ROOT, "python_embed", "python.exe"),
    process.platform === "win32" ? "python" : "python3",
  ];
  for (const c of candidates) {
    if (c === "python" || c === "python3") return c;
    if (fs.existsSync(c)) return c;
  }
  return "python";
}

function clean() {
  rmrf("dist-electron");
  rmrf("dist");
  rmrf(BACKEND_DIST);
  rmrf(path.join(BACKEND_BUILD, "pyinstaller"));
  rmrf(path.join(ROOT, "build", "pyinstaller"));
  // Preserve backend/build/LICENSE.txt and build/ThirdPartyNotices.txt (licensing pipeline).
  // Do not delete build/LICENSE.txt — copied from EULA during build:licenses.
}

async function buildBackend() {
  await ensurePythonEmbed(false);
  fs.mkdirSync(BACKEND_DIST, { recursive: true });
  fs.mkdirSync(BACKEND_BUILD, { recursive: true });

  const py = resolvePython();
  run(py, ["-m", "pip", "install", "-r", "requirements-build.txt"]);
  run(py, [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath",
    path.join("backend", "dist"),
    "--workpath",
    path.join("backend", "build", "pyinstaller"),
    path.join(ROOT, "packaging", "botbuilder-backend.spec"),
  ]);

  if (!fs.existsSync(BACKEND_EXE)) {
    console.error("PyInstaller output missing:", BACKEND_EXE);
    process.exit(1);
  }
  console.log("Backend freeze OK:", BACKEND_EXE);
}

async function main() {
  const step = process.argv[2] || "clean";
  if (step === "clean") {
    clean();
    return;
  }
  if (step === "backend") {
    await buildBackend();
    return;
  }
  if (step === "python-embed") {
    await ensurePythonEmbed(process.argv.includes("--force"));
    return;
  }
  console.error("Usage: node scripts/build-prod.js <clean|backend|python-embed>");
  process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
