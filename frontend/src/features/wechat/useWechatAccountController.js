import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const EMPTY_QR_LOGIN = Object.freeze({ login_id: '', status: '', message: '', qr_image_data_url: '' })

export function useWechatAccountController({
  accounts,
  refreshSubscriptions,
  settingsOpen,
  apiBase = `${API}/wechat-subscriptions`,
  request = axios,
  notify = ElMessage,
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const selectedWeChatAccountId = ref('')
  const wechatAccountDisplayName = ref('微信公众平台账号')
  const wechatQrLogin = ref({ ...EMPTY_QR_LOGIN })
  const wechatQrStarting = ref(false)
  const wechatManualToken = ref('')
  const wechatManualCookie = ref('')
  const wechatManualConnecting = ref(false)
  const wechatSearchQuery = ref('')
  const wechatSearchResults = ref([])
  const wechatSearching = ref(false)
  let qrPollTimer = null

  function reconcileSelectedAccount() {
    if (!accounts?.value?.some((account) => account.id === selectedWeChatAccountId.value)) {
      selectedWeChatAccountId.value = accounts?.value?.[0]?.id || ''
    }
  }

  function stopWeChatQrPolling() {
    if (qrPollTimer) cancelSchedule(qrPollTimer)
    qrPollTimer = null
  }

  function scheduleWeChatQrPoll() {
    stopWeChatQrPolling()
    if (!wechatQrLogin.value.login_id || !settingsOpen?.value) return
    qrPollTimer = schedule(() => {
      qrPollTimer = null
      void pollWeChatQrLogin()
    }, 1800)
  }

  async function startWeChatQrLogin(reauthorizeAccountId = '') {
    stopWeChatQrPolling()
    wechatQrStarting.value = true
    const account = accounts?.value?.find((item) => item.id === reauthorizeAccountId)
    try {
      const response = await request.post(`${apiBase}/accounts/qr-login`, {
        display_name: account?.display_name || wechatAccountDisplayName.value.trim() || '微信公众平台账号',
        reauthorize_account_id: reauthorizeAccountId || null,
      }, { timeout: 30000 })
      wechatQrLogin.value = response.data || { ...EMPTY_QR_LOGIN }
      scheduleWeChatQrPoll()
    } catch (error) {
      notify.error(errorMessage(error, '未能获取微信公众平台二维码'))
    } finally {
      wechatQrStarting.value = false
    }
  }

  async function pollWeChatQrLogin() {
    const loginId = wechatQrLogin.value.login_id
    if (!loginId || !settingsOpen?.value) return
    try {
      const response = await request.post(`${apiBase}/accounts/qr-login/${encodeURIComponent(loginId)}/poll`, {
        display_name: wechatAccountDisplayName.value.trim() || '微信公众平台账号',
        reauthorize_account_id: wechatQrLogin.value.reauthorize_account_id || null,
      }, { timeout: 30000 })
      wechatQrLogin.value = response.data || { ...EMPTY_QR_LOGIN }
      if (response.data?.status === 'confirmed') {
        notify.success(response.data?.reauthorize_account_id ? '微信公众平台已重新授权，订阅保持不变' : '微信公众平台授权成功')
        wechatQrLogin.value = { ...EMPTY_QR_LOGIN }
        await refreshSubscriptions?.()
        return
      }
      if (['expired', 'failed'].includes(response.data?.status)) {
        stopWeChatQrPolling()
        notify.warning(response.data?.message || '二维码已失效，请重新点击扫码连接')
        return
      }
      scheduleWeChatQrPoll()
    } catch (error) {
      stopWeChatQrPolling()
      notify.error(errorMessage(error, '微信扫码授权失败'))
    }
  }

  async function connectWeChatManually() {
    if (!wechatManualToken.value.trim() || !wechatManualCookie.value.trim()) {
      notify.warning('请输入 token 和 Cookie')
      return false
    }
    wechatManualConnecting.value = true
    try {
      const response = await request.post(`${apiBase}/accounts`, {
        display_name: wechatAccountDisplayName.value.trim() || '微信公众平台账号',
        token: wechatManualToken.value.trim(),
        cookie: wechatManualCookie.value.trim(),
      }, { timeout: 30000 })
      selectedWeChatAccountId.value = response.data?.id || ''
      wechatManualToken.value = ''
      wechatManualCookie.value = ''
      notify.success('微信公众平台账号已连接')
      await refreshSubscriptions?.()
      return true
    } catch (error) {
      notify.error(errorMessage(error, '微信公众平台登录态不可用'))
      return false
    } finally {
      wechatManualConnecting.value = false
    }
  }

  async function deleteWeChatAccount(accountId) {
    try {
      await request.delete(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, { timeout: 10000 })
      notify.success('授权账号已移除')
      await refreshSubscriptions?.()
      return true
    } catch (error) {
      notify.error(errorMessage(error, '移除授权账号失败'))
      return false
    }
  }

  async function transferWeChatAccountSubscriptions(sourceAccountId) {
    const targetAccountId = String(selectedWeChatAccountId.value || '')
    if (!targetAccountId || targetAccountId === String(sourceAccountId)) {
      notify.warning('请先在授权账号列表中选中接管订阅的新账号')
      return false
    }
    try {
      const response = await request.post(
        `${apiBase}/accounts/${encodeURIComponent(sourceAccountId)}/transfer-subscriptions`,
        { target_account_id: targetAccountId },
        { timeout: 10000 },
      )
      notify.success(`已迁移 ${response.data?.moved_count || 0} 个公众号订阅`)
      await refreshSubscriptions?.()
      return true
    } catch (error) {
      notify.error(errorMessage(error, '迁移公众号订阅失败'))
      return false
    }
  }

  async function searchWeChatAccounts() {
    if (!selectedWeChatAccountId.value || !wechatSearchQuery.value.trim()) return []
    wechatSearching.value = true
    wechatSearchResults.value = []
    try {
      const response = await request.get(
        `${apiBase}/accounts/${encodeURIComponent(selectedWeChatAccountId.value)}/search`,
        { params: { q: wechatSearchQuery.value.trim(), limit: 10 }, timeout: 30000 },
      )
      wechatSearchResults.value = Array.isArray(response.data) ? response.data : []
      if (!wechatSearchResults.value.length) notify.info?.('没有找到匹配的公众号')
      return wechatSearchResults.value
    } catch (error) {
      notify.error(errorMessage(error, '搜索公众号失败'))
      return []
    } finally {
      wechatSearching.value = false
    }
  }

  function clearWeChatSearchResults() {
    wechatSearchResults.value = []
  }

  function disposeWechatAccountController() {
    stopWeChatQrPolling()
  }

  return {
    selectedWeChatAccountId,
    wechatAccountDisplayName,
    wechatQrLogin,
    wechatQrStarting,
    wechatManualToken,
    wechatManualCookie,
    wechatManualConnecting,
    wechatSearchQuery,
    wechatSearchResults,
    wechatSearching,
    reconcileSelectedAccount,
    startWeChatQrLogin,
    scheduleWeChatQrPoll,
    stopWeChatQrPolling,
    connectWeChatManually,
    deleteWeChatAccount,
    transferWeChatAccountSubscriptions,
    searchWeChatAccounts,
    clearWeChatSearchResults,
    disposeWechatAccountController,
  }
}
