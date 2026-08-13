export function createTaskDisplayPresentation({
  getTaskStatus,
  getCurrentStep,
  getResult,
  getParsedUrl,
  getTaskNames,
  getLogClearedAt,
  sourceProviderFromUrl,
  sourceProviderLabel,
  formatBytes,
  roundedProgress,
  stepNames,
  modelProfiles,
  promptTaskOptions,
}) {
  function isActiveTask(task) {
    return ['queued', 'running', 'paused'].includes(task?.status)
  }

  function statusbarStageLabel(task = null) {
    const result = getResult()
    const status = task?.status || getTaskStatus()
    if (status === 'queued') return '等待中'
    if (status === 'paused') return '已暂停'

    const step = task?.step || getCurrentStep()
    const platform = task
      ? (task.platform || task.source_provider || sourceProviderFromUrl(task.source_url || task.url))
      : (result.platform || getParsedUrl()?.platform)
    if (step === 'info' && platform === 'wechat') return '读取文章'
    const labels = {
      parse: '解析链接',
      info: '读取信息',
      download: '下载视频',
      extract_audio: '提取音频',
      transcribe: '转写音频',
      summarize: 'AI 总结',
      save: '保存内容',
    }
    return labels[step] || '处理中'
  }

  function statusbarTaskContext(task = null) {
    const result = getResult()
    const title = task
      ? (getTaskNames()[task.task_id] || task.display_title || task.source_title)
      : result.source_title
    if (title && !/^https?:\/\//i.test(title)) return title

    const platform = task
      ? (task.platform || task.source_provider || sourceProviderFromUrl(task.source_url || task.url))
      : (result.platform || getParsedUrl()?.platform)
    if (platform) return `${sourceProviderLabel(platform)}内容`
    if (task?.local_video_path || result.video_path) return '本地视频'
    if (task?.local_subtitle_path) return '字幕文件'
    return '当前内容'
  }

  function statusbarTransferDetail(transfer, fallback) {
    if (!transfer) return fallback
    const parts = [transfer.detail].filter(Boolean)
    const received = Number(transfer.received_bytes)
    const total = Number(transfer.total_bytes)
    const speed = Number(transfer.bytes_per_second)
    if (Number.isFinite(received) && received >= 0) {
      parts.push(Number.isFinite(total) && total > 0
        ? `${formatBytes(received)} / ${formatBytes(total)}`
        : `${formatBytes(received)} 已接收`)
    }
    if (Number.isFinite(speed) && speed > 0) parts.push(`${formatBytes(speed)}/s`)
    return parts.join(' · ') || fallback
  }

  function shouldDisplayTask(task) {
    if (isActiveTask(task)) return true
    const clearedAt = getLogClearedAt()
    if (!clearedAt) return true
    const createdAt = Date.parse(task?.created_at || '')
    return Number.isFinite(createdAt) && createdAt > clearedAt
  }

  function logTypeFromMessage(message) {
    return String(message || '').includes('失败') || String(message || '').includes('错误') || String(message || '').includes('ERROR') ? 'error'
      : String(message || '').includes('完成') || String(message || '').includes('成功') ? 'success'
      : String(message || '').includes('WARNING') || String(message || '').includes('警告') ? 'warn'
      : 'info'
  }

  function formatProcessLogTime(value) {
    const timestamp = Date.parse(value || '')
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleTimeString() : '—'
  }

  function progressStatus(status, stageKey = null, task = null) {
    if (status === 'succeeded') return 'success'
    if (status === 'failed') return 'exception'
    if (status === 'cancelled' || status === 'paused') return 'warning'
    if (stageKey && stageProgress(stageKey, task) >= 100) return 'success'
    return undefined
  }

  function stageProgress(stageKey, task = null) {
    const source = task?.progress || getResult().progress || {}
    return roundedProgress(source[stageKey])
  }

  function stepLabel(step) {
    return stepNames[step] || step
  }

  function modelLabel(model) {
    if (!model) return '默认'
    const profile = modelProfiles.find((item) => item.model === model)
    return profile ? profile.label : model
  }

  function promptTaskLabel(taskType) {
    const option = promptTaskOptions.find((item) => item.value === taskType)
    return option ? option.label : taskType
  }

  return {
    formatProcessLogTime,
    isActiveTask,
    logTypeFromMessage,
    modelLabel,
    progressStatus,
    promptTaskLabel,
    shouldDisplayTask,
    stageProgress,
    statusbarStageLabel,
    statusbarTaskContext,
    statusbarTransferDetail,
    stepLabel,
  }
}
