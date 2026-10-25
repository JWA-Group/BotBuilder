const { contextBridge, ipcRenderer } = require("electron");

const initialPortArg = process.argv.find((a) => a.startsWith("--initial-port="));
const initialUndoArg = process.argv.find((a) => a.startsWith("--initial-undo-steps="));
const initialLangArg = process.argv.find((a) => a.startsWith("--initial-lang="));
const initialThemeArg = process.argv.find((a) => a.startsWith("--initial-theme="));
const initialAiEnabledArg = process.argv.find((a) => a.startsWith("--initial-ai-enabled="));
const initialAiProviderArg = process.argv.find((a) => a.startsWith("--initial-ai-provider="));
const initialAiEndpointArg = process.argv.find((a) => a.startsWith("--initial-ai-endpoint="));
const initialAiModelArg = process.argv.find((a) => a.startsWith("--initial-ai-model="));
const initialAiModelPlannerArg = process.argv.find((a) =>
  a.startsWith("--initial-ai-model-planner=")
);
const initialAiModelCoderArg = process.argv.find((a) => a.startsWith("--initial-ai-model-coder="));
const initialAiModelScenarioArg = process.argv.find((a) =>
  a.startsWith("--initial-ai-model-scenario=")
);
const initialAiModelWorkerArg = process.argv.find((a) =>
  a.startsWith("--initial-ai-model-worker=")
);
const initialAiKeyArg = process.argv.find((a) => a.startsWith("--initial-ai-key="));

function decodeArg(raw, prefix) {
  try {
    return decodeURIComponent(raw.slice(prefix.length));
  } catch {
    return raw.slice(prefix.length);
  }
}

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

const initialAiModel = initialAiModelArg
  ? decodeArg(initialAiModelArg, "--initial-ai-model=") || "gpt-4o"
  : "gpt-4o";

contextBridge.exposeInMainWorld("settingsBridge", {
  initialPort: Number.isFinite(initialPort) ? initialPort : 8000,
  initialUndoSteps:
    Number.isFinite(initialUndoSteps) && initialUndoSteps >= 1 ? initialUndoSteps : 30,
  initialLang: ["en", "ru", "es"].includes(initialLang) ? initialLang : "en",
  initialTheme: initialTheme === "dark" ? "dark" : "light",
  initialAiEnabled: initialAiEnabledArg
    ? initialAiEnabledArg.slice("--initial-ai-enabled=".length) === "1"
    : false,
  initialAiProvider: initialAiProviderArg
    ? decodeArg(initialAiProviderArg, "--initial-ai-provider=") || "custom"
    : "custom",
  initialAiEndpoint: initialAiEndpointArg
    ? decodeArg(initialAiEndpointArg, "--initial-ai-endpoint=") || "https://api.openai.com/v1"
    : "https://api.openai.com/v1",
  initialAiModel,
  initialAiModelPlanner: initialAiModelPlannerArg
    ? decodeArg(initialAiModelPlannerArg, "--initial-ai-model-planner=") || initialAiModel
    : initialAiModel,
  initialAiModelCoder: initialAiModelCoderArg
    ? decodeArg(initialAiModelCoderArg, "--initial-ai-model-coder=") || initialAiModel
    : initialAiModel,
  initialAiModelScenario: initialAiModelScenarioArg
    ? decodeArg(initialAiModelScenarioArg, "--initial-ai-model-scenario=") || initialAiModel
    : initialAiModel,
  initialAiModelWorker: initialAiModelWorkerArg
    ? decodeArg(initialAiModelWorkerArg, "--initial-ai-model-worker=")
    : "",
  initialAiKey: initialAiKeyArg ? decodeArg(initialAiKeyArg, "--initial-ai-key=") : "",
  save: (settings) => ipcRenderer.send("settings-save", settings),
  cancel: () => ipcRenderer.send("settings-cancel"),
});
