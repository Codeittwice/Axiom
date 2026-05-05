const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('axiomWindow', {
  isElectron: true,
  minimize: () => ipcRenderer.invoke('window:minimize'),
  toggleFullscreen: () => ipcRenderer.invoke('window:toggle-fullscreen'),
  onFullscreenChanged: callback => {
    const handler = (_event, isFullscreen) => callback(Boolean(isFullscreen));
    ipcRenderer.on('window:fullscreen-changed', handler);
    return () => ipcRenderer.removeListener('window:fullscreen-changed', handler);
  },
  close: () => ipcRenderer.invoke('window:close'),
  quit: () => ipcRenderer.invoke('window:quit'),
});
