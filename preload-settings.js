const { contextBridge, ipcRenderer } = require("electron");

const initialPortArg = process.argv.find((a) => a.startsWith("--initial-port="));
const initialUndoArg = process.argv.find((a) => a.startsWith("--initial-undo-steps="));
const initialLangArg = process.argv.find((a) => a.startsWith("--initial-lang="));
const initialThemeArg = process.argv.find((a) => a.startsWith("--initial-theme="));

const initialPort = initialPortArg
  ? parseInt(initialPortArg.slice("--initial-port=".length), 10)
  : 8000;
const initialUndoSteps = initialUndoArg
  ? parseInt(initialUndoArg.slice("--initial-undo-steps=".length), 10)
  : 30;
const initialLang = initialLangArg
  ? initialLangArg.slice("--initial-lang=".length)
  : "en";
const initialTheme = initialThemeArg
  ? initialThemeArg.slice("--initial-theme=".length)
  : "light";

contextBridge.exposeInMainWorld("settingsBridge", {
  initialPort: Number.isFinite(initialPort) ? initialPort : 8000,
  initialUndoSteps:
    Number.isFinite(initialUndoSteps) && initialUndoSteps >= 1 ? initialUndoSteps : 30,
  initialLang: ["en", "ru", "es"].includes(initialLang) ? initialLang : "en",
  initialTheme: initialTheme === "dark" ? "dark" : "light",
  save: (settings) => ipcRenderer.send("settings-save", settings),
  cancel: () => ipcRenderer.send("settings-cancel"),
});
