/**
 * BotBuilder — Electron main process
 * Spawns FastAPI sidecar, waits for health check, loads SPA, cleans up on exit.
 */
const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  Menu,
  shell,
} = require("electron");
const path = require("path");
const fs = require("fs");
const net = require("net");
const http = require("http");
const { spawn } = require("child_process");
const MENU_LOCALES = require("./electron/menu-locales");

const SUPPORTED_LANGS = new Set(["en", "ru", "es"]);

const DEFAULT_PORT = 8000;
const DEFAULT_UNDO_STEPS = 30;
const HOST = "127.0.0.1";
const HEALTH_PATH = "/api/health";
const HEALTH_TIMEOUT_MS = 90_000;
const SHUTDOWN_TIMEOUT_MS = 8_000;

// Stable AppData folder: %AppData%/botbuilder-desktop (must run before ready)
try {
  const appDataRoot = app.getPath("appData");
  app.setPath("userData", path.join(appDataRoot, "botbuilder-desktop"));
} catch {
  /* app may not expose paths in some test harnesses */
}

/** @type {import('child_process').ChildProcess | null} */
let sidecarProcess = null;
/** @type {boolean} */
let ownsSidecar = false;
/** @type {BrowserWindow | null} */
let mainWindow = null;
/** @type {BrowserWindow | null} */
let settingsWindow = null;
/** @type {boolean} */
let isQuitting = false;
/** @type {boolean} — suppress app.quit() while first-run setup is open (no main window yet). */
let startupPhase = true;
/** @type {number} */
let currentPort = DEFAULT_PORT;

/** @type {Map<string, import('electron').BrowserWindow>} */
const childWindows = new Map();

/** Разделы приложения для открытия во втором окне. */
const APP_WINDOWS = [
  { id: "home", path: "/dashboard/", width: 1100, height: 760 },
  { id: "analytics", path: "/analytics/", width: 1200, height: 860 },
  { id: "database", path: "/database/", width: 1280, height: 820 },
  { id: "bots", path: "/bots/", width: 1200, height: 820 },
  { id: "templates", path: "/templates/", width: 1100, height: 820 },
  { id: "plugins", path: "/plugins/", width: 1100, height: 780 },
  { id: "plugin-builder", path: "/plugin-builder/", width: 1400, height: 900 },
  { id: "scenario", path: "/editor/scenario/", width: 1440, height: 900 },
  { id: "mailing", path: "/mailing/", width: 1100, height: 760 },
  { id: "monitor", path: "/monitor/", width: 1200, height: 860 },
  { id: "deployment", path: "/deployment/", width: 1100, height: 820 },
  { id: "info", path: "/info/", width: 1080, height: 820 },
];

const WINDOW_LABEL_KEYS = {
  home: "win_home",
  analytics: "win_analytics",
  database: "win_database",
  bots: "win_bots",
  templates: "win_templates",
  plugins: "win_plugins",
  "plugin-builder": "win_plugin_builder",
  scenario: "win_scenario",
  mailing: "win_mailing",
  monitor: "win_monitor",
  deployment: "win_deployment",
  info: "win_info",
};

/** Install / repo root (read-only assets: frontend, bundled plugins, python_embed). */
function getAppRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "app")
    : __dirname;
}

/** Writable OS user data — %AppData%/botbuilder-desktop/data on Windows. */
function getDataDir() {
  return path.join(app.getPath("userData"), "data");
}

function ensureUserDataDirs() {
  const dataDir = getDataDir();
  [
    dataDir,
    path.join(dataDir, "projects"),
    path.join(dataDir, "plugins"),
    path.join(dataDir, "databases"),
    path.join(dataDir, "templates", "local"),
    path.join(dataDir, "logs"),
  ].forEach((dir) => fs.mkdirSync(dir, { recursive: true }));
  return dataDir;
}

const ROOT = getAppRoot();

