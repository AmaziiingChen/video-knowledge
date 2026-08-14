const { app, BrowserWindow, clipboard, dialog, shell, ipcMain, net, protocol, safeStorage, session, Tray, Menu, nativeImage } = require('electron')
const { spawn } = require('child_process')
const { randomUUID } = require('crypto')
const fs = require('fs')
const http = require('http')
const nodeNet = require('net')
const path = require('path')
const { pathToFileURL } = require('url')
const { createCampusWebVpnController } = require('./campus-webvpn.cjs')
const { createPlatformAuthController } = require('./platform-auth.cjs')
const { directChildEnvironment } = require('./network-env.cjs')
const { checkDesktopReleaseUpdate } = require('./release-update.cjs')
const { exportMarkdownDocument } = require('./markdown-export.cjs')
const { isExpectedBackendHealth } = require('./backend-health.cjs')
const {
  backendSpawnOptions,
  clearBackendLease,
  terminateBackendProcess,
  terminateLeasedBackend,
  writeBackendLease,
} = require('./backend-process.cjs')
const { shouldInjectBackendToken, withBackendToken } = require('./backend-request-auth.cjs')
const { applyUserDataDirectoryOverride } = require('./user-data-dir.cjs')
const {
  LEASE_HEARTBEAT_MS,
  createMcpBridgeSession,
  refreshMcpBridgeLease,
  removeMcpBridgeSession,
} = require('./mcp-bridge-session.cjs')

const ROOT_DIR = path.resolve(__dirname, '..', '..')
const BACKEND_URL = 'http://127.0.0.1:8000'
const HEALTH_URL = `${BACKEND_URL}/api/health`
const WECHAT_PREVIEW_PARTITION = 'persist:knowledgehub-wechat-preview'
const LOCAL_HTML_PREVIEW_PARTITION = 'persist:knowledgehub-local-html-preview'
const APP_PROTOCOL = 'knowledgehub'
const APP_ORIGIN = `${APP_PROTOCOL}://app`
const BACKEND_INSTANCE_TOKEN = randomUUID()

// Release checks use this explicit, process-local override so an isolated DMG
// run never opens the user's real Electron profile. Normal launches retain
// Electron's platform-default userData path.
applyUserDataDirectoryOverride(app)

// KnowledgeHub owns explicit direct-network clients. Do not let Electron
// navigation or platform login windows silently follow the macOS system proxy.
app.commandLine.appendSwitch('no-proxy-server')

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_PROTOCOL,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
])

let backendProcess = null
let mcpBridgeSession = null
let mcpBridgeLeaseTimer = null
let mainWindow = null
let campusWebVpn = null
let platformAuth = null
let isQuitting = false
let backendReady = false
let backendReadyWaiters = []
let notificationTray = null
let pendingNotifications = []
let unreadDockBadgeCount = 0

function trayIcon() {
  const image = nativeImage.createFromPath(path.join(__dirname, 'assets', 'trayTemplate.png'))
  image.setTemplateImage(true)
  return image
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow()
    return
  }
  mainWindow.show()
  mainWindow.focus()
}

function sendRendererMenuAction(action) {
  showMainWindow()
  if (!mainWindow || mainWindow.isDestroyed()) return
  const deliver = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    mainWindow.webContents.send('knowledgehub:menu-action', action)
  }
  if (mainWindow.webContents.isLoading()) {
    mainWindow.webContents.once('did-finish-load', deliver)
  } else {
    deliver()
  }
}

