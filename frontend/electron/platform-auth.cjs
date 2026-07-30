const http = require('http')

const PLATFORM_CONFIG = {
  bilibili: {
    label: 'B站',
    partition: 'persist:knowledgehub-bilibili-auth',
    loginUrl: 'https://www.bilibili.com/',
    apiPath: '/api/bilibili-cookie',
    statusPath: '/api/creator-sources/health',
    allowedHost: (host) => host === 'bilibili.com' || host.endsWith('.bilibili.com') || host === 'b23.tv' || host.endsWith('.b23.tv'),
    isSignedIn: (cookies) => cookies.some((cookie) => cookie.name === 'SESSDATA'),
  },
  douyin: {
    label: '抖音',
    partition: 'persist:knowledgehub-douyin-auth',
    loginUrl: 'https://www.douyin.com/',
    apiPath: '/api/cookie',
    statusPath: '/api/cookie',
    allowedHost: (host) => host === 'douyin.com' || host.endsWith('.douyin.com'),
    isSignedIn: (cookies) => cookies.some((cookie) => ['sessionid', 'sid_guard'].includes(cookie.name)),
  },
  xiaohongshu: {
    label: '小红书',
    partition: 'persist:knowledgehub-xiaohongshu-auth',
    loginUrl: 'https://www.xiaohongshu.com/',
    apiPath: '/api/xiaohongshu-cookie',
    statusPath: '/api/xiaohongshu-cookie',
    allowedHost: (host) => host === 'xiaohongshu.com' || host.endsWith('.xiaohongshu.com') || host === 'xhslink.com' || host.endsWith('.xhslink.com'),
    // `web_session` is the server-issued login credential accepted by the
    // bundled PC collector; anonymous device cookies alone are insufficient.
    isSignedIn: (cookies) => cookies.some((cookie) => cookie.name === 'web_session'),
  },
}

function createPlatformAuthController({ BrowserWindow, session, backendUrl }) {
  const loginWindows = new Map()

  function configFor(platform) {
    const config = PLATFORM_CONFIG[platform]
    if (!config) throw new Error('不支持的平台登录')
    return config
  }

  function platformSession(platform) {
    const config = configFor(platform)
    const value = session.fromPartition(config.partition, { cache: true })
    value.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
    return value
  }

  function isAllowedUrl(platform, value) {
    try {
      const url = new URL(value)
      return url.protocol === 'https:' && configFor(platform).allowedHost(url.hostname.toLowerCase())
    } catch {
      return false
    }
  }

  async function platformCookies(platform) {
    const config = configFor(platform)
    const cookies = await platformSession(platform).cookies.get({})
    return cookies.filter((cookie) => {
      const host = String(cookie.domain || '').replace(/^\./, '').toLowerCase()
      return config.allowedHost(host) && cookie.name && cookie.value
    })
  }

  async function status(platform, { refresh = false } = {}) {
    const config = configFor(platform)
    const sessionCookies = await platformCookies(platform)
    const endpoint = `${config.statusPath}${refresh ? '?refresh=true' : ''}`
    try {
      const response = await requestJson(backendUrl, endpoint)
      const backendStatus = platform === 'bilibili'
        ? (response.cookies?.bilibili || {})
        : response
      return {
        ...backendStatus,
        desktop_available: true,
        browser_session_detected: config.isSignedIn(sessionCookies),
      }
    } catch (error) {
      return {
        configured: false,
        state: 'unknown',
        label: `${config.label}登录态待确认`,
        detail: `无法连接本地服务验证登录态：${error.message}`,
        desktop_available: true,
        browser_session_detected: config.isSignedIn(sessionCookies),
      }
    }
  }

  async function persistSession(platform) {
    const config = configFor(platform)
    const cookies = await platformCookies(platform)
    if (!config.isSignedIn(cookies)) return null
    // Credentials stay inside Electron's isolated session and this local IPC
    // bridge. They are never returned to the renderer or written to its logs.
    const cookieHeader = cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join('; ')
    await requestJson(backendUrl, config.apiPath, {
      method: 'POST',
      body: { cookie: cookieHeader },
    })
    return status(platform, { refresh: true })
  }

  function openLoginWindow(platform, parentWindow) {
    const config = configFor(platform)
    const existing = loginWindows.get(platform)
    if (existing && !existing.isDestroyed()) {
      existing.show()
      existing.focus()
      return existing
    }
    const loginWindow = new BrowserWindow({
      width: 1040,
      height: 760,
      minWidth: 820,
      minHeight: 620,
      title: `连接${config.label}`,
      parent: parentWindow || undefined,
      modal: false,
      backgroundColor: '#f7f8f5',
      webPreferences: {
        partition: config.partition,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    })
    loginWindows.set(platform, loginWindow)
    let completing = false
    const persistIfSignedIn = async () => {
      if (completing || loginWindow.isDestroyed()) return false
      const saved = await persistSession(platform).catch(() => null)
      if (!saved) return false
      completing = true
      setTimeout(() => {
        if (!loginWindow.isDestroyed()) loginWindow.close()
      }, 350)
      return true
    }
    const activeSession = platformSession(platform)
    const cookieListener = () => { void persistIfSignedIn() }
    activeSession.cookies.on('changed', cookieListener)

    loginWindow.webContents.on('did-finish-load', () => { void persistIfSignedIn() })
    loginWindow.webContents.on('will-navigate', (event, value) => {
      if (!isAllowedUrl(platform, value)) event.preventDefault()
    })
    loginWindow.webContents.on('will-redirect', (event, value) => {
      if (!isAllowedUrl(platform, value)) event.preventDefault()
    })
    loginWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (isAllowedUrl(platform, url)) loginWindow.loadURL(url).catch(() => {})
      return { action: 'deny' }
    })
    loginWindow.on('closed', () => {
      activeSession.cookies.removeListener('changed', cookieListener)
      if (loginWindows.get(platform) === loginWindow) loginWindows.delete(platform)
    })
    loginWindow.loadURL(config.loginUrl).catch(() => {})
    return loginWindow
  }

  async function connect(platform, parentWindow) {
    const window = openLoginWindow(platform, parentWindow)
    return new Promise((resolve) => {
      window.once('closed', async () => resolve(await status(platform, { refresh: true })))
    })
  }

  async function disconnect(platform) {
    const config = configFor(platform)
    const window = loginWindows.get(platform)
    if (window && !window.isDestroyed()) window.close()
    await platformSession(platform).clearStorageData()
    await requestJson(backendUrl, config.apiPath, { method: 'DELETE' })
    return status(platform, { refresh: true })
  }

  return { connect, disconnect, status }
}

function requestJson(baseUrl, path, { method = 'GET', body = null } = {}) {
  const target = new URL(path, baseUrl)
  const payload = body === null ? '' : JSON.stringify(body)
  return new Promise((resolve, reject) => {
    const request = http.request(target, {
      method,
      headers: payload ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {},
      timeout: 15000,
    }, (response) => {
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8')
        let data = {}
        try { data = text ? JSON.parse(text) : {} } catch { data = {} }
        if (response.statusCode >= 200 && response.statusCode < 300) return resolve(data)
        reject(new Error(data.detail || data.message || `本地服务返回 HTTP ${response.statusCode}`))
      })
    })
    request.on('timeout', () => request.destroy(new Error('本地服务响应超时')))
    request.on('error', reject)
    if (payload) request.write(payload)
    request.end()
  })
}

module.exports = { PLATFORM_CONFIG, createPlatformAuthController }
