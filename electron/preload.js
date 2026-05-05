const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('axiomWindow', {
  isElectron: true,
  minimize: () => ipcRenderer.invoke('window:minimize'),
  close: () => ipcRenderer.invoke('window:close'),
  quit: () => ipcRenderer.invoke('window:quit'),
});