function createApplicationMenu() {
  const action = (id) => () => sendRendererMenuAction(id)
  const template = [
    {
      label: 'KnowledgeHub',
      submenu: [
        { role: 'about', label: '关于 KnowledgeHub' },
        { type: 'separator' },
        { label: '设置…', accelerator: 'CommandOrControl+,', click: action('settings') },
        { label: '检查更新…', click: action('check-for-update') },
        { type: 'separator' },
        { role: 'hide', label: '隐藏 KnowledgeHub' },
        { role: 'hideOthers', label: '隐藏其他应用' },
        { role: 'unhide', label: '显示全部' },
        { type: 'separator' },
        { role: 'quit', label: '退出 KnowledgeHub' },
      ],
    },
    {
      label: '文件',
      submenu: [
        { label: '导入本地资料…', accelerator: 'CommandOrControl+O', click: action('import-local-files') },
      ],
    },
    { role: 'editMenu', label: '编辑' },
    {
      label: '视图',
      submenu: [
        { label: '快速打开…', accelerator: 'CommandOrControl+K', click: action('open-command-palette') },
        { type: 'separator' },
        { label: '显示或隐藏文件栏', accelerator: 'CommandOrControl+Shift+L', click: action('toggle-primary-sidebar') },
        { label: '显示或隐藏右侧栏', accelerator: 'CommandOrControl+Shift+I', click: action('toggle-context-sidebar') },
        { label: '显示或隐藏处理日志', accelerator: 'CommandOrControl+Shift+J', click: action('toggle-process-log') },
      ],
    },
    {
      label: '工具',
      submenu: [
        { label: '切换剪贴板监听', click: action('toggle-clipboard-watching') },
        { label: '刷新资料库', click: action('refresh-library') },
      ],
    },
    {
      role: 'window',
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'zoom', label: '缩放' },
        { type: 'separator' },
        { role: 'front', label: '置于前台' },
      ],
    },
    {
      role: 'help',
      label: '帮助',
      submenu: [
        { label: '检查更新…', click: action('check-for-update') },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function updateNotificationTray() {
  if (!notificationTray) return
  const entries = pendingNotifications.slice(0, 8).map((item) => ({
    label: String(item.title || '待查看资料').replace(/\s+/g, ' ').slice(0, 54),
    toolTip: String(item.body || item.title || ''),
    click: () => {
      showMainWindow()
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('knowledgehub:open-pending-notification', item)
    },
  }))
  const unread = pendingNotifications.length
  notificationTray.setTitle(unread ? String(unread) : '')
  notificationTray.setToolTip(unread ? `KnowledgeHub：${unread} 条待查看` : 'KnowledgeHub')
  notificationTray.setContextMenu(Menu.buildFromTemplate([
    { label: unread ? `待查看 ${unread} 条` : '暂无待查看事项', enabled: false },
    ...(entries.length ? entries : []),
    { type: 'separator' },
    { label: '打开 KnowledgeHub', click: showMainWindow },
    { label: '退出 KnowledgeHub', click: () => app.quit() },
  ]))
}

function createNotificationTray() {
  if (process.platform !== 'darwin' || notificationTray) return
  notificationTray = new Tray(trayIcon())
  notificationTray.on('click', showMainWindow)
  updateNotificationTray()
}

function setUnreadDockBadgeCount(value) {
  const numericValue = Number(value)
  unreadDockBadgeCount = Number.isFinite(numericValue)
    ? Math.min(999, Math.max(0, Math.floor(numericValue)))
    : 0
  if (process.platform === 'darwin') app.setBadgeCount(unreadDockBadgeCount)
  return unreadDockBadgeCount
}

function markBackendReady() {
  backendReady = true
  for (const resolve of backendReadyWaiters) resolve(true)
  backendReadyWaiters = []
}

function logRendererDiagnostic(kind, detail) {
  try {
    const runtime = backendRuntime()
    fs.mkdirSync(runtime.logDir, { recursive: true })
    const entry = `[${new Date().toISOString()}] ${kind}: ${detail}\n`
    fs.appendFileSync(path.join(runtime.logDir, 'desktop-frontend.log'), entry)
  } catch {
    // Diagnostics must never prevent the desktop window from opening.
  }
}

function normalizeExternalUrl(value) {
  try {
    const url = new URL(String(value || ''))
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.toString() : ''
  } catch {
    return ''
  }
}

async function openExternalUrl(value) {
  const url = normalizeExternalUrl(value)
  if (!url) throw new Error('不支持的外部链接')
  await shell.openExternal(url)
  return true
}

function isWechatPreviewUrl(value) {
  try {
    const url = new URL(String(value || ''))
    return url.protocol === 'https:' && url.hostname === 'mp.weixin.qq.com'
  } catch {
    return false
  }
}

function isLocalHtmlPreviewUrl(value) {
  try {
    const url = new URL(String(value || ''))
    return url.protocol === 'https:'
  } catch {
    return false
  }
}

function isSameSiteLocalHtmlPreviewNavigation(currentValue, nextValue) {
  try {
    const current = new URL(String(currentValue || ''))
    const next = new URL(String(nextValue || ''))
    return current.protocol === 'https:'
      && next.protocol === 'https:'
      && current.hostname === next.hostname
      && current.port === next.port
  } catch {
    return false
  }
}

function configureWechatPreviewSession() {
  const previewSession = session.fromPartition(WECHAT_PREVIEW_PARTITION)
  previewSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  return previewSession
}

function configureLocalHtmlPreviewSession() {
  const previewSession = session.fromPartition(LOCAL_HTML_PREVIEW_PARTITION)
  previewSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  return previewSession
}

function frontendAssetsDirectory() {
  return app.isPackaged
    ? path.join(app.getAppPath(), 'dist')
    : path.join(ROOT_DIR, 'frontend', 'dist')
}

function registerLocalAppProtocol() {
  protocol.handle(APP_PROTOCOL, (request) => {
    try {
      const url = new URL(request.url)
      if (url.protocol !== `${APP_PROTOCOL}:` || url.hostname !== 'app') {
        return new Response('Not found', { status: 404 })
      }
      const relativePath = decodeURIComponent(url.pathname).replace(/^\/+/, '') || 'index.html'
      const root = frontendAssetsDirectory()
      const target = path.resolve(root, relativePath)
      const relativeTarget = path.relative(root, target)
      if (relativeTarget.startsWith('..') || path.isAbsolute(relativeTarget) || !fs.statSync(target).isFile()) {
        return new Response('Not found', { status: 404 })
      }
      return net.fetch(pathToFileURL(target).toString())
    } catch {
      return new Response('Not found', { status: 404 })
    }
  })
}

function isTrustedDesktopRenderer(event) {
  if (!mainWindow || mainWindow.isDestroyed() || event?.sender !== mainWindow.webContents) return false
  const frameUrl = String(event?.senderFrame?.url || event.sender.getURL() || '')
  return frameUrl === APP_ORIGIN || frameUrl.startsWith(`${APP_ORIGIN}/`)
}

function trustedIpcHandler(handler) {
  return (event, ...args) => {
    if (!isTrustedDesktopRenderer(event)) throw new Error('未授权的桌面渲染进程')
    return handler(...args)
  }
}

ipcMain.handle('knowledgehub:choose-directory', trustedIpcHandler(async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'] })
  return result.canceled ? '' : (result.filePaths[0] || '')
}))

ipcMain.handle('knowledgehub:choose-executable', trustedIpcHandler(async (toolName = '') => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: toolName ? `选择 ${toolName} 可执行文件` : '选择可执行文件',
    properties: ['openFile'],
  })
  return result.canceled ? '' : (result.filePaths[0] || '')
}))

