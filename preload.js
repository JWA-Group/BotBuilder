/**
 * Secure preload bridge — exposes a minimal desktop API to the renderer.
 * Port is injected synchronously via additionalArguments from the main process.
 */
const { contextBridge, ipcRenderer } = require("electron");

const DEFAULT_PORT = 8000;
const DEFAULT_UNDO_STEPS = 30;
const HOST = "127.0.0.1";

function readPortFromArgv() {
  const match = process.argv.find((arg) => arg.startsWith("--api-port="));
  if (!match) return DEFAULT_PORT;
  const parsed = parseInt(match.slice("--api-port=".length), 10);
  return Number.isFinite(parsed) && parsed > 0 && parsed < 65536 ? parsed : DEFAULT_PORT;
}

function readUndoStepsFromArgv() {
  const match = process.argv.find((arg) => arg.startsWith("--undo-steps="));
  if (!match) return DEFAULT_UNDO_STEPS;
  const parsed = parseInt(match.slice("--undo-steps=".length), 10);
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= 500
    ? Math.floor(parsed)
    : DEFAULT_UNDO_STEPS;
}

function readLangFromArgv() {
  const match = process.argv.find((arg) => arg.startsWith("--app-lang="));
  if (!match) return null;
  const code = match.slice("--app-lang=".length).trim().slice(0, 2);
  return code === "ru" || code === "es" || code === "en" ? code : null;
}

const apiPort = readPortFromArgv();
const undoSteps = readUndoStepsFromArgv();
const appLang = readLangFromArgv();

ipcRenderer.on("app:lang-changed", (_event, lang) => {
  try {
    if (typeof window.__applyLanguageFromMain === "function") {
      window.__applyLanguageFromMain(lang);
    } else if (typeof window.applyLanguage === "function") {
      window.applyLanguage(lang, { silent: true, fromBroadcast: true });
    }
  } catch (e) {
    /* ignore */
  }
});

contextBridge.exposeInMainWorld("electronAPI", {
  isDesktop: true,
  getHost: () => HOST,
  getPort: () => apiPort,
  getUndoSteps: () => undoSteps,
  getAppLanguage: () => appLang,
  getApiOrigin: () => `http://${HOST}:${apiPort}`,
  getApiBase: () => `http://${HOST}:${apiPort}/api`,
  openSettings: () => ipcRenderer.invoke("open-settings"),
  setAppLanguage: (lang) => ipcRenderer.invoke("lang:set", lang),
  selectDatabaseFile: () => ipcRenderer.invoke("dialog:openDatabaseFile"),
  selectTextFile: () => ipcRenderer.invoke("dialog:openTextFile"),
  selectImportFile: () => ipcRenderer.invoke("dialog:openImportFile"),
  openAppWindow: (windowId, query) =>
    ipcRenderer.invoke("windows:open", { windowId: windowId, query: query || "" }),
  openCurrentPageInNewWindow: () => ipcRenderer.invoke("windows:open-current"),
  notifyThemeChange: (theme) => ipcRenderer.invoke("theme:set", theme),
});
