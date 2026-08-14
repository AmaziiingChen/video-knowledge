const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('knowledgeHubDesktop', {
  isDesktop: true,
  chooseDirectory: () => ipcRenderer.invoke('knowledgehub:choose-directory'),
  chooseExecutable: (toolName) => ipcRenderer.invoke('knowledgehub:choose-executable', toolName),
  exportMarkdown: (title, markdown) => ipcRenderer.invoke('knowledgehub:export-markdown', { title, markdown }),
  copyText: (text) => ipcRenderer.invoke('knowledgehub:copy-text', text),
  revealPath: (path) => ipcRenderer.invoke('knowledgehub:reveal-path', path),
  openPath: (path) => ipcRenderer.invoke('knowledgehub:open-path', path),
  openExternal: (url) => ipcRenderer.invoke('knowledgehub:open-external', url),
  checkForUpdate: () => ipcRenderer.invoke('knowledgehub:check-for-update'),
  backendAccessToken: () => ipcRenderer.invoke('knowledgehub:backend-access-token'),
  waitForBackend: () => ipcRenderer.invoke('knowledgehub:wait-for-backend'),
  setPendingNotifications: (items) => ipcRenderer.invoke('knowledgehub:set-pending-notifications', items),
  setUnreadBadgeCount: (count) => ipcRenderer.invoke('knowledgehub:set-unread-badge-count', count),
  campusAuthStatus: () => ipcRenderer.invoke('knowledgehub:campus-auth-status'),
  connectCampusWebVpn: () => ipcRenderer.invoke('knowledgehub:campus-connect'),
  disconnectCampusWebVpn: () => ipcRenderer.invoke('knowledgehub:campus-disconnect'),
  syncCampusGwt: (request = 20) => ipcRenderer.invoke('knowledgehub:campus-sync-gwt', request),
  downloadCampusAttachment: (attachment) => ipcRenderer.invoke('knowledgehub:campus-download-attachment', attachment),
  connectPlatformAuth: (platform) => ipcRenderer.invoke('knowledgehub:platform-auth-connect', platform),
  disconnectPlatformAuth: (platform) => ipcRenderer.invoke('knowledgehub:platform-auth-disconnect', platform),
  onPreviewFind: (listener) => {
    if (typeof listener !== 'function') return () => {}
    const handler = () => listener()
    ipcRenderer.on('knowledgehub:preview-find', handler)
    return () => ipcRenderer.removeListener('knowledgehub:preview-find', handler)
  },
  onOpenPendingNotification: (listener) => {
    if (typeof listener !== 'function') return () => {}
    const handler = (_event, item) => listener(item)
    ipcRenderer.on('knowledgehub:open-pending-notification', handler)
    return () => ipcRenderer.removeListener('knowledgehub:open-pending-notification', handler)
  },
  onMenuAction: (listener) => {
    if (typeof listener !== 'function') return () => {}
    const handler = (_event, action) => listener(action)
    ipcRenderer.on('knowledgehub:menu-action', handler)
    return () => ipcRenderer.removeListener('knowledgehub:menu-action', handler)
  },
})

window.addEventListener('DOMContentLoaded', () => {
  document.documentElement.classList.add('desktop-shell')
})