ipcMain.handle('knowledgehub:export-markdown', trustedIpcHandler(async (payload = {}) => {
  const runtime = backendRuntime()
  const request = payload && typeof payload === 'object' ? payload : {}
  return exportMarkdownDocument({
    dataDir: runtime.dataDir,
    title: request.title,
    markdown: request.markdown,
  })
}))

ipcMain.handle('knowledgehub:copy-text', trustedIpcHandler((value) => {
  const text = typeof value === 'string' ? value : ''
  if (!text.trim()) throw new Error('没有可复制的内容')
  clipboard.writeText(text)
  return true
}))

ipcMain.handle('knowledgehub:reveal-path', trustedIpcHandler((value) => {
  const requestedPath = typeof value === 'string' ? value.trim() : ''
  if (!requestedPath) throw new Error('没有可打开的位置')
  const targetPath = path.resolve(requestedPath)
  if (!fs.existsSync(targetPath)) throw new Error('文件或文件夹不存在')
  shell.showItemInFolder(targetPath)
  return true
}))

ipcMain.handle('knowledgehub:open-path', trustedIpcHandler(async (value) => {
  const requestedPath = typeof value === 'string' ? value.trim() : ''
  if (!requestedPath) throw new Error('没有可打开的文件')
  const targetPath = path.resolve(requestedPath)
  if (!fs.existsSync(targetPath)) throw new Error('原始文件不存在')
  const error = await shell.openPath(targetPath)
  if (error) throw new Error(error)
  return true
}))