/** Windows / Electron window & taskbar icon */
function getAppIconPath() {
  const candidates = [
    path.join(__dirname, "BBico.ico"),
    path.join(getAppRoot(), "BBico.ico"),
    path.join(__dirname, "frontend", "icons", "BBico.ico"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

function settingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function loadSettings() {
  const defaults = {
    port: DEFAULT_PORT,
    undoSteps: DEFAULT_UNDO_STEPS,
    theme: "light",
    lang: null,
  };
  try {
    const raw = fs.readFileSync(settingsPath(), "utf8");
    const parsed = JSON.parse(raw);
    const port = Number(parsed.port);
    const undoSteps = Number(parsed.undoSteps);
    const theme = parsed.theme === "dark" ? "dark" : "light";
    const lang =
      typeof parsed.lang === "string" && SUPPORTED_LANGS.has(parsed.lang.slice(0, 2))
        ? parsed.lang.slice(0, 2)
        : null;
    return {
      port: Number.isFinite(port) && port > 0 && port < 65536 ? port : DEFAULT_PORT,
      undoSteps:
        Number.isFinite(undoSteps) && undoSteps >= 1 && undoSteps <= 500
          ? Math.floor(undoSteps)
          : DEFAULT_UNDO_STEPS,
      theme,
      lang,
    };
  } catch {
    return defaults;
  }
}

function resolveAppLang(settings) {
  const s = settings || loadSettings();
  if (s.lang && SUPPORTED_LANGS.has(s.lang)) return s.lang;
  try {
    const osLang = app.getLocale().slice(0, 2).toLowerCase();
    if (SUPPORTED_LANGS.has(osLang)) return osLang;
  } catch {
    /* ignore */
  }
  return "en";
}

function menuLabel(key, lang) {
  const pack = MENU_LOCALES[lang] || MENU_LOCALES.en;
  return (pack && pack[key]) || MENU_LOCALES.en[key] || key;
}

function windowTitleForSpec(spec, lang) {
  const key = WINDOW_LABEL_KEYS[spec.id] || "win_home";
  return menuLabel(key, lang);
}

function getRendererAdditionalArgs(port) {
  const settings = loadSettings();
  const lang = resolveAppLang(settings);
  return [
    `--api-port=${port}`,
    `--undo-steps=${settings.undoSteps}`,
    `--app-lang=${lang}`,
  ];
}

function applyLangToWindow(win, lang) {
  if (!win || win.isDestroyed()) return;
  const code = SUPPORTED_LANGS.has(lang) ? lang : "en";
  try {
    win.webContents.send("app:lang-changed", code);
  } catch {
    /* ignore */
  }
  win.webContents
    .executeJavaScript(
      `try{localStorage.setItem("botbuilder_lang",${JSON.stringify(code)});` +
        `if(window.__applyLanguageFromMain)window.__applyLanguageFromMain(${JSON.stringify(code)});` +
        `else if(window.applyLanguage)window.applyLanguage(${JSON.stringify(code)},{silent:true,fromBroadcast:true});` +
        `}catch(e){}`,
      true
    )
    .catch(() => {});
}

function applyLangToAllWindows(lang, exceptWebContentsId) {
  const code = SUPPORTED_LANGS.has(lang) ? lang : "en";
  BrowserWindow.getAllWindows().forEach((win) => {
    if (
      exceptWebContentsId != null &&
      win.webContents &&
      win.webContents.id === exceptWebContentsId
    ) {
      return;
    }
    applyLangToWindow(win, code);
  });
}

function setAppLanguage(lang, options) {
  const next = SUPPORTED_LANGS.has(lang) ? lang : "en";
  const settings = loadSettings();
  const changed = settings.lang !== next;
  if (changed) {
    settings.lang = next;
    saveSettings(settings);
  }
  applyLangToAllWindows(next, options && options.exceptWebContentsId);
  if (currentPort) buildMenu(currentPort);
  return next;
}

function languageSetupHtmlPath() {
  const fromAppRoot = path.join(getAppRoot(), "frontend", "setup", "language.html");
  if (fs.existsSync(fromAppRoot)) return fromAppRoot;
  return path.join(__dirname, "electron", "language-setup.html");
}

function settingsHtmlPath() {
  const fromAppRoot = path.join(getAppRoot(), "frontend", "setup", "settings.html");
  if (fs.existsSync(fromAppRoot)) return fromAppRoot;
  return path.join(__dirname, "electron", "settings.html");
}

function showLanguageSetupWindow() {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (lang) => {
      if (settled) return;
      settled = true;
      resolve(lang);
    };

    const setupWin = new BrowserWindow({
      width: 640,
      height: 720,
      resizable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      show: false,
      autoHideMenuBar: true,
      icon: getAppIconPath(),
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, "preload-language-setup.js"),
      },
    });

    setupWin.setMenu(null);

    setupWin.loadFile(languageSetupHtmlPath());
    setupWin.once("ready-to-show", () => setupWin.show());

    ipcMain.once("language-setup-choose", (_event, payload) => {
      const raw =
        payload && typeof payload === "object" ? payload : { lang: payload, theme: "light" };
      const next = SUPPORTED_LANGS.has(raw.lang) ? raw.lang : "en";
      const theme = raw.theme === "dark" ? "dark" : "light";
      const settings = loadSettings();
      saveSettings({ ...settings, lang: next, theme });
      setAppTheme(theme, { silent: true });
      if (!setupWin.isDestroyed()) setupWin.close();
      finish(next);
    });

    setupWin.on("closed", () => {
      const settings = loadSettings();
      if (!settings.lang) {
        saveSettings({ ...settings, lang: "en" });
        finish("en");
      } else if (!settled) {
        finish(settings.lang);
      }
    });
  });
}

