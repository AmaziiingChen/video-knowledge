import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useClipboardController({
  activeView,
  aiRequestOptions,
  asrRequestOptions,
  batchTaskIds,
  batchTaskNames,
  pollBatchTasks,
  recordTelemetry,
  useCache
}) {
  const clipboardWatching = ref(false)
  const clipboardTimer = ref(null)
  const clipboardScanning = ref(false)
  const clipboardStatus = ref('未开启')
  const clipboardCapturedLinks = ref([])

  const clipboardStatusText = computed(() => {
    if (clipboardWatching.value) return clipboardStatus.value || '监听中'
    if (clipboardCapturedLinks.value.length) return `最近捕获 ${clipboardCapturedLinks.value.length} 条`
    return clipboardStatus.value || '未开启'
  })

  function stopClipboardStatusPolling() {
    if (!clipboardTimer.value) return
    clearInterval(clipboardTimer.value)
    clipboardTimer.value = null
  }

  async function toggleClipboardWatching(enabled) {
    if (enabled) await startClipboardWatching()
    else await stopClipboardWatching()
  }

  async function startClipboardWatching() {
    clipboardScanning.value = true
    try {
      const response = await axios.post(`${API}/clipboard-watcher/start`, {
        ...asrRequestOptions(),
        ...aiRequestOptions(),
        use_cache: useCache.value,
        poll_interval: 2.5,
        capture_mode: 'task'
      }, { timeout: 10000 })
      const freshIds = applyClipboardStatus(response.data)
      startClipboardStatusPolling()
      if (freshIds.length) await pollBatchTasks()
      ElMessage.success('本机剪贴板监听已开启')
      void recordTelemetry('clipboard_listener_changed', { state: 'enabled' })
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '开启监听失败'
      clipboardWatching.value = false
      clipboardStatus.value = typeof message === 'string' ? message : '开启监听失败'
      ElMessage.error(clipboardStatus.value)
    } finally {
      clipboardScanning.value = false
    }
  }

  async function stopClipboardWatching() {
    clipboardScanning.value = true
    try {
      const response = await axios.post(`${API}/clipboard-watcher/stop`, {}, { timeout: 10000 })
      stopClipboardStatusPolling()
      applyClipboardStatus(response.data)
      ElMessage.success('本机剪贴板监听已停止')
      void recordTelemetry('clipboard_listener_changed', { state: 'disabled' })
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '停止监听失败'
      ElMessage.error(typeof message === 'string' ? message : '停止监听失败')
    } finally {
      clipboardScanning.value = false
    }
  }

  function startClipboardStatusPolling() {
    if (clipboardTimer.value) return
    clipboardTimer.value = setInterval(loadClipboardStatus, 2000)
  }

  async function loadClipboardStatus() {
    try {
      const response = await axios.get(`${API}/clipboard-watcher`, { timeout: 10000 })
      const freshIds = applyClipboardStatus(response.data)
      if (response.data.running) startClipboardStatusPolling()
      if (freshIds.length) await pollBatchTasks()
    } catch (error) {
      if (clipboardWatching.value) clipboardStatus.value = error.message || '读取监听状态失败'
    }
  }

  function applyClipboardStatus(data) {
    const wasRunning = clipboardWatching.value
    clipboardWatching.value = Boolean(data.running)
    clipboardStatus.value = data.last_error || (data.running ? '本机监听中' : '未开启')
    clipboardCapturedLinks.value = (data.captured_links || [])
      .map((item) => item.link || item)
      .filter(Boolean)
      .slice(0, 6)

    for (const item of data.captured_links || []) {
      if (item?.task_id && !batchTaskNames.value[item.task_id]) {
        batchTaskNames.value[item.task_id] = item.link || `任务 ${item.task_id}`
      }
    }
    const ids = data.created_task_ids || []
    const freshIds = ids.filter((id) => !batchTaskIds.value.includes(id))
    if (freshIds.length) {
      batchTaskIds.value = [...new Set([...batchTaskIds.value, ...freshIds])]
      activeView.value = 'library'
    }
    if (wasRunning && !data.running) stopClipboardStatusPolling()
    return freshIds
  }

  return {
    clipboardWatching,
    clipboardScanning,
    clipboardStatus,
    clipboardStatusText,
    stopClipboardStatusPolling,
    toggleClipboardWatching,
    loadClipboardStatus
  }
}