ipcMain.handle('knowledgehub:open-external', trustedIpcHandler(async (url = '') => openExternalUrl(url)))
ipcMain.handle('knowledgehub:check-for-update', trustedIpcHandler(async () => checkDesktopReleaseUpdate({
  fetcher: net.fetch.bind(net),
  currentVersion: app.getVersion(),
})))
ipcMain.handle('knowledgehub:backend-access-token', trustedIpcHandler(() => {
  return BACKEND_INSTANCE_TOKEN
}))
ipcMain.handle('knowledgehub:wait-for-backend', trustedIpcHandler(() => {
  if (backendReady) return true
  return new Promise((resolve) => backendReadyWaiters.push(resolve))
}))
ipcMain.handle('knowledgehub:set-pending-notifications', trustedIpcHandler((items = []) => {
  pendingNotifications = Array.isArray(items)
    ? items.slice(0, 100).map((item) => ({
      id: String(item?.id || ''), title: String(item?.title || '').slice(0, 240),
      body: String(item?.body || '').slice(0, 800), content_item_id: String(item?.content_item_id || ''),
      target_view: String(item?.target_view || 'library'),
    })).filter((item) => item.id && item.title)
    : []
  updateNotificationTray()
  return true
}))
ipcMain.handle('knowledgehub:set-unread-badge-count', trustedIpcHandler((count = 0) => {
  return setUnreadDockBadgeCount(count)
}))

ipcMain.handle('knowledgehub:campus-auth-status', trustedIpcHandler(async () => campusWebVpn.status()))

ipcMain.handle('knowledgehub:campus-connect', trustedIpcHandler(async () => campusWebVpn.connect(mainWindow)))

ipcMain.handle('knowledgehub:campus-disconnect', trustedIpcHandler(async () => campusWebVpn.disconnect()))

ipcMain.handle('knowledgehub:campus-sync-gwt', trustedIpcHandler(async (request = 20) => campusWebVpn.sync(request)))
ipcMain.handle('knowledgehub:campus-download-attachment', trustedIpcHandler(async (payload = {}) => {
  const request = payload && typeof payload === 'object' ? payload : {}
  return campusWebVpn.downloadAttachment(request.url, request.name)
}))

ipcMain.handle('knowledgehub:platform-auth-connect', trustedIpcHandler(async (platform) => platformAuth.connect(platform, mainWindow)))
ipcMain.handle('knowledgehub:platform-auth-disconnect', trustedIpcHandler(async (platform) => platformAuth.disconnect(platform)))

function waitForHealth(url, timeoutMs = 45000, earlyFailure = () => '') {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
      inspectBackendHealth(url).then((health) => {
        if (health.ready) {
          resolve()
          return
        }
        const failure = earlyFailure()
        if (failure) {
          reject(new Error(failure))
          return
        }
        if (Date.now() - started > timeoutMs) {
          reject(new Error('后端服务启动超时'))
          return
        }
        setTimeout(tick, 500)
      })
    }
    tick()
  })
}

function isExpectedBackendProcess(pid) {
  try {
    const command = require('child_process').execFileSync(
      'ps', ['-p', String(pid), '-o', 'command='],
      { encoding: 'utf8', timeout: 1000 },
    )
    return /knowledgehub-backend|uvicorn\s+main:app/.test(command)
  } catch {
    return false
  }
}

function inspectBackendHealth(url) {
  return new Promise((resolve) => {
    const request = http.get(url, {
      timeout: 1200,
      headers: { 'X-KnowledgeHub-Token': BACKEND_INSTANCE_TOKEN },
    }, (response) => {
      let body = ''
      response.setEncoding('utf8')
      response.on('data', (chunk) => {
        if (body.length < 16_384) body += chunk
      })
      response.on('end', () => {
        let payload = null
        try {
          payload = JSON.parse(body)
        } catch {
          payload = null
        }
        resolve({
          reachable: true,
          ready: response.statusCode >= 200
            && response.statusCode < 300
            && isExpectedBackendHealth(payload, BACKEND_INSTANCE_TOKEN),
        })
      })
    })
    request.on('timeout', () => {
      request.destroy()
      resolve({ reachable: false, ready: false })
    })
    request.on('error', () => resolve({ reachable: false, ready: false }))
  })
}

function isPortOccupied(port = 8000) {
  return new Promise((resolve) => {
    const socket = nodeNet.connect({ host: '127.0.0.1', port })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => resolve(false))
    socket.setTimeout(300, () => {
      socket.destroy()
      resolve(true)
    })
  })
}

