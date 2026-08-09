import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatAccountController } from './useWechatAccountController.js'

function createController({ request = {}, accounts = [], settingsOpen = true } = {}) {
  const notices = []
  const timers = []
  const cancelled = []
  let refreshCount = 0
  const controller = useWechatAccountController({
    accounts: ref(accounts),
    settingsOpen: ref(settingsOpen),
    refreshSubscriptions: async () => { refreshCount += 1 },
    request: {
      get: async () => ({ data: [] }),
      post: async () => ({ data: {} }),
      delete: async () => {},
      ...request,
    },
    notify: {
      success: (message) => notices.push(['success', message]),
      warning: (message) => notices.push(['warning', message]),
      error: (message) => notices.push(['error', message]),
      info: (message) => notices.push(['info', message]),
    },
    schedule: (callback, delay) => {
      const token = { callback, delay }
      timers.push(token)
      return token
    },
    cancelSchedule: (token) => cancelled.push(token),
  })
  return { controller, notices, timers, cancelled, refreshCount: () => refreshCount }
}

test('manual account connection trims credentials, clears them, and refreshes subscriptions', async () => {
  const requests = []
  const { controller, refreshCount } = createController({
    request: { post: async (...args) => { requests.push(args); return { data: { id: 'account-1' } } } },
  })
  controller.wechatManualToken.value = '  token  '
  controller.wechatManualCookie.value = '  cookie  '

  assert.equal(await controller.connectWeChatManually(), true)
  assert.deepEqual(requests[0], [
    'http://127.0.0.1:8000/api/wechat-subscriptions/accounts',
    { display_name: '微信公众平台账号', token: 'token', cookie: 'cookie' },
    { timeout: 30000 },
  ])
  assert.equal(controller.selectedWeChatAccountId.value, 'account-1')
  assert.equal(controller.wechatManualToken.value, '')
  assert.equal(controller.wechatManualCookie.value, '')
  assert.equal(refreshCount(), 1)
})

test('QR confirmation refreshes once and releases its completed timer', async () => {
  const calls = []
  const { controller, timers, cancelled, refreshCount } = createController({
    request: {
      post: async (url) => {
        calls.push(url)
        return calls.length === 1
          ? { data: { login_id: 'login-1', status: 'waiting' } }
          : { data: { status: 'confirmed' } }
      },
    },
  })

  await controller.startWeChatQrLogin()
  assert.equal(timers.length, 1)
  await timers[0].callback()
  assert.equal(refreshCount(), 1)
  assert.equal(controller.wechatQrLogin.value.login_id, '')
  controller.disposeWechatAccountController()
  assert.equal(cancelled.length, 0)
})

test('expired QR authorizations stop polling and retain the recovery message', async () => {
  const { controller, notices, timers, cancelled } = createController({
    request: {
      post: async (_url) => ({ data: timers.length === 0
        ? { login_id: 'login-1', status: 'waiting' }
        : { status: 'expired', message: '二维码已过期' } }),
    },
  })

  await controller.startWeChatQrLogin()
  await timers[0].callback()

  assert.deepEqual(notices, [['warning', '二维码已过期']])
  assert.equal(cancelled.length, 0)
})

test('account selection is reconciled and searching uses the selected account only', async () => {
  const requests = []
  const { controller } = createController({
    accounts: [{ id: 'account-1' }, { id: 'account-2' }],
    request: {
      get: async (...args) => {
        requests.push(args)
        return { data: [{ fakeid: 'fake-1', name: '公众号' }] }
      },
    },
  })
  controller.reconcileSelectedAccount()
  controller.wechatSearchQuery.value = '  关键词 '

  assert.deepEqual(await controller.searchWeChatAccounts(), [{ fakeid: 'fake-1', name: '公众号' }])
  assert.deepEqual(requests[0], [
    'http://127.0.0.1:8000/api/wechat-subscriptions/accounts/account-1/search',
    { params: { q: '关键词', limit: 10 }, timeout: 30000 },
  ])
})

test('transferring to the same account is rejected before a network request', async () => {
  let posted = false
  const { controller, notices } = createController({
    request: { post: async () => { posted = true; return { data: {} } } },
  })
  controller.selectedWeChatAccountId.value = 'account-1'

  assert.equal(await controller.transferWeChatAccountSubscriptions('account-1'), false)
  assert.equal(posted, false)
  assert.deepEqual(notices, [['warning', '请先在授权账号列表中选中接管订阅的新账号']])
})
