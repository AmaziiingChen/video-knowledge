import { ref } from 'vue'
import axios from 'axios'

import { API_BASE } from '../../utils/localApiAuth.js'
import { assertTelemetryEnabledState } from './telemetryNoticeState.js'

export function useTelemetrySettingsController({
  httpClient = axios,
  endpoint = `${API_BASE}/telemetry`,
  notifySuccess = () => {},
  notifyError = () => {},
} = {}) {
  const telemetryEnabled = ref(false)
  const confirmedEnabled = ref(false)
  const telemetryPendingEvents = ref(0)
  const telemetrySaving = ref(false)
  const telemetryStatusLoading = ref(false)
  const telemetryStatusLoaded = ref(false)
  const telemetryStatusError = ref('')
  const noticeVersion = ref('')

  async function loadTelemetryStatus() {
    telemetryStatusLoading.value = true
    telemetryStatusLoaded.value = false
    telemetryStatusError.value = ''
    try {
      const response = await httpClient.get(endpoint, { timeout: 5000 })
      if (typeof response.data?.enabled !== 'boolean') throw new Error('invalid telemetry status')
      telemetryEnabled.value = response.data.enabled
      confirmedEnabled.value = response.data.enabled
      telemetryPendingEvents.value = Number(response.data?.pending_events || 0)
      noticeVersion.value = String(response.data?.privacy_notice_version || '')
      telemetryStatusLoaded.value = true
    } catch {
      telemetryStatusError.value = '无法读取当前诊断状态。'
    } finally {
      telemetryStatusLoading.value = false
    }
  }

  async function saveTelemetry(enabled) {
    if (!telemetryStatusLoaded.value || telemetrySaving.value) {
      telemetryEnabled.value = confirmedEnabled.value
      return
    }
    const requestedEnabled = Boolean(enabled)
    telemetrySaving.value = true
    try {
      const response = await httpClient.put(endpoint, {
        enabled: requestedEnabled,
        privacy_notice_version: requestedEnabled ? noticeVersion.value : '',
      }, { timeout: 5000 })
      const status = assertTelemetryEnabledState(response.data || {}, requestedEnabled)
      telemetryEnabled.value = status.enabled
      confirmedEnabled.value = status.enabled
      telemetryPendingEvents.value = Number(status.pending_events || 0)
      telemetryStatusError.value = ''
      notifySuccess(status.enabled ? '已开启去标识使用诊断' : '已关闭并清除本机遥测数据')
    } catch {
      telemetryEnabled.value = confirmedEnabled.value
      notifyError('遥测设置保存失败')
      await loadTelemetryStatus()
    } finally {
      telemetrySaving.value = false
    }
  }

  return {
    telemetryEnabled,
    telemetryPendingEvents,
    telemetrySaving,
    telemetryStatusLoading,
    telemetryStatusLoaded,
    telemetryStatusError,
    loadTelemetryStatus,
    saveTelemetry,
  }
}