async function waitForPortRelease(port = 8000, timeoutMs = 4000) {
  const started = Date.now()
  while (await isPortOccupied(port)) {
    if (Date.now() - started >= timeoutMs) return false
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  return true
}

function pickPython() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN
  if (process.platform === 'win32') return 'python'
  const candidates = [
    '/opt/miniconda3/bin/python',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    'python3',
  ]
  return candidates.find((candidate) => candidate === 'python3' || fs.existsSync(candidate)) || 'python3'
}

function backendRuntime() {
  if (!app.isPackaged) {
    const dataDir = path.join(ROOT_DIR, 'data')
    const args = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000']
    // The Finder launcher is used as a local, long-running application. A
    // uvicorn reloader tears down its HTTP worker on every saved backend file,
    // then waits for any active download/transcription/AI worker to finish.
    // That leaves port 8000 occupied but unable to answer /api/health, so a
    // second launch misleadingly reports a startup timeout. Keep this normal
    // launcher stable; developers can explicitly opt in to hot reload.
    if (process.env.KNOWLEDGEHUB_SOURCE_RELOAD === '1') {
      args.push('--reload', '--reload-dir', path.join(ROOT_DIR, 'backend'))
    }
    return {
      cwd: path.join(ROOT_DIR, 'backend'),
      command: pickPython(),
      args,
      dataDir,
      envFile: path.join(ROOT_DIR, 'backend', '.env'),
      logDir: path.join(dataDir, 'logs'),
      runDir: path.join(dataDir, 'run'),
    }
  }

  const dataDir = path.join(app.getPath('userData'), 'data')
  const executable = process.platform === 'win32' ? 'knowledgehub-backend.exe' : 'knowledgehub-backend'
  return {
    cwd: path.join(process.resourcesPath, 'backend', 'knowledgehub-backend'),
    command: path.join(process.resourcesPath, 'backend', 'knowledgehub-backend', executable),
    args: [],
    dataDir,
    envFile: path.join(app.getPath('userData'), 'settings.env'),
    logDir: path.join(dataDir, 'logs'),
    runDir: path.join(app.getPath('userData'), 'run'),
  }
}

function stopMcpBridgeSession({ ignoreErrors = false } = {}) {
  if (mcpBridgeLeaseTimer) clearInterval(mcpBridgeLeaseTimer)
  mcpBridgeLeaseTimer = null
  if (!mcpBridgeSession) return
  const session = mcpBridgeSession
  mcpBridgeSession = null
  try {
    removeMcpBridgeSession(session)
  } catch (error) {
    if (!ignoreErrors) throw error
  }
}

function startMcpBridgeSession(runDir) {
  stopMcpBridgeSession()
  mcpBridgeSession = createMcpBridgeSession(runDir, `${BACKEND_URL}/api`)
  mcpBridgeLeaseTimer = setInterval(() => {
    try {
      if (!mcpBridgeSession) return
      refreshMcpBridgeLease(mcpBridgeSession)
    } catch (error) {
      stopMcpBridgeSession({ ignoreErrors: true })
      const failedBackend = backendProcess
      backendProcess = null
      terminateBackendProcess(failedBackend)
      if (!isQuitting) dialog.showErrorBox('KnowledgeHub MCP 已停止', error.message)
    }
  }, LEASE_HEARTBEAT_MS)
  mcpBridgeLeaseTimer.unref?.()
  return mcpBridgeSession
}

