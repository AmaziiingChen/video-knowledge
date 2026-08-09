import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useCookieStatusController({
  notify,
  request = axios,
  apiBase = API,
  scheduleTimeout = (callback, delay) => window.setTimeout(callback, delay),
  cancelTimeout = (timer) => window.clearTimeout(timer),
  scheduleInterval = (callback, delay) => window.setInterval(callback, delay),
  cancelInterval = (timer) => window.clearInterval(timer),
  requestIdle = (callback, options) => typeof window.requestIdleCallback === 'function'
    ? window.requestIdleCallback(callback, options)
    : null,
  cancelIdle = (handle) => typeof window.cancelIdleCallback === 'function'
    ? window.cancelIdleCallback(handle)
    : window.clearTimeout(handle),
}) {
  const cookieConfigured = ref(false)
  const cookieState = ref('unknown')
  const cookieStatusText = ref('抖音凭据待检测')
  const cookieStatusDetail = ref('正在读取抖音下载凭据状态')
  const cookieChecking = ref(false)
  const bilibiliCookieConfigured = ref(false)
  const bilibiliCookieState = ref('loading')
  const bilibiliCookieStatusText = ref('正在读取 B站登录态')
  let cookieTimer = null
  let bilibiliCookieTimer = null
  let deferredCookieProbeHandle = null
  let deferredCookieProbeUsesIdleCallback = false
  let lastDouyinCookieAlertState = ''

  function applyCookieStatus(data = {}) {
    const previousState = cookieState.value
    cookieConfigured.value = Boolean(data.configured)
    cookieState.value = data.state || (data.configured ? 'unknown' : 'missing')
    cookieStatusText.value = data.label || (data.configured ? '抖音凭据待确认' : '抖音凭据未配置')
    cookieStatusDetail.value = data.detail || '暂无检测详情'
    const needsLogin = ['missing', 'invalid', 'blocked'].includes(cookieState.value)
    if (needsLogin && cookieState.value !== previousState && lastDouyinCookieAlertState !== cookieState.value) {
      lastDouyinCookieAlertState = cookieState.value
      notify.warning({
        title: '抖音登录态需要处理',
        message: `${cookieStatusText.value}：请在设置 > 平台凭据中点击“登录并连接”。`,
        duration: 0,
      })
    }
    if (!needsLogin) lastDouyinCookieAlertState = ''
  }

  async function loadCookieStatus(force = false, { probe = true } = {}) {
    if (cookieChecking.value) return
    cookieChecking.value = true
    try {
      const params = {}
      if (force) params.refresh = true
      if (!probe) params.probe = false
      const res = await request.get(`${apiBase}/cookie`, {
        params: Object.keys(params).length ? params : undefined,
        timeout: 30000,
      })
      applyCookieStatus(res.data)
    } catch (error) {
      cookieState.value = 'unknown'
      cookieStatusText.value = '抖音凭据待确认'
      cookieStatusDetail.value = error.response?.data?.detail || error.message || '状态检测不可用'
    } finally {
      cookieChecking.value = false
    }
  }

  async function loadBilibiliCookieStatus(force = false) {
    bilibiliCookieState.value = 'loading'
    try {
      const res = await request.get(`${apiBase}/creator-sources/health`, {
        params: force ? { refresh: true, probe_douyin: false } : { probe_douyin: false },
        timeout: 15000,
      })
      const status = res.data?.cookies?.bilibili || {}
      bilibiliCookieConfigured.value = Boolean(status.configured)
      bilibiliCookieState.value = status.state || (status.configured ? 'unknown' : 'missing')
      bilibiliCookieStatusText.value = status.detail || status.label || (status.configured ? 'B站登录态已配置' : 'B站登录态未配置')
    } catch (error) {
      bilibiliCookieConfigured.value = false
      bilibiliCookieState.value = 'unknown'
      bilibiliCookieStatusText.value = error.response?.data?.detail || error.message || 'B站登录态状态读取失败'
    }
  }

  function scheduleDeferredCookieProbe() {
    if (deferredCookieProbeHandle !== null) return
    const runProbe = () => {
      deferredCookieProbeHandle = null
      deferredCookieProbeUsesIdleCallback = false
      void loadCookieStatus(true)
    }
    const idleHandle = requestIdle(runProbe, { timeout: 5000 })
    if (idleHandle !== null && idleHandle !== undefined) {
      deferredCookieProbeUsesIdleCallback = true
      deferredCookieProbeHandle = idleHandle
      return
    }
    deferredCookieProbeHandle = scheduleTimeout(runProbe, 1500)
  }

  function cancelDeferredCookieProbe() {
    if (deferredCookieProbeHandle === null) return
    if (deferredCookieProbeUsesIdleCallback) cancelIdle(deferredCookieProbeHandle)
    else cancelTimeout(deferredCookieProbeHandle)
    deferredCookieProbeHandle = null
    deferredCookieProbeUsesIdleCallback = false
  }

  function startCookieStatusPolling() {
    if (cookieTimer) return
    cookieTimer = scheduleInterval(() => loadCookieStatus(), 60000)
    bilibiliCookieTimer = scheduleInterval(() => loadBilibiliCookieStatus(true), 300000)
  }

  function stopCookieStatusPolling() {
    if (cookieTimer) {
      cancelInterval(cookieTimer)
      cookieTimer = null
    }
    if (bilibiliCookieTimer) {
      cancelInterval(bilibiliCookieTimer)
      bilibiliCookieTimer = null
    }
  }

  return {
    cookieConfigured,
    cookieState,
    cookieStatusText,
    cookieStatusDetail,
    cookieChecking,
    bilibiliCookieConfigured,
    bilibiliCookieState,
    bilibiliCookieStatusText,
    loadCookieStatus,
    loadBilibiliCookieStatus,
    scheduleDeferredCookieProbe,
    cancelDeferredCookieProbe,
    startCookieStatusPolling,
    stopCookieStatusPolling,
  }
}
