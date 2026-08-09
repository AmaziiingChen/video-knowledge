import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function usePlatformCredentialController({
  showSettings,
  cookieConfigured,
  cookieState,
  loadCookieStatus,
  loadBilibiliCookieStatus,
  notify,
  confirmDisconnect,
  request = axios,
  apiBase = API,
  desktopBridge = () => window.knowledgeHubDesktop,
}) {
  const cookieInput = ref('')
  const savingCookie = ref(false)
  const bilibiliCookieInput = ref('')
  const savingBilibiliCookie = ref(false)
  const platformAuthConnecting = ref('')
  const platformAuthAvailable = Boolean(desktopBridge()?.connectPlatformAuth)

  async function saveCookie({ closeAfterSave = true, notify: notifyResult = true } = {}) {
    if (!cookieInput.value.trim()) {
      if (cookieConfigured.value) {
        showSettings.value = false
        return
      }
      notify.warning('请粘贴 Cookie')
      return
    }
    savingCookie.value = true
    try {
      const response = await request.post(`${apiBase}/cookie`, { cookie: cookieInput.value.trim() })
      if (!response.data.success) {
        notify.error(response.data.message)
        return false
      }
      await loadCookieStatus(true)
      if (closeAfterSave) showSettings.value = false
      if (notifyResult) {
        notify.success(cookieState.value === 'valid' ? 'Cookie 已保存并验证可用' : 'Cookie 已保存，正在等待抖音验证')
      }
      return true
    } catch {
      notify.error('保存失败')
      return false
    } finally {
      savingCookie.value = false
    }
  }

  async function saveBilibiliCookie({ notify: notifyResult = true } = {}) {
    if (!bilibiliCookieInput.value.trim()) return true
    savingBilibiliCookie.value = true
    try {
      const response = await request.post(
        `${apiBase}/bilibili-cookie`,
        { cookie: bilibiliCookieInput.value.trim() },
        { timeout: 10000 },
      )
      if (!response.data.success) {
        notify.error(response.data.message)
        return false
      }
      bilibiliCookieInput.value = ''
      await loadBilibiliCookieStatus()
      if (notifyResult) notify.success('B站 Cookie 已保存')
      return true
    } catch (error) {
      notify.error(error.response?.data?.detail || error.message || 'B站 Cookie 保存失败')
      return false
    } finally {
      savingBilibiliCookie.value = false
    }
  }

  async function refreshPlatformStatus(platform) {
    if (platform === 'bilibili') await loadBilibiliCookieStatus(true)
    else await loadCookieStatus(true)
  }

  function platformLabel(platform) {
    return platform === 'bilibili' ? 'B站' : '抖音'
  }

  async function connectPlatformAuth(platform) {
    const connect = desktopBridge()?.connectPlatformAuth
    if (!connect) {
      notify.warning('请使用桌面版在应用内登录；浏览器版仍可手动粘贴 Cookie。')
      return false
    }
    platformAuthConnecting.value = platform
    try {
      const status = await connect(platform)
      await refreshPlatformStatus(platform)
      const label = platformLabel(platform)
      if (status?.state === 'valid') {
        notify.success(`${label}登录态已连接并验证可用`)
        return true
      }
      if (status?.configured) {
        notify.info(`${label}登录态已保存，正在等待平台验证`)
        return true
      }
      notify.info('登录窗口已关闭；尚未检测到可用登录态。')
      return false
    } catch (error) {
      notify.error(error?.message || '登录状态保存失败')
      return false
    } finally {
      platformAuthConnecting.value = ''
    }
  }

  async function disconnectPlatformAuth(platform) {
    const disconnect = desktopBridge()?.disconnectPlatformAuth
    if (!disconnect) return
    const label = platformLabel(platform)
    const confirmed = await confirmDisconnect({
      title: `断开${label}登录态`,
      message: `这会清除本应用保存的${label}登录会话和下载凭据；之后需要重新登录才能使用受限功能。`,
      confirmLabel: '断开登录态',
    })
    if (!confirmed) return
    platformAuthConnecting.value = platform
    try {
      await disconnect(platform)
      await refreshPlatformStatus(platform)
      notify.success(`${label}登录态已断开`)
    } catch (error) {
      notify.error(error?.message || '断开登录态失败')
    } finally {
      platformAuthConnecting.value = ''
    }
  }

  return {
    cookieInput,
    savingCookie,
    bilibiliCookieInput,
    savingBilibiliCookie,
    platformAuthConnecting,
    platformAuthAvailable,
    saveCookie,
    saveBilibiliCookie,
    connectPlatformAuth,
    disconnectPlatformAuth,
  }
}