async function ensureBackend() {
  const runtime = backendRuntime()
  const existingHealth = await inspectBackendHealth(HEALTH_URL)
  if (existingHealth.ready) return
  if (existingHealth.reachable) {
    throw new Error('本机端口 8000 已被另一个后端或其他服务占用，请先关闭该进程后重试')
  }
  const terminatedLease = terminateLeasedBackend(runtime.runDir, { isExpectedBackendProcess })
  if (terminatedLease && !(await waitForPortRelease())) {
    throw new Error('上一轮 KnowledgeHub 后端未能停止，请完全退出旧版 KnowledgeHub 后重试')
  }
  fs.mkdirSync(runtime.logDir, { recursive: true })
  const bridgeSession = startMcpBridgeSession(runtime.runDir)
  const backendLog = path.join(runtime.logDir, 'desktop-backend.log')
  let log = null
  const pathEntries = process.platform === 'darwin'
    ? ['/opt/miniconda3/bin', '/opt/homebrew/bin', '/usr/local/bin', process.env.PATH || '']
    : [process.env.PATH || '']
  const env = {
    ...directChildEnvironment(process.env),
    PATH: pathEntries.filter(Boolean).join(path.delimiter),
    NO_PROXY: '127.0.0.1,localhost',
    no_proxy: '127.0.0.1,localhost',
    DATA_DIR: runtime.dataDir,
    KNOWLEDGEHUB_ENV_FILE: runtime.envFile,
    KNOWLEDGEHUB_BACKEND_HOST: '127.0.0.1',
    KNOWLEDGEHUB_BACKEND_PORT: '8000',
    KNOWLEDGEHUB_INSTANCE_TOKEN: BACKEND_INSTANCE_TOKEN,
    KNOWLEDGEHUB_MCP_BRIDGE_TOKEN: bridgeSession.token,
    KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID: bridgeSession.sessionId,
    KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE: bridgeSession.tokenFile,
    KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE: bridgeSession.leaseFile,
    APP_VERSION: app.getVersion(),
  }

  try {
    log = fs.openSync(backendLog, 'a')
    backendProcess = spawn(
      runtime.command,
      runtime.args,
      {
        cwd: runtime.cwd,
        env,
        stdio: ['ignore', log, log],
        ...backendSpawnOptions(),
      },
    )
    fs.closeSync(log)
    log = null

    const spawnedBackend = backendProcess
    let backendExit = null
    writeBackendLease(runtime.runDir, spawnedBackend)
    spawnedBackend.on('exit', (code, signal) => {
      backendExit = { code, signal }
      clearBackendLease(runtime.runDir, spawnedBackend.pid)
      if (backendProcess === spawnedBackend) backendProcess = null
      stopMcpBridgeSession({ ignoreErrors: true })
    })

    await waitForHealth(HEALTH_URL, 45000, () => {
      if (!backendExit) return ''
      return '本机后端启动后立即退出；端口 8000 可能仍被旧版进程占用，请完全退出旧版 KnowledgeHub 后重试'
    })
  } catch (error) {
    if (log !== null) fs.closeSync(log)
    const failedBackend = backendProcess
    backendProcess = null
    terminateBackendProcess(failedBackend)
    clearBackendLease(runtime.runDir, failedBackend?.pid)
    stopMcpBridgeSession({ ignoreErrors: true })
    throw error
  }
}

