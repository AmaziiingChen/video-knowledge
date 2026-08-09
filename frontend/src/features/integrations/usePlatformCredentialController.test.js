import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { usePlatformCredentialController } from './usePlatformCredentialController.js'

function createController({ request = {}, desktop = {}, confirmDisconnect = async () => true } = {}) {
  const messages = []
  const requests = []
  const cookieConfigured = ref(false)
  const cookieState = ref('unknown')
  const showSettings = ref(true)
  const refreshes = []
  const controller = usePlatformCredentialController({
    showSettings,
    cookieConfigured,
    cookieState,
    loadCookieStatus: async (force) => refreshes.push(['douyin', force]),
    loadBilibiliCookieStatus: async (force) => refreshes.push(['bilibili', force]),
    notify: Object.fromEntries(['warning', 'info', 'success', 'error'].map((level) => [level, (message) => messages.push([level, message])])),
    confirmDisconnect,
    request: {
      post: async (...args) => {
        requests.push(args)
        return { data: { success: true } }
      },
      ...request,
    },
    apiBase: 'http://api.test',
    desktopBridge: () => desktop,
  })
  return { controller, cookieConfigured, cookieState, showSettings, messages, refreshes, requests }
}

test('saves manual credentials without retaining the Bilibili secret', async () => {
  const { controller, cookieState, showSettings, messages, refreshes, requests } = createController()
  controller.cookieInput.value = '  douyin-cookie  '
  cookieState.value = 'valid'
  assert.equal(await controller.saveCookie(), true)
  assert.deepEqual(requests, [['http://api.test/cookie', { cookie: 'douyin-cookie' }]])
  assert.deepEqual(refreshes, [['douyin', true]])
  assert.equal(showSettings.value, false)
  assert.deepEqual(messages, [['success', 'Cookie 已保存并验证可用']])

  controller.bilibiliCookieInput.value = ' b-cookie '
  assert.equal(await controller.saveBilibiliCookie(), true)
  assert.equal(controller.bilibiliCookieInput.value, '')
  assert.deepEqual(requests.at(-1), ['http://api.test/bilibili-cookie', { cookie: 'b-cookie' }, { timeout: 10000 }])
  assert.deepEqual(refreshes.at(-1), ['bilibili', undefined])
})

test('connects through the desktop bridge and refreshes only its platform status', async () => {
  const calls = []
  const { controller, refreshes, messages } = createController({
    desktop: { connectPlatformAuth: async (platform) => {
      calls.push(platform)
      return { state: 'valid' }
    } },
  })

  assert.equal(await controller.connectPlatformAuth('bilibili'), true)
  assert.deepEqual(calls, ['bilibili'])
  assert.deepEqual(refreshes, [['bilibili', true]])
  assert.deepEqual(messages, [['success', 'B站登录态已连接并验证可用']])
  assert.equal(controller.platformAuthConnecting.value, '')
})

test('does not disconnect without confirmation and refreshes after a confirmed disconnect', async () => {
  const calls = []
  const blocked = createController({
    desktop: { disconnectPlatformAuth: async (platform) => calls.push(platform) },
    confirmDisconnect: async () => false,
  })
  await blocked.controller.disconnectPlatformAuth('douyin')
  assert.deepEqual(calls, [])

  const allowed = createController({
    desktop: { disconnectPlatformAuth: async (platform) => calls.push(platform) },
  })
  await allowed.controller.disconnectPlatformAuth('douyin')
  assert.deepEqual(calls, ['douyin'])
  assert.deepEqual(allowed.refreshes, [['douyin', true]])
  assert.deepEqual(allowed.messages, [['success', '抖音登录态已断开']])
})
