export const REPORT_LOG_HISTORY_KEY = 'video-knowledge.report-process-logs.v1'
export const MAX_REPORT_LOG_HISTORY = 300


export function loadReportLogHistory(storage = globalThis.localStorage) {
  if (!storage) return []
  try {
    const parsed = JSON.parse(storage.getItem(REPORT_LOG_HISTORY_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(isPersistableReportLog)
      .slice(-MAX_REPORT_LOG_HISTORY)
  } catch {
    return []
  }
}


export function persistReportLogHistory(entries, storage = globalThis.localStorage) {
  if (!storage) return
  const reportEntries = (Array.isArray(entries) ? entries : [])
    .filter(isPersistableReportLog)
    .slice(-MAX_REPORT_LOG_HISTORY)
  try {
    storage.setItem(REPORT_LOG_HISTORY_KEY, JSON.stringify(reportEntries))
  } catch {
    // The process log is diagnostic state; storage quota errors must not affect generation.
  }
}


export function markInterruptedReportLogs(entries, now = Date.now()) {
  const reportEntries = (Array.isArray(entries) ? entries : []).filter(isPersistableReportLog)
  const latestByTaskId = new Map()
  for (const entry of reportEntries) {
    const previous = latestByTaskId.get(entry.task_id)
    if (!previous || Number(entry.timestamp) >= Number(previous.timestamp)) {
      latestByTaskId.set(entry.task_id, entry)
    }
  }

  const interrupted = []
  for (const entry of latestByTaskId.values()) {
    if (!['queued', 'running', 'paused'].includes(entry.task_status)) continue
    interrupted.push({
      task_id: entry.task_id,
      task_name: entry.task_name || '报告生成',
      task_status: 'failed',
      task_progress: Number(entry.task_progress || 0),
      time: new Date(now).toLocaleTimeString(),
      msg: '报告任务已中断：应用或报告服务在完成前重新启动，请重新生成。',
      type: 'error',
      step: entry.step || 'report_prepare',
      elapsed_seconds: null,
      timestamp: Math.max(Number(now), Number(entry.timestamp || 0) + 1),
    })
  }
  return interrupted.length
    ? [...reportEntries, ...interrupted].slice(-MAX_REPORT_LOG_HISTORY)
    : reportEntries
}


export function clearReportLogHistory(storage = globalThis.localStorage) {
  if (!storage) return
  try {
    storage.removeItem(REPORT_LOG_HISTORY_KEY)
  } catch {
    // Clearing visible logs remains successful even if storage is temporarily unavailable.
  }
}


export function isPersistableReportLog(entry) {
  return Boolean(
    entry
    && typeof entry === 'object'
    && typeof entry.task_id === 'string'
    && entry.task_id.startsWith('report:')
    && typeof entry.msg === 'string'
    && Number.isFinite(Number(entry.timestamp))
  )
}
