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
  const telemetryUploadResult = ref('')
  const telemetryLastUploadAttemptAt = ref('')
  const telemetryLastUploadSuccessAt = ref('')
  const telemetryUploadRetrying = ref(false)
  const noticeVersion = ref('')

  function applyStatus(status) {
    telemetryEnabled.value = status.enabled
    confirmedEnabled.value = status.enabled
    telemetryPendingEvents.value = Number(status.pending_events || 0)
    noticeVersion.value = String(status.privacy_notice_version || '')
    telemetryUploadResult.value = String(status.last_upload_result || '')
    telemetryLastUploadAttemptAt.value = String(status.last_upload_attempt_at || '')
    telemetryLastUploadSuccessAt.value = String(status.last_upload_success_at || '')
  }

  async function loadTelemetryStatus() {
    telemetryStatusLoading.value = true
    telemetryStatusLoaded.value = false
    telemetryStatusError.value = ''
    try {
      const response = await httpClient.get(endpoint, { timeout: 5000 })
      if (typeof response.data?.enabled !== 'boolean') throw new Error('invalid telemetry status')
      applyStatus(response.data)
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
      applyStatus({
        ...status,
        last_upload_result: telemetryUploadResult.value,
        last_upload_attempt_at: telemetryLastUploadAttemptAt.value,
        last_upload_success_at: telemetryLastUploadSuccessAt.value,
      })
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

  async function retryTelemetryUpload() {
    if (!telemetryStatusLoaded.value || !confirmedEnabled.value || telemetryUploadRetrying.value) return
    telemetryUploadRetrying.value = true
    try {
      await httpClient.post(`${endpoint}/upload`, {}, { timeout: 8000 })
      await loadTelemetryStatus()
      if (telemetryUploadResult.value === 'failed') {
        notifyError('诊断数据仍无法连接 Cloudflare，将在后台自动重试')
      } else {
        notifySuccess(telemetryPendingEvents.value ? '已发送一批诊断数据' : '诊断数据已上传')
      }
    } catch {
      notifyError('诊断数据上传失败，将在后台自动重试')
      await loadTelemetryStatus()
    } finally {
      telemetryUploadRetrying.value = false
    }
  }

  return {
    telemetryEnabled,
    telemetryPendingEvents,
    telemetrySaving,
    telemetryStatusLoading,
    telemetryStatusLoaded,
    telemetryStatusError,
    telemetryUploadResult,
    telemetryLastUploadAttemptAt,
    telemetryLastUploadSuccessAt,
    telemetryUploadRetrying,
    loadTelemetryStatus,
    saveTelemetry,
    retryTelemetryUpload,
  }
}
