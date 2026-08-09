import { describe, expect, it } from 'vitest'
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

describe('usePlatformCredentialController', () => {
  it('saves manual credentials without retaining the Bilibili secret', async () => {
    const { controller, cookieState, showSettings, messages, refreshes, requests } = createController()
    controller.cookieInput.value = '  douyin-cookie  '
    cookieState.value = 'valid'
    await expect(controller.saveCookie()).resolves.toBe(true)
    expect(requests).toEqual([['http://api.test/cookie', { cookie: 'douyin-cookie' }]])
    expect(refreshes).toEqual([['douyin', true]])
    expect(showSettings.value).toBe(false)
    expect(messages).toEqual([['success', 'Cookie 已保存并验证可用']])

    controller.bilibiliCookieInput.value = ' b-cookie '
    await expect(controller.saveBilibiliCookie()).resolves.toBe(true)
    expect(controller.bilibiliCookieInput.value).toBe('')
    expect(requests.at(-1)).toEqual(['http://api.test/bilibili-cookie', { cookie: 'b-cookie' }, { timeout: 10000 }])
    expect(refreshes.at(-1)).toEqual(['bilibili', undefined])
  })

  it('keeps empty input semantics and exposes both manual-save failures', async () => {
    const empty = createController()
    await expect(empty.controller.saveCookie()).resolves.toBeUndefined()
    expect(empty.messages).toEqual([['warning', '请粘贴 Cookie']])
    empty.cookieConfigured.value = true
    await expect(empty.controller.saveCookie()).resolves.toBeUndefined()
    expect(empty.showSettings.value).toBe(false)
    await expect(empty.controller.saveBilibiliCookie()).resolves.toBe(true)

    const rejected = createController({ request: { post: async () => ({ data: { success: false, message: '拒绝保存' } }) } })
    rejected.controller.cookieInput.value = 'cookie'
    await expect(rejected.controller.saveCookie()).resolves.toBe(false)
    rejected.controller.bilibiliCookieInput.value = 'cookie'
    await expect(rejected.controller.saveBilibiliCookie()).resolves.toBe(false)
    expect(rejected.messages).toEqual([['error', '拒绝保存'], ['error', '拒绝保存']])
  })

  it('connects through the desktop bridge and handles unavailable or provisional status', async () => {
    const unavailable = createController()
    await expect(unavailable.controller.connectPlatformAuth('douyin')).resolves.toBe(false)
    expect(unavailable.messages).toEqual([['warning', '请使用桌面版在应用内登录；浏览器版仍可手动粘贴 Cookie。']])

    const calls = []
    const { controller, refreshes, messages } = createController({
      desktop: { connectPlatformAuth: async (platform) => {
        calls.push(platform)
        return { configured: true }
      } },
    })
    await expect(controller.connectPlatformAuth('bilibili')).resolves.toBe(true)
    expect(calls).toEqual(['bilibili'])
    expect(refreshes).toEqual([['bilibili', true]])
    expect(messages).toEqual([['info', 'B站登录态已保存，正在等待平台验证']])
    expect(controller.platformAuthConnecting.value).toBe('')
  })

  it('does not disconnect without confirmation and reports a bridge failure', async () => {
    const calls = []
    const blocked = createController({
      desktop: { disconnectPlatformAuth: async (platform) => calls.push(platform) },
      confirmDisconnect: async () => false,
    })
    await expect(blocked.controller.disconnectPlatformAuth('douyin')).resolves.toBeUndefined()
    expect(calls).toEqual([])

    const failed = createController({
      desktop: { disconnectPlatformAuth: async () => { throw new Error('无法断开') } },
    })
    await failed.controller.disconnectPlatformAuth('douyin')
    expect(failed.messages).toEqual([['error', '无法断开']])
    expect(failed.controller.platformAuthConnecting.value).toBe('')
  })
})
