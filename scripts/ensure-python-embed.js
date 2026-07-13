/**
 * Ensure python_embed/ is a relocatable Windows embeddable Python
 * with bot runtime packages (aiogram, aiohttp).
 *
 * Used by customer bot subprocesses — NOT the FastAPI sidecar.
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const https = require("https");
const http = require("http");
const { pipeline } = require("stream/promises");
const { createWriteStream } = require("fs");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const EMBED_DIR = path.join(ROOT, "python_embed");
const EMBED_PY = path.join(EMBED_DIR, "python.exe");
const PYTHON_VERSION = "3.11.9";
const EMBED_ZIP_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py";

function run(command, args, opts = {}) {
  console.log(`\n> ${command} ${args.join(" ")}\n`);
  const result = spawnSync(command, args, {
    cwd: opts.cwd || ROOT,
    stdio: "inherit",
    shell: !!opts.shell,
    env: opts.env || process.env,
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command} ${args.join(" ")}`);
  }
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(dest);
    const get = url.startsWith("https") ? https.get : http.get;
    const req = get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        file.close();
        fs.unlinkSync(dest);
        download(res.headers.location, dest).then(resolve, reject);
        return;
      }
      if (res.statusCode !== 200) {
        reject(new Error(`Download failed ${res.statusCode}: ${url}`));
        res.resume();
        return;
      }
      pipeline(res, file).then(resolve, reject);
    });
    req.on("error", reject);
  });
}

function embedHasAiogram() {
  if (!fs.existsSync(EMBED_PY)) return false;
  const check = spawnSync(
    EMBED_PY,
    ["-c", "import aiogram, aiohttp; print(aiogram.__version__)"],
    { encoding: "utf8", windowsHide: true }
  );
  return check.status === 0;
}

function patchPth() {
  const files = fs.readdirSync(EMBED_DIR).filter((f) => f.endsWith("._pth"));
  if (!files.length) {
    throw new Error("python_embed: missing *._pth file after extract");
  }
  const pth = path.join(EMBED_DIR, files[0]);
  const zip =
    fs.readdirSync(EMBED_DIR).find((f) => /^python3\d+\.zip$/i.test(f)) || "python311.zip";
  const lines = [zip, ".", "Lib\\site-packages", "", "import site", ""];
  fs.writeFileSync(pth, lines.join("\n"), "utf8");
  console.log("[python_embed] patched", path.basename(pth));
}

function extractZip(zipPath, destDir) {
  // PowerShell Expand-Archive is available on Windows build machines
  if (process.platform === "win32") {
    execFileSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        `Expand-Archive -LiteralPath '${zipPath.replace(/'/g, "''")}' -DestinationPath '${destDir.replace(/'/g, "''")}' -Force`,
      ],
      { stdio: "inherit" }
    );
    return;
  }
  run("unzip", ["-o", zipPath, "-d", destDir]);
}

async function ensurePythonEmbed(force = false) {
  if (!force && embedHasAiogram()) {
    console.log("[python_embed] OK — aiogram already available");
    return;
  }

  fs.mkdirSync(EMBED_DIR, { recursive: true });

  if (force || !fs.existsSync(EMBED_PY) || fs.statSync(EMBED_PY).size < 1024) {
    // Wipe stub / broken tree
    for (const name of fs.readdirSync(EMBED_DIR)) {
      fs.rmSync(path.join(EMBED_DIR, name), { recursive: true, force: true });
    }

    const zipPath = path.join(ROOT, "build", `python-${PYTHON_VERSION}-embed-amd64.zip`);
    fs.mkdirSync(path.dirname(zipPath), { recursive: true });
    if (!fs.existsSync(zipPath)) {
      console.log("[python_embed] downloading", EMBED_ZIP_URL);
      await download(EMBED_ZIP_URL, zipPath);
    }
    console.log("[python_embed] extracting…");
    extractZip(zipPath, EMBED_DIR);
  }

  if (!fs.existsSync(EMBED_PY)) {
    throw new Error("python_embed/python.exe missing after extract");
  }

  patchPth();

  const getPip = path.join(EMBED_DIR, "get-pip.py");
  if (!fs.existsSync(path.join(EMBED_DIR, "Scripts", "pip.exe")) && !fs.existsSync(path.join(EMBED_DIR, "pip.exe"))) {
    console.log("[python_embed] installing pip…");
    await download(GET_PIP_URL, getPip);
    run(EMBED_PY, [getPip, "--no-warn-script-location"], { cwd: EMBED_DIR });
  }

  const req = path.join(ROOT, "requirements-bots.txt");
  console.log("[python_embed] installing bot packages…");
  run(
    EMBED_PY,
    ["-m", "pip", "install", "--no-warn-script-location", "-r", req],
    { cwd: EMBED_DIR }
  );

  if (!embedHasAiogram()) {
    throw new Error("python_embed: aiogram import check failed after install");
  }
  console.log("[python_embed] ready:", EMBED_PY);
}

module.exports = { ensurePythonEmbed, EMBED_DIR, EMBED_PY };

if (require.main === module) {
  ensurePythonEmbed(process.argv.includes("--force")).catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
