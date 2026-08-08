const test = require('node:test')
const assert = require('node:assert/strict')

const { PLATFORM_CONFIG, isVerifiedPlatformSession } = require('./platform-auth.cjs')

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
