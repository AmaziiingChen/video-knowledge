import { reactive, ref } from 'vue'

function createEmptyTaskResult() {
  return {
    task_id: null,
    content_item_id: null,
    url: null,
    platform: null,
    video_path: null,
    transcript: null,
    summary: null,
    reasoning_content: '',
    reasoning_truncated: false,
    display_title: null,
    source_title: null,
    obsidian_path: null,
    markdown_draft_path: null,
    whisper_model: null,
    asr_backend: null,
    text_source: null,
    ai_calls: [],
    error: null,
    error_info: null,
    persistence_error: null,
    cache_hits: [],
    logs: [],
    timings: {},
    progress: {},
    overall_progress: 0,
    download_transfer: null,
  }
}

export function useActiveTaskStateController({
  logs,
  backendLogCount,
  openSections,
  stopPolling = () => {},
  clearBackendLogCounts = () => {},
  resetQaState = () => {},
  addBackendLogs = () => {},
  addLog = () => {},
} = {}) {
  const running = ref(false)
  const cancelling = ref(false)
  const activeStep = ref(0)
  const currentStep = ref(null)
  const taskStatus = ref('idle')
  const taskCancelRequested = ref(false)
  const result = reactive(createEmptyTaskResult())

  function resetRunState() {
    stopPolling()
    running.value = false
    cancelling.value = false
    logs.value = []
    backendLogCount.value = 0
    clearBackendLogCounts()
    activeStep.value = 0
    currentStep.value = null
    taskStatus.value = 'idle'
    taskCancelRequested.value = false
    openSections.value = ['source', 'timings']
    Object.assign(result, createEmptyTaskResult())
    resetQaState()
  }

  function applyTaskData(data) {
    if (data.task_id && result.task_id && data.task_id !== result.task_id) {
      resetQaState()
    }
    const previousPersistenceError = result.persistence_error
    if (data.logs) {
      result.logs = data.logs
      addBackendLogs(data.logs, data)
    }
    result.task_id = data.task_id || null
    result.content_item_id = data.content_item_id || null
    result.timings = data.timings || {}
    result.url = data.url
    result.platform = data.platform
    result.video_path = data.video_path
    result.transcript = data.transcript
    result.summary = data.summary
    result.reasoning_content = data.reasoning_content || ''
    result.reasoning_truncated = Boolean(data.reasoning_truncated)
    result.display_title = data.display_title || null
    result.source_title = data.source_title || null
    result.obsidian_path = data.obsidian_path
    result.markdown_draft_path = data.markdown_draft_path || null
    result.whisper_model = data.whisper_model || null
    result.asr_backend = data.asr_backend || null
    result.text_source = data.text_source || null
    result.ai_calls = data.ai_calls || []
    result.error = data.error || null
    result.error_info = data.error_info || null
    result.persistence_error = data.persistence_error || null
    result.cache_hits = data.cache_hits || []
    result.progress = data.progress || {}
    result.overall_progress = Number(data.overall_progress || 0)
    result.download_transfer = data.download_transfer || null
    taskStatus.value = data.status || (data.success ? 'succeeded' : data.error ? 'failed' : taskStatus.value)
    taskCancelRequested.value = Boolean(data.cancel_requested)
    currentStep.value = data.step || null
    if (data.persistence_error && data.persistence_error !== previousPersistenceError) {
      addLog(`本地保存失败：${data.persistence_error}`, 'error', data.step || null, null, {
        task_id: data.task_id || result.task_id || '',
        task_name: data.display_title || data.source_title || '',
        task_status: data.status || taskStatus.value,
        task_progress: data.overall_progress ?? result.overall_progress ?? 0,
      })
    }

    const stepMap = {
      parse: 1,
      info: 1,
      download: 2,
      extract_audio: 3,
      transcribe: 4,
      summarize: 5,
      save: 6,
      total: 6,
      cancelled: activeStep.value,
    }
    if (taskStatus.value === 'succeeded') {
      activeStep.value = 6
    } else if (data.step && stepMap[data.step] !== undefined) {
      activeStep.value = stepMap[data.step]
    }
  }

  return {
    running,
    cancelling,
    activeStep,
    currentStep,
    taskStatus,
    taskCancelRequested,
    result,
    resetRunState,
    applyTaskData,
  }
}
