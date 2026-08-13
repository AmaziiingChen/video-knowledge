import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLinkIngestController({
  result,
  activeStep,
  running,
  openSections,
  useCache,
  resetRunState,
  applyTaskData,
  addLog,
  addBackendLogs,
  recordTelemetry,
  registerBatchTask,
  hydrateProgressiveTask,
  getProgressiveSnapshot = () => undefined,
  pollTask,
  getAsrRequestOptions = () => ({}),
  getAiRequestOptions = () => ({}),
  request = axios,
  apiBase = API,
  notify = ElMessage,
  schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
  cancel = (timer) => globalThis.clearTimeout(timer),
} = {}) {
  const shareText = ref('')
  const parsedUrl = ref(null)
  let parseTimer = null
  let parseRequestId = 0

  async function parseShareText(text) {
    const requestId = ++parseRequestId
    if (!shareText.value.trim()) {
      parsedUrl.value = null
      return
    }
    try {
      const response = await request.post(`${apiBase}/parse`, { text })
      if (requestId !== parseRequestId || text !== shareText.value.trim()) return
      if (response.data.success) {
        parsedUrl.value = { url: response.data.url, platform: response.data.platform }
        result.url = response.data.url
        result.platform = response.data.platform
        activeStep.value = 1
      } else {
        parsedUrl.value = null
      }
    } catch {
      parsedUrl.value = null
    }
  }

  async function onInputChange() {
    if (parseTimer) {
      cancel(parseTimer)
      parseTimer = null
    }
    const text = shareText.value.trim()
    if (!text) {
      parseRequestId += 1
      parsedUrl.value = null
      return
    }
    parseTimer = schedule(() => {
      parseTimer = null
      void parseShareText(text)
    }, 260)
  }

  async function runFullPipeline() {
    const text = shareText.value.trim()
    if (!text) {
      notify.warning('请输入链接')
      return
    }

    resetRunState()
    running.value = true
    void recordTelemetry('import_started', { input_kind: 'link' })
    addLog('提交任务…', 'info')

    try {
      const response = await request.post(`${apiBase}/ingest/link`, {
        text,
        mode: 'process',
        ...getAsrRequestOptions(),
        ...getAiRequestOptions(),
        use_cache: useCache.value,
      }, { timeout: 10000 })
      const task = response.data.task || response.data
      if (!task?.task_id) throw new Error('链接已识别，但未能创建处理任务')
      applyTaskData(task)
      registerBatchTask(task, {
        title: response.data.item?.title || task.source_title || text,
      })
      await hydrateProgressiveTask(task, getProgressiveSnapshot(task.task_id))
      parseRequestId += 1
      shareText.value = ''
      parsedUrl.value = null
      addLog(`任务已创建: ${task.task_id}`, 'success')
      void recordTelemetry('import_completed', { result: 'accepted' })
      pollTask(task.task_id)
    } catch (error) {
      const detail = error.response?.data?.detail
      if (detail && typeof detail === 'object') {
        if (detail.logs) addBackendLogs(detail.logs)
        if (detail.timings) result.timings = detail.timings
        addLog(`失败: ${detail.error}`, 'error')
        openSections.value = ['logs']
        notify.error(detail.error)
      } else {
        const message = typeof detail === 'string' ? detail : (error.message || '请求失败')
        addLog(`失败: ${message}`, 'error')
        openSections.value = ['logs']
        notify.error(message)
      }
    } finally {
      if (!result.task_id) running.value = false
    }
  }

  function dispose() {
    parseRequestId += 1
    if (!parseTimer) return
    cancel(parseTimer)
    parseTimer = null
  }

  return {
    shareText,
    parsedUrl,
    onInputChange,
    runFullPipeline,
    dispose,
  }
}
