function sortableTimestamp(value) {
  const numericTimestamp = Number(value)
  if (Number.isFinite(numericTimestamp)) return numericTimestamp
  const parsedTimestamp = Date.parse(value || '')
  return Number.isFinite(parsedTimestamp) ? parsedTimestamp : 0
}

export function isActiveProcessLogTask(task) {
  return ['queued', 'running', 'paused'].includes(task?.status)
}

// A task may be active without a measurable percentage (for example while a
// remote service is waiting). Only expose a bar when the queue provided an
// actual finite value; this prevents a decorative or misleading progress bar.
export function boundedTaskProgress(task) {
  if (!['queued', 'running'].includes(task?.status)) return null
  const value = Number(task?.overall_progress)
  if (!Number.isFinite(value)) return null
  return Math.round(Math.max(0, Math.min(100, value)))
}

export function processLogEntriesForTask(logs = [], taskId = '') {
  if (!taskId) return []
  return logs
    .filter((item) => item.task_id === taskId)
    .slice()
    .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
}

export function visibleProcessLogTasks(logs = [], batchTasks = []) {
  const latestLogByTaskId = new Map()
  logs.forEach((item, index) => {
    if (!item.task_id) return
    const previous = latestLogByTaskId.get(item.task_id)
    const timestamp = sortableTimestamp(item.timestamp)
    if (!previous || timestamp >= previous.timestamp) {
      latestLogByTaskId.set(item.task_id, { item, timestamp, index })
    }
  })

  const tasksById = new Map()
  for (const [taskIndex, task] of batchTasks.entries()) {
    const latestLog = latestLogByTaskId.get(task.task_id)
    tasksById.set(task.task_id, {
      ...task,
      timestamp: latestLog?.timestamp
        ?? sortableTimestamp(task.updated_at || task.created_at),
      sortIndex: latestLog?.index ?? logs.length + taskIndex,
    })
  }

  for (const [taskId, latestLog] of latestLogByTaskId) {
    if (tasksById.has(taskId)) continue
    const { item, timestamp, index } = latestLog
    const status = item.task_status || (item.type === 'error' ? 'failed' : item.type === 'success' ? 'succeeded' : 'running')
    tasksById.set(taskId, {
      task_id: taskId,
      display_title: item.task_name || '手动处理',
      status,
      step: item.step || 'summarize',
      overall_progress: item.task_progress ?? (status === 'succeeded' ? 100 : 0),
      timestamp,
      sortIndex: index,
    })
  }

  // Both panes follow the same direction: old work is above, the most recent
  // task sits at the bottom next to its newest log line.
  return [...tasksById.values()]
    .sort((a, b) => a.timestamp - b.timestamp || a.sortIndex - b.sortIndex)
}

export function preferredProcessLogTaskId(tasks = []) {
  const newestActiveTask = [...tasks]
    .reverse()
    .find((task) => isActiveProcessLogTask(task))
  return newestActiveTask?.task_id || tasks.at(-1)?.task_id || ''
}