function createWindow(entryPath = 'index.html') {
  const macTitleBarOptions = process.platform === 'darwin'
    ? { titleBarStyle: 'hidden', trafficLightPosition: { x: 14, y: 14 } }
    : {}
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 980,
    minHeight: 680,
    title: 'KnowledgeHub',
    frame: false,
    ...macTitleBarOptions,
    backgroundColor: '#FDF6E3',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  })

  // Native media, iframe and image loads cannot attach the renderer's custom
  // header. Inject the capability only for requests attributed to this exact
  // trusted main renderer, never for remote webview partitions.
  mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: [`${BACKEND_URL}/api/*`] },
    (details, callback) => {
      if (!shouldInjectBackendToken(details, mainWindow?.webContents?.id)) {
        callback({ cancel: false, requestHeaders: details.requestHeaders })
        return
      }
      callback({
        cancel: false,
        requestHeaders: withBackendToken(details.requestHeaders, BACKEND_INSTANCE_TOKEN),
      })
    },
  )

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.on('console-message', (event, legacyDetails) => {
    // Electron 42 moved console fields onto the event object.  Accept the
    // former shape too so a renderer exception never turns into a blank log
    // entry (which made a white screen impossible to diagnose).
    const details = event?.message !== undefined ? event : legacyDetails
    if (Number(details?.level) < 2) return
    logRendererDiagnostic(
      'renderer-console',
      `${details?.sourceId || 'unknown'}:${details?.lineNumber || 0} ${details?.message || '未提供错误文本'}`,
    )
  })
  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    logRendererDiagnostic('load-failed', `${errorCode} ${errorDescription} (${validatedURL})`)
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    logRendererDiagnostic('renderer-gone', `${details.reason || 'unknown'} (${details.exitCode ?? ''})`)
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void openExternalUrl(url).catch(() => {})
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-attach-webview', (event, webPreferences, params) => {
    const isWechatPreview = isWechatPreviewUrl(params.src) && params.partition === WECHAT_PREVIEW_PARTITION
    const isLocalHtmlPreview = isLocalHtmlPreviewUrl(params.src) && params.partition === LOCAL_HTML_PREVIEW_PARTITION
    if (!isWechatPreview && !isLocalHtmlPreview) {
      event.preventDefault()
      return
    }
    webPreferences.contextIsolation = true
    webPreferences.nodeIntegration = false
    webPreferences.sandbox = true
    webPreferences.webSecurity = true
    delete webPreferences.preload
  })

  mainWindow.webContents.on('did-attach-webview', (_event, guestContents) => {
    const isWechatPreview = guestContents.session === session.fromPartition(WECHAT_PREVIEW_PARTITION)
    const isLocalHtmlPreview = guestContents.session === session.fromPartition(LOCAL_HTML_PREVIEW_PARTITION)
    guestContents.setWindowOpenHandler(({ url }) => {
      if (isLocalHtmlPreview && isSameSiteLocalHtmlPreviewNavigation(guestContents.getURL(), url)) {
        void guestContents.loadURL(url).catch(() => {})
        return { action: 'deny' }
      }
      void openExternalUrl(url).catch(() => {})
      return { action: 'deny' }
    })
    guestContents.on('before-input-event', (event, input) => {
      const key = String(input?.key || '').toLowerCase()
      if (input?.type !== 'keyDown' || key !== 'f' || !(input.control || input.meta) || input.alt) return
      event.preventDefault()
      if (!mainWindow?.isDestroyed()) mainWindow.webContents.send('knowledgehub:preview-find')
    })
    if (isWechatPreview) {
      guestContents.on('will-navigate', (event, url) => {
        if (isWechatPreviewUrl(url)) return
        event.preventDefault()
        void openExternalUrl(url).catch(() => {})
      })
    } else if (isLocalHtmlPreview) {
      let isInitialPageLoad = true
      guestContents.once('did-finish-load', () => {
        isInitialPageLoad = false
      })
      guestContents.on('will-navigate', (event, url) => {
        // Keep same-site reading navigation in the in-app preview.  The
        // original load may also follow HTTPS redirects; other destinations
        // remain external so this surface never becomes a general browser.
        if (isInitialPageLoad && isLocalHtmlPreviewUrl(url)) return
        if (isSameSiteLocalHtmlPreviewNavigation(guestContents.getURL(), url)) return
        event.preventDefault()
        void openExternalUrl(url).catch(() => {})
      })
    }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url.startsWith(`${APP_ORIGIN}/`)) return
    event.preventDefault()
    void openExternalUrl(url).catch(() => {})
  })

  mainWindow.on('close', (event) => {
    if (process.platform === 'darwin' && !isQuitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  const entryHtml = path.join(frontendAssetsDirectory(), entryPath)
  if (!fs.existsSync(entryHtml)) {
    throw new Error(`未找到前端资源：${entryHtml}`)
  }
  mainWindow.loadURL(`${APP_ORIGIN}/${entryPath}`)
}

app.whenReady().then(async () => {
  registerLocalAppProtocol()
  configureWechatPreviewSession()
  configureLocalHtmlPreviewSession()
  campusWebVpn = createCampusWebVpnController({ app, BrowserWindow, session, safeStorage, dialog })
  platformAuth = createPlatformAuthController({
    BrowserWindow,
    session,
    backendUrl: BACKEND_URL,
    backendToken: BACKEND_INSTANCE_TOKEN,
  })
  // Render the real Vue workbench immediately. Its data hydration waits on the
  // bridge below, so the visible shell does not make failed API requests while
  // Python is still booting.
  createApplicationMenu()
  createWindow()
  createNotificationTray()

  try {
    await ensureBackend()
    markBackendReady()
  } catch (error) {
    dialog.showErrorBox(
      'KnowledgeHub 启动失败',
      `${error.message}\n\n后端日志：${path.join(backendRuntime().logDir, 'desktop-backend.log')}`,
    )
    app.quit()
  }
})

app.on('activate', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show()
    mainWindow.focus()
  } else {
    createWindow()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  setUnreadDockBadgeCount(0)
  stopMcpBridgeSession({ ignoreErrors: true })
  terminateBackendProcess(backendProcess)
  clearBackendLease(backendRuntime().runDir, backendProcess?.pid)
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
