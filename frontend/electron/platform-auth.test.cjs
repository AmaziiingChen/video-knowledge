const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')

const {
  PLATFORM_CONFIG,
  createPlatformAuthController,
  isVerifiedPlatformSession,
  requestJson,
} = require('./platform-auth.cjs')

test('小红书登录桥只接受本站会话，并以 web_session 判断已登录', () => {
  const config = PLATFORM_CONFIG.xiaohongshu

  assert.equal(config.apiPath, '/api/xiaohongshu-cookie')
  assert.equal(config.statusPath, '/api/xiaohongshu-cookie')
  assert.equal(config.allowedHost('www.xiaohongshu.com'), true)
  assert.equal(config.allowedHost('example.com'), false)
  assert.equal(config.isSignedIn([{ name: 'a1', value: 'visitor' }]), false)
  assert.equal(config.isSignedIn([{ name: 'web_session', value: 'session' }]), true)
})

test('平台登录窗口只在后台确认会话有效后才视为完成', () => {
  assert.equal(isVerifiedPlatformSession({ configured: true, state: 'invalid' }), false)
  assert.equal(isVerifiedPlatformSession({ configured: true, state: 'unknown' }), false)
  assert.equal(isVerifiedPlatformSession({ configured: true, state: 'valid' }), true)
})

test('平台登录后端的 GET、POST 和 DELETE 请求都携带桌面实例令牌', async () => {
  const requests = []
  const requestImpl = (target, options, onResponse) => {
    const request = new EventEmitter()
    const chunks = []
    request.write = (chunk) => chunks.push(Buffer.from(chunk))
    request.destroy = (error) => request.emit('error', error)
    request.end = () => {
      requests.push({
        method: options.method,
        path: target.pathname,
        token: options.headers['X-KnowledgeHub-Token'],
        body: Buffer.concat(chunks).toString('utf8'),
      })
      const response = new EventEmitter()
      response.statusCode = 200
      onResponse(response)
      response.emit('data', Buffer.from('{}'))
      response.emit('end')
    }
    return request
  }
  const baseUrl = 'http://127.0.0.1:8000'

  await requestJson(baseUrl, '/api/status', { token: 'desktop-token', requestImpl })
  await requestJson(baseUrl, '/api/credential', {
    method: 'POST',
    body: { cookie: 'private-cookie' },
    token: 'desktop-token',
    requestImpl,
  })
  await requestJson(baseUrl, '/api/credential', { method: 'DELETE', token: 'desktop-token', requestImpl })

  assert.deepEqual(requests, [
    { method: 'GET', path: '/api/status', token: 'desktop-token', body: '' },
    { method: 'POST', path: '/api/credential', token: 'desktop-token', body: '{"cookie":"private-cookie"}' },
    { method: 'DELETE', path: '/api/credential', token: 'desktop-token', body: '' },
  ])
})

test('登录窗口对并发 Cookie 事件单飞保存，仅在验证有效后关闭并清理监听', async () => {
  const cookies = new EventEmitter()
  cookies.get = async () => [
    { domain: '.douyin.com', name: 'sessionid', value: 'signed-in' },
    { domain: '.douyin.com', name: 'csrf_session_id', value: 'csrf' },
  ]
  const platformSession = {
    cookies,
    setPermissionRequestHandler() {},
    async clearStorageData() {},
  }
  const session = { fromPartition: () => platformSession }

  class FakeBrowserWindow extends EventEmitter {
    static instances = []

    constructor(options) {
      super()
      this.options = options
      this.destroyed = false
      this.webContents = new EventEmitter()
      this.webContents.setWindowOpenHandler = () => {}
      FakeBrowserWindow.instances.push(this)
    }

    isDestroyed() { return this.destroyed }
    loadURL() { return Promise.resolve() }
    show() {}
    focus() {}
    close() {
      if (this.destroyed) return
      this.destroyed = true
      this.emit('closed')
    }
  }

  let resolveFirstPost
  let postCount = 0
  let backendState = 'invalid'
  const request = async (_baseUrl, _path, options = {}) => {
    assert.equal(options.token, 'desktop-token')
    if (options.method === 'POST') {
      postCount += 1
      if (postCount === 1) await new Promise((resolve) => { resolveFirstPost = resolve })
      return { success: true }
    }
    return { configured: true, state: backendState }
  }
  const controller = createPlatformAuthController({
    BrowserWindow: FakeBrowserWindow,
    session,
    backendUrl: 'http://127.0.0.1:8000',
    backendToken: 'desktop-token',
    request,
    scheduleClose: (callback) => callback(),
  })

  const connection = controller.connect('douyin')
  const loginWindow = FakeBrowserWindow.instances[0]
  loginWindow.webContents.emit('did-finish-load')
  cookies.emit('changed')
  cookies.emit('changed')
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(postCount, 1)
  assert.equal(loginWindow.isDestroyed(), false)

  resolveFirstPost()
  await new Promise((resolve) => setImmediate(resolve))
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(loginWindow.isDestroyed(), false)
  assert.equal(cookies.listenerCount('changed'), 1)

  backendState = 'valid'
  cookies.emit('changed')
  const finalStatus = await connection
  assert.equal(postCount, 1)
  assert.equal(loginWindow.isDestroyed(), true)
  assert.equal(cookies.listenerCount('changed'), 0)
  assert.equal(finalStatus.state, 'valid')
})