async function ensureAppLanguage() {
  const settings = loadSettings();
  if (settings.lang && SUPPORTED_LANGS.has(settings.lang)) {
    setAppLanguage(settings.lang, { silent: true });
    return settings.lang;
  }
  const lang = await showLanguageSetupWindow();
  setAppLanguage(lang, { silent: true });
  return lang;
}

function saveSettings(settings) {
  const dir = path.dirname(settingsPath());
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2), "utf8");
}

function applyThemeToWindow(win, theme) {
  if (!win || win.isDestroyed()) return;
  const t = theme === "dark" ? "dark" : "light";
  // silent:true — must NOT call notifyThemeChange or we get an IPC storm that freezes the PC
  win.webContents
    .executeJavaScript(
      `try{window.AppTheme&&AppTheme.apply(${JSON.stringify(t)},{silent:true})}catch(e){}`,
      true
    )
    .catch(() => {});
}

function applyThemeToAllWindows(theme, exceptWebContentsId) {
  BrowserWindow.getAllWindows().forEach((win) => {
    if (
      exceptWebContentsId != null &&
      win.webContents &&
      win.webContents.id === exceptWebContentsId
    ) {
      return;
    }
    applyThemeToWindow(win, theme);
  });
}

function setAppTheme(theme, options) {
  const next = theme === "dark" ? "dark" : "light";
  const settings = loadSettings();
  const changed = settings.theme !== next;
  if (changed) {
    settings.theme = next;
    saveSettings(settings);
  }
  // Always sync other windows silently; skip if nothing changed and no force
  if (changed || (options && options.forceBroadcast)) {
    applyThemeToAllWindows(next, options && options.exceptWebContentsId);
    if (currentPort) buildMenu(currentPort);
  }
  return next;
}

function resolveDevBackendPython() {
  const root = getAppRoot();
  const candidates = [
    path.join(__dirname, "venv", "Scripts", "python.exe"),
    path.join(root, "venv", "Scripts", "python.exe"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

/** Python for the FastAPI sidecar (venv / system). Never python_embed — that is bot-only. */
function resolveSidecarPython() {
  const fromVenv = resolveDevBackendPython();
  if (fromVenv) return fromVenv;
  return process.platform === "win32" ? "python" : "python3";
}

function resolveFrozenBackend() {
  // Production: exact resources path required by the NSIS layout.
  if (app.isPackaged) {
    const packaged = path.join(
      process.resourcesPath,
      "botbuilder-backend",
      "botbuilder-backend.exe"
    );
    if (!fs.existsSync(packaged)) {
      throw new Error(
        "BotBuilder backend binary not found:\n" +
          packaged +
          "\nRebuild with: npm run build:prod"
      );
    }
    return packaged;
  }

  // Dev / local freeze fallbacks
  const candidates = [
    path.join(__dirname, "backend", "dist", "botbuilder-backend", "botbuilder-backend.exe"),
    path.join(__dirname, "dist", "botbuilder-backend", "botbuilder-backend.exe"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function buildSidecarEnv(port) {
  const appRoot = getAppRoot();
  const dataDir = ensureUserDataDirs();
  const env = {
    ...process.env,
    DESKTOP_APP: "1",
    APP_BASE_URL: `http://${HOST}:${port}`,
    BOTBUILDER_DATA_DIR: dataDir,
    BOTBUILDER_APP_ROOT: appRoot,
  };
  // PyInstaller breaks if parent shell injects PYTHONHOME/PYTHONPATH (missing encodings).
  for (const key of Object.keys(env)) {
    if (key === "PYTHONUNBUFFERED" || key === "PYTHONIOENCODING" || key === "PYTHONUTF8") {
      continue;
    }
    if (key.startsWith("PYTHON")) {
      delete env[key];
    }
  }
  env.PYTHONUNBUFFERED = "1";
  env.PYTHONIOENCODING = "utf-8";
  env.PYTHONUTF8 = "1";
  return env;
}

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, HOST);
  });
}

function httpGetJson(url, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        try {
          resolve(JSON.parse(body || "{}"));
        } catch {
          resolve(null);
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function sidecarMatchesInstall(port) {
  if (!app.isPackaged) return true;
  try {
    const body = await httpGetJson(`http://${HOST}:${port}${HEALTH_PATH}`);
    if (!body || body.status !== "ok") return false;
    const expected = path.resolve(getAppRoot()).toLowerCase();
    const reported = path.resolve(String(body.app_root || "")).toLowerCase();
    return expected === reported;
  } catch {
    return false;
  }
}

/** Stop a stale sidecar so updates / reinstall pick up new frontend from disk. */
async function retireExistingSidecar(port) {
  if (!(await isHealthOk(port))) return;
  if (app.isPackaged) {
    await postShutdown(port);
    await sleep(700);
    return;
  }
  const matches = await sidecarMatchesInstall(port);
  if (!matches) {
    await postShutdown(port);
    await sleep(500);
  }
}

function httpStatus(url, timeoutMs = 2500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode || 0);
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
  });
}

async function isHealthOk(port) {
  try {
    const status = await httpStatus(`http://${HOST}:${port}${HEALTH_PATH}`);
    return status === 200 || status === 401;
  } catch {
    return false;
  }
}

function waitForHealth(port, timeoutMs = HEALTH_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const tick = async () => {
      if (await isHealthOk(port)) {
        resolve(true);
        return;
      }
      if (Date.now() >= deadline) {
        resolve(false);
        return;
      }
      setTimeout(tick, 250);
    };
    tick();
  });
}

