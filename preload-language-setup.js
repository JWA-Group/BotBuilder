const { contextBridge, ipcRenderer } = require("electron");



contextBridge.exposeInMainWorld("languageSetupBridge", {

  choose: (payload) => ipcRenderer.send("language-setup-choose", payload),

});

