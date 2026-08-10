import { nextTick, ref } from 'vue'

import {
  clearReportLogHistory,
  isPersistableReportLog,
  loadReportLogHistory,
  markInterruptedReportLogs,
  persistReportLogHistory,
} from './processLogHistory.js'

const PROCESS_LOG_CLEARED_AT_KEY = 'knowledgehub.process-log-cleared-at.v1'

export function useProcessLogController({
  batchTasks,
  batchTaskIds,
  getResult = () => ({}),
  getTaskStatus = () => 'idle',
  isActiveTask = () => false,
  logTypeFromMessage = () => 'info',
  resetTaskQueueCursor = () => {},
  storage = globalThis.localStorage,
  now = () => Date.now(),
  defer = nextTick,
} = {}) {
  const restoredReportLogs = loadReportLogHistory(storage)
  const reconciledReportLogs = markInterruptedReportLogs(restoredReportLogs)
  if (reconciledReportLogs.length !== restoredReportLogs.length) {
    persistReportLogHistory(reconciledReportLogs, storage)
  }

  const logs = ref(reconciledReportLogs)
  const logContainer = ref(null)
  const backendLogCount = ref(0)
  const logClearedAt = ref(Number(storage?.getItem(PROCESS_LOG_CLEARED_AT_KEY) || 0))
  const backendLogCountsByTaskId = new Map()

  function addLog(message, type = 'info', step = null, elapsedSeconds = null, context = {}) {
    const contextTimestamp = Number(context.timestamp)
    const timestamp = Number.isFinite(contextTimestamp) ? contextTimestamp : now()
    const entry = {
      ...context,
      time: context.time || new Date(timestamp).toLocaleTimeString(),
      msg: message,
      type,
      step,
      elapsed_seconds: elapsedSeconds,
      timestamp,
    }
    logs.value.push(entry)
    if (isPersistableReportLog(entry)) persistReportLogHistory(logs.value, storage)
    defer(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }

  function clearBackendLogCounts() {
    backendLogCountsByTaskId.clear()
  }

  function clearLogs() {
    logs.value = []
    clearBackendLogCounts()
    clearReportLogHistory(storage)
    logClearedAt.value = now()
    storage?.setItem(PROCESS_LOG_CLEARED_AT_KEY, String(logClearedAt.value))
    resetTaskQueueCursor(new Date(logClearedAt.value).toISOString())
    batchTasks.value = batchTasks.value.filter((task) => isActiveTask(task))
    batchTaskIds.value = batchTasks.value.map((task) => task.task_id)
    backendLogCount.value = 0
  }

  function addBackendLogs(logList, task = {}) {
    if (!Array.isArray(logList)) return
    const result = getResult()
    const taskId = String(task.task_id || result.task_id || '__current__')
    const previousCount = backendLogCountsByTaskId.get(taskId) || 0
    const newItems = logList.slice(previousCount)
    backendLogCountsByTaskId.set(taskId, logList.length)
    if (taskId === String(result.task_id || '__current__')) {
      backendLogCount.value = logList.length
    }
    for (const item of newItems) {
      const itemTimestamp = typeof item === 'object' ? Date.parse(item.created_at || '') : NaN
      if (logClearedAt.value && Number.isFinite(itemTimestamp) && itemTimestamp <= logClearedAt.value) continue
      if (typeof item === 'string') {
        addLog(item, logTypeFromMessage(item))
        continue
      }
      addLog(item.message, item.level || 'info', item.step || null, item.elapsed_seconds ?? null, {
        timestamp: Date.parse(item.created_at || '') || undefined,
        task_id: task.task_id || result.task_id || '',
        task_name: task.display_title || task.source_title || '',
        task_status: task.status || getTaskStatus(),
        task_progress: task.overall_progress ?? result.overall_progress ?? 0,
      })
    }
  }

  return {
    logs,
    logContainer,
    backendLogCount,
    logClearedAt,
    addLog,
    addBackendLogs,
    clearBackendLogCounts,
    clearLogs,
  }
}