function postShutdown(port) {
  return new Promise((resolve) => {
    const req = http.request(
      {
        hostname: HOST,
        port,
        path: "/api/shutdown",
        method: "POST",
        timeout: SHUTDOWN_TIMEOUT_MS,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

function killProcessTree(proc) {
  if (!proc || proc.killed || proc.exitCode !== null) return;
  const pid = proc.pid;
  if (!pid) return;

  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    try {
      proc.kill("SIGTERM");
    } catch {
      /* ignore */
    }
    setTimeout(() => {
      try {
        if (proc.exitCode === null) proc.kill("SIGKILL");
      } catch {
        /* ignore */
      }
    }, 3000);
  }
}

async function stopSidecar(port) {
  if (ownsSidecar && sidecarProcess) {
    await postShutdown(port);
    killProcessTree(sidecarProcess);
    sidecarProcess = null;
    ownsSidecar = false;
    return;
  }
  await postShutdown(port);
}

function spawnSidecar(port) {
  const env = buildSidecarEnv(port);
  let frozen = null;
  if (app.isPackaged) {
    try {
      frozen = resolveFrozenBackend();
    } catch (err) {
      dialog.showErrorBox("BotBuilder — backend missing", err.message || String(err));
      throw err;
    }
  } else {
    frozen = resolveFrozenBackend();
  }

  let child;
  const liveBackendScript = path.join(getAppRoot(), "core", "main.py");
  const devBackendPython = resolveDevBackendPython();
  const preferLiveBackend =
    !app.isPackaged &&
    process.env.BOTBUILDER_FROZEN_BACKEND !== "1" &&
    fs.existsSync(liveBackendScript) &&
    devBackendPython;

  if (preferLiveBackend) {
    child = spawn(devBackendPython, [liveBackendScript, "--host", HOST, "--port", String(port)], {
      cwd: getAppRoot(),
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  } else if (frozen) {
    child = spawn(frozen, ["--host", HOST, "--port", String(port)], {
      cwd: path.dirname(frozen),
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  } else {
    const python = resolveSidecarPython();
    const script = path.join(getAppRoot(), "core", "main.py");
    child = spawn(python, [script, "--host", HOST, "--port", String(port)], {
      cwd: getAppRoot(),
      env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  }

  child.stdout?.on("data", (chunk) => {
    if (!app.isPackaged) process.stdout.write(`[sidecar] ${chunk}`);
  });
  child.stderr?.on("data", (chunk) => {
    if (!app.isPackaged) process.stderr.write(`[sidecar] ${chunk}`);
  });

  child.on("exit", (code, signal) => {
    if (!isQuitting && code !== 0 && code !== null) {
      dialog.showErrorBox(
        "BotBuilder — ошибка сервера",
        `FastAPI sidecar завершился (code=${code}, signal=${signal || "none"}).\n` +
          (frozen
            ? "Проверьте сборку botbuilder-backend (npm run build:backend)."
            : "Проверьте venv/python_embed и requirements.txt.")
      );
    }
    if (sidecarProcess === child) {
      sidecarProcess = null;
      ownsSidecar = false;
    }
  });

  return child;
}

async function promptForPort(currentPort, reason) {
  const { response, checkboxChecked } = await dialog.showMessageBox({
    type: "warning",
    title: "BotBuilder — порт занят",
    message: reason,
    detail: `Текущий порт: ${currentPort}. Укажите другой порт (1024–65535) в настройках.`,
    buttons: ["Открыть настройки", "Повторить", "Выход"],
    defaultId: 0,
    cancelId: 2,
    checkboxLabel: "Запомнить новый порт",
    checkboxChecked: true,
  });

  if (response === 2) return null;
  if (response === 1) return currentPort;

  const saved = await openSettingsDialog(loadSettings());
  if (saved == null) return null;
  if (checkboxChecked) saveSettings(saved);
  return saved.port;
}

function openSettingsDialog(initialSettings) {
  const settings =
    typeof initialSettings === "object" && initialSettings !== null
      ? initialSettings
      : { port: Number(initialSettings) || DEFAULT_PORT, undoSteps: DEFAULT_UNDO_STEPS };

  return new Promise((resolve) => {
    if (settingsWindow) {
      settingsWindow.focus();
      return;
    }

    settingsWindow = new BrowserWindow({
      width: 760,
      height: 720,
      minWidth: 560,
      minHeight: 520,
      resizable: true,
      minimizable: false,
      maximizable: false,
      parent: mainWindow || undefined,
      modal: !!mainWindow,
      show: false,
      autoHideMenuBar: true,
      icon: getAppIconPath(),
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, "preload-settings.js"),
        additionalArguments: [
          `--initial-port=${settings.port}`,
          `--initial-undo-steps=${settings.undoSteps}`,
          `--initial-lang=${resolveAppLang(settings)}`,
          `--initial-theme=${settings.theme === "dark" ? "dark" : "light"}`,
        ],
      },
    });

    settingsWindow.loadFile(settingsHtmlPath());

    settingsWindow.once("ready-to-show", () => settingsWindow?.show());

    settingsWindow.on("closed", () => {
      settingsWindow = null;
    });

    ipcMain.once("settings-save", (_event, payload) => {
      const port = Number(payload && typeof payload === "object" ? payload.port : payload);
      const undoSteps = Number(
        payload && typeof payload === "object" ? payload.undoSteps : DEFAULT_UNDO_STEPS
      );
      const langRaw =
        payload && typeof payload === "object" ? String(payload.lang || "").slice(0, 2) : "";
      const lang = SUPPORTED_LANGS.has(langRaw) ? langRaw : resolveAppLang(loadSettings());
      const theme =
        payload && typeof payload === "object" && payload.theme === "dark" ? "dark" : "light";
      const langPack = MENU_LOCALES[lang] || MENU_LOCALES.en;

      if (!Number.isFinite(port) || port < 1024 || port > 65535) {
        dialog.showErrorBox("BotBuilder", langPack.dialog_invalid_port);
        resolve(null);
        settingsWindow?.close();
        return;
      }
      if (!Number.isFinite(undoSteps) || undoSteps < 1 || undoSteps > 500) {
        dialog.showErrorBox("BotBuilder", langPack.dialog_invalid_undo);
        resolve(null);
        settingsWindow?.close();
        return;
      }
      const prev = loadSettings();
      const saved = {
        port,
        undoSteps: Math.floor(undoSteps),
        theme,
        lang,
      };
      saveSettings(saved);
      setAppTheme(theme, { forceBroadcast: true });
      setAppLanguage(lang);
      resolve(saved);
      settingsWindow?.close();
    });

    ipcMain.once("settings-cancel", () => {
      resolve(null);
      settingsWindow?.close();
    });
  });
}

async function resolveRuntimePort() {
  let port = loadSettings().port;

  await retireExistingSidecar(port);

  for (let attempt = 0; attempt < 5; attempt++) {
    if (await isHealthOk(port)) {
      if (!app.isPackaged && (await sidecarMatchesInstall(port))) {
        ownsSidecar = false;
        sidecarProcess = null;
        return port;
      }
      await postShutdown(port);
      await sleep(600);
    }

    if (await isPortAvailable(port)) {
      sidecarProcess = spawnSidecar(port);
      ownsSidecar = true;

      const ready = await waitForHealth(port);
      if (ready) return port;

      killProcessTree(sidecarProcess);
      sidecarProcess = null;
      ownsSidecar = false;

      const next = await promptForPort(
        port,
        `Не удалось запустить API на порту ${port}. Порт занят или сервер не ответил на ${HEALTH_PATH}.`
      );
      if (next == null) return null;
      port = next;
      continue;
    }

    const next = await promptForPort(
      port,
      `Порт ${port} уже используется другим процессом, и health-check не прошёл.`
    );
    if (next == null) return null;
    port = next;
  }

  return null;
}

function buildMenu(port) {
  currentPort = port;
  const settings = loadSettings();
  const lang = resolveAppLang(settings);
  const newWindowItems = [
    {
      label: menuLabel("menu_current_page", lang),
      accelerator: "CmdOrCtrl+Shift+N",
      click: () => {
        openCurrentPageInNewWindow(currentPort).catch((err) => {
          dialog.showErrorBox(
            "BotBuilder",
            `${menuLabel("dialog_open_failed", lang)}:\n${err.message || err}`
          );
        });
      },
    },
    { type: "separator" },
    ...APP_WINDOWS.map((item) => ({
      label: windowTitleForSpec(item, lang),
      click: () => {
        openAppWindowById(currentPort, item.id).catch((err) => {
          dialog.showErrorBox(
            "BotBuilder",
            `${menuLabel("dialog_open_failed", lang)}:\n${err.message || err}`
          );
        });
      },
    })),
  ];

  const template = [
    {
      label: menuLabel("menu_settings", lang),
      submenu: [
        {
          label: menuLabel("menu_settings_open", lang),
          accelerator: "CmdOrCtrl+,",
          click: async () => {
            await showSettingsWithRestartPrompt(loadSettings());
          },
        },
        { type: "separator" },
        {
          label: `API: http://${HOST}:${port}`,
          enabled: false,
        },
        { type: "separator" },
        { role: "quit", label: menuLabel("menu_quit", lang) },
      ],
    },
    {
      label: menuLabel("menu_view", lang),
      submenu: [
        {
          label: menuLabel("menu_new_window", lang),
          submenu: newWindowItems,
        },
        { type: "separator" },
        { role: "reload", label: menuLabel("menu_reload", lang) },
        { role: "forceReload", label: menuLabel("menu_force_reload", lang) },
        { role: "toggleDevTools", label: menuLabel("menu_devtools", lang) },
        { type: "separator" },
        { role: "resetZoom", label: menuLabel("menu_reset_zoom", lang) },
        { role: "zoomIn", label: menuLabel("menu_zoom_in", lang) },
        { role: "zoomOut", label: menuLabel("menu_zoom_out", lang) },
        { type: "separator" },
        {
          label: menuLabel("menu_theme_light", lang),
          type: "radio",
          checked: settings.theme === "light",
          click: () => setAppTheme("light"),
        },
        {
          label: menuLabel("menu_theme_dark", lang),
          type: "radio",
          checked: settings.theme === "dark",
          click: () => setAppTheme("dark"),
        },
        {
          label: menuLabel("menu_theme_toggle", lang),
          accelerator: "CmdOrCtrl+Shift+L",
          click: () => setAppTheme(settings.theme === "dark" ? "light" : "dark"),
        },
      ],
    },
    {
      label: menuLabel("menu_help", lang),
      submenu: [
        {
          label: menuLabel("menu_help_info", lang),
          accelerator: "F1",
          click: () => {
            openAppWindowById(currentPort, "info").catch((err) => {
              dialog.showErrorBox(
                "BotBuilder",
                `${menuLabel("dialog_open_failed", lang)}:\n${err.message || err}`
              );
            });
          },
        },
        { type: "separator" },
        {
          label: menuLabel("menu_data_folder", lang),
          click: () => shell.openPath(getDataDir()),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

/** ERR_ABORTED (-3) — нормально при client-side redirect с index.html на login/dashboard. */
function isAbortedNavigationError(err) {
  if (!err) return false;
  const code = err.errno ?? err.code;
  const message = String(err.message || err);
  return code === -3 || code === "ERR_ABORTED" || message.includes("ERR_ABORTED");
}

async function loadAppUrl(win, url) {
  try {
    await win.loadURL(url);
  } catch (err) {
    if (!isAbortedNavigationError(err)) throw err;
  }
}

function buildAppUrl(port, pagePath, query) {
  const pathPart = pagePath.startsWith("/") ? pagePath : `/${pagePath}`;
  const base = `http://${HOST}:${port}${pathPart}`;
  if (!query) return base;
  const q = String(query).replace(/^\?/, "");
  return `${base}${base.includes("?") ? "&" : "?"}${q}`;
}

function isLocalAppUrl(url) {
  try {
    const parsed = new URL(url);
    return (
      (parsed.hostname === HOST || parsed.hostname === "127.0.0.1") &&
      parsed.protocol === "http:"
    );
  } catch {
    return false;
  }
}

async function createChildWindow(port, spec, options) {
  options = options || {};
  const query = options.query || "";
  const windowKey = options.windowKey || `${spec.id}${query ? `?${query.replace(/^\?/, "")}` : ""}`;
  const existing = childWindows.get(windowKey);
  if (existing && !existing.isDestroyed()) {
    if (existing.isMinimized()) existing.restore();
    existing.focus();
    return existing;
  }

  const settings = loadSettings();
  const win = new BrowserWindow({
    width: spec.width || 1100,
    height: spec.height || 780,
    minWidth: 800,
    minHeight: 500,
    show: false,
    autoHideMenuBar: false,
    title: options.title || windowTitleForSpec(spec, resolveAppLang(settings)) || "BotBuilder",
    icon: getAppIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: getRendererAdditionalArgs(port),
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  win.once("ready-to-show", () => win.show());

  win.on("closed", () => {
    childWindows.delete(windowKey);
  });

  const targetUrl = options.url || buildAppUrl(port, spec.path, query);
  await loadAppUrl(win, targetUrl);
  applyThemeToWindow(win, settings.theme);
  applyLangToWindow(win, resolveAppLang(settings));
  childWindows.set(windowKey, win);
  return win;
}

async function openAppWindowById(port, windowId, query) {
  const spec = APP_WINDOWS.find((item) => item.id === windowId);
  if (!spec) return null;
  return createChildWindow(port, spec, { query: query || "" });
}

async function openCurrentPageInNewWindow(port) {
  const focused = BrowserWindow.getFocusedWindow();
  if (!focused) return null;
  const currentUrl = focused.webContents.getURL();
  if (!isLocalAppUrl(currentUrl)) {
    shell.openExternal(currentUrl);
    return null;
  }
  const parsed = new URL(currentUrl);
  const windowKey = `url:${parsed.pathname}${parsed.search}`;
  const existing = childWindows.get(windowKey);
  if (existing && !existing.isDestroyed()) {
    if (existing.isMinimized()) existing.restore();
    existing.focus();
    return existing;
  }
  const settings = loadSettings();
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 800,
    minHeight: 500,
    show: false,
    autoHideMenuBar: false,
    title: "BotBuilder",
    icon: getAppIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: getRendererAdditionalArgs(port),
    },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.once("ready-to-show", () => win.show());
  win.on("closed", () => childWindows.delete(windowKey));
  await loadAppUrl(win, currentUrl);
  applyThemeToWindow(win, settings.theme);
  applyLangToWindow(win, resolveAppLang(settings));
  childWindows.set(windowKey, win);
  return win;
}

async function createMainWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    show: false,
    autoHideMenuBar: false,
    title: "BotBuilder",
    icon: getAppIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: getRendererAdditionalArgs(port),
    },
  });

  buildMenu(port);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await loadAppUrl(mainWindow, `http://${HOST}:${port}/dashboard/index.html`);
  const bootSettings = loadSettings();
  applyThemeToWindow(mainWindow, bootSettings.theme);
  applyLangToWindow(mainWindow, resolveAppLang(bootSettings));
}

ipcMain.handle("get-port", () => loadSettings().port);
ipcMain.handle("get-settings", () => loadSettings());
ipcMain.handle("theme:set", (event, theme) => {
  const next = theme === "dark" ? "dark" : "light";
  const current = loadSettings().theme || "light";
  if (next === current) return current;
  return setAppTheme(next, {
    exceptWebContentsId: event && event.sender ? event.sender.id : undefined,
  });
});
ipcMain.handle("lang:set", (event, lang) => {
  return setAppLanguage(lang, {
    exceptWebContentsId: event && event.sender ? event.sender.id : undefined,
  });
});
ipcMain.handle("get-app-lang", () => resolveAppLang(loadSettings()));
ipcMain.handle("save-settings", (_event, settings) => {
  const port = Number(settings?.port);
  const undoSteps = Number(settings?.undoSteps ?? DEFAULT_UNDO_STEPS);
  const langRaw = String(settings?.lang || "").slice(0, 2);
  const lang = SUPPORTED_LANGS.has(langRaw) ? langRaw : resolveAppLang(loadSettings());
  if (!Number.isFinite(port) || port < 1024 || port > 65535) {
    throw new Error("Invalid port");
  }
  if (!Number.isFinite(undoSteps) || undoSteps < 1 || undoSteps > 500) {
    throw new Error("Invalid undoSteps");
  }
  const prev = loadSettings();
  saveSettings({
    port,
    undoSteps: Math.floor(undoSteps),
    theme: settings?.theme === "dark" ? "dark" : prev.theme === "dark" ? "dark" : "light",
    lang,
  });
  setAppLanguage(lang);
  return loadSettings();
});

async function showSettingsWithRestartPrompt(initialSettings) {
  const before = loadSettings();
  const lang = resolveAppLang(before);
  const langPack = MENU_LOCALES[lang] || MENU_LOCALES.en;
  const saved = await openSettingsDialog(initialSettings || before);
  if (saved != null && saved.port !== before.port) {
    const detail = String(langPack.dialog_port_changed_detail || "").replace(
      "{port}",
      String(saved.port)
    );
    const { response } = await dialog.showMessageBox({
      type: "info",
      buttons: [langPack.dialog_restart, langPack.dialog_later],
      defaultId: 0,
      message: langPack.dialog_port_changed,
      detail,
    });
    if (response === 0) {
      app.relaunch();
      app.quit();
    }
  }
  return saved;
}

ipcMain.handle("open-settings", async () => {
  return showSettingsWithRestartPrompt(loadSettings());
});

ipcMain.handle("dialog:openBotDatabase", openDatabaseFileDialog);
ipcMain.handle("dialog:openDatabaseFile", openDatabaseFileDialog);
ipcMain.handle("dialog:openTextFile", openTextFileDialog);
ipcMain.handle("dialog:openImportFile", openImportFileDialog);
ipcMain.handle("windows:open", (_event, payload) => {
  const windowId = payload && payload.windowId;
  const query = (payload && payload.query) || "";
  if (!windowId) throw new Error("windowId required");
  return openAppWindowById(currentPort, windowId, query);
});
ipcMain.handle("windows:open-current", () => openCurrentPageInNewWindow(currentPort));

function openDatabaseFileDialog() {
  const win = BrowserWindow.getFocusedWindow() || mainWindow;
  const lang = resolveAppLang(loadSettings());
  const langPack = MENU_LOCALES[lang] || MENU_LOCALES.en;
  return dialog
    .showOpenDialog(win || undefined, {
      title: langPack.dialog_db_title,
      properties: ["openFile"],
      filters: [
        { name: "SQLite / JSON", extensions: ["db", "sqlite", "json"] },
        { name: "SQLite", extensions: ["db", "sqlite"] },
        { name: "JSON export", extensions: ["json"] },
      ],
    })
    .then(function (result) {
      if (result.canceled || !result.filePaths || !result.filePaths.length) {
        return { canceled: true, filePath: null };
      }
      return { canceled: false, filePath: result.filePaths[0] };
    });
}

function openImportFileDialog() {
  const win = BrowserWindow.getFocusedWindow() || mainWindow;
  const lang = resolveAppLang(loadSettings());
  const langPack = MENU_LOCALES[lang] || MENU_LOCALES.en;
  return dialog
    .showOpenDialog(win || undefined, {
      title: langPack.dialog_import_title || "Select import file",
      properties: ["openFile"],
      filters: [
        { name: "Text / JSON", extensions: ["txt", "json"] },
        { name: "Text", extensions: ["txt"] },
        { name: "JSON", extensions: ["json"] },
        { name: "All files", extensions: ["*"] },
      ],
    })
    .then(function (result) {
      if (result.canceled || !result.filePaths || !result.filePaths.length) {
        return { canceled: true, filePath: null };
      }
      return { canceled: false, filePath: result.filePaths[0] };
    });
}

function openTextFileDialog() {
  const win = BrowserWindow.getFocusedWindow() || mainWindow;
  const lang = resolveAppLang(loadSettings());
  const langPack = MENU_LOCALES[lang] || MENU_LOCALES.en;
  return dialog
    .showOpenDialog(win || undefined, {
      title: langPack.dialog_txt_title || "Select .txt file",
      properties: ["openFile"],
      filters: [
        { name: "Text", extensions: ["txt"] },
        { name: "All files", extensions: ["*"] },
      ],
    })
    .then(function (result) {
      if (result.canceled || !result.filePaths || !result.filePaths.length) {
        return { canceled: true, filePath: null };
      }
      return { canceled: false, filePath: result.filePaths[0] };
    });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  if (process.platform === "win32") {
    app.setAppUserModelId("com.botbuilder.desktop");
  }

  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    await ensureAppLanguage();
    const port = await resolveRuntimePort();
    if (port == null) {
      startupPhase = false;
      app.quit();
      return;
    }

    try {
      await createMainWindow(port);
      startupPhase = false;
    } catch (err) {
      startupPhase = false;
      dialog.showErrorBox(
        "BotBuilder",
        `Не удалось открыть окно приложения:\n${err.message || err}`
      );
      await stopSidecar(port);
      app.quit();
    }
  });

  app.on("window-all-closed", async () => {
    if (process.platform !== "darwin") {
      if (startupPhase) return;
      isQuitting = true;
      await stopSidecar(loadSettings().port);
      app.quit();
    }
  });

  app.on("before-quit", async (event) => {
    if (isQuitting) return;
    event.preventDefault();
    isQuitting = true;
    await stopSidecar(loadSettings().port);
    app.quit();
  });

  app.on("activate", async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const port = await resolveRuntimePort();
      if (port != null) await createMainWindow(port);
    }
  });
}
