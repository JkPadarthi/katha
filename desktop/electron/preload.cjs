const { contextBridge, ipcRenderer } = require('electron')

// Minimal bridge for the custom title bar. No node access leaks to the renderer.
contextBridge.exposeInMainWorld('katha', {
  isElectron: true,
  minimize: () => ipcRenderer.send('win:minimize'),
  maximize: () => ipcRenderer.send('win:maximize'),
  close: () => ipcRenderer.send('win:close')
})