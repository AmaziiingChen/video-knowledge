import { computed } from 'vue'

export function useProcessLogProjectionController({
  logs,
  logClearedAt,
  result,
  statusbarProgress,
  batchTasks,
  batchTaskName,
  formatProcessLogTime,
  logTypeFromMessage,
  now = Date.now,
} = {}) {
  const processLogEntries = computed(() => {
    const entries = []
    const clearedAt = logClearedAt.value

    for (const item of logs.value) {
      const timestamp = item.timestamp || 0
      if (timestamp >= clearedAt) {
        entries.push({
          ...item,
          timestamp,
          task_id: item.task_id || result.task_id || '',
          task_name: item.task_name || statusbarProgress.value.detail || result.url || '',
        })
      }
    }

    for (const task of batchTasks.value) {
      const taskName = batchTaskName(task)
      const taskLogs = Array.isArray(task.logs) ? task.logs : []
      const aiCalls = Array.isArray(task.ai_calls) ? task.ai_calls : []
      const reportedCalls = aiCalls.filter((call) => (
        call?.prompt_tokens !== null
        && call?.prompt_tokens !== undefined
        && call?.completion_tokens !== null
        && call?.completion_tokens !== undefined
        && Number.isFinite(Number(call.prompt_tokens))
        && Number.isFinite(Number(call.completion_tokens))
      ))
      const promptTokens = reportedCalls.reduce((sum, call) => sum + Number(call.prompt_tokens), 0)
      const completionTokens = reportedCalls.reduce((sum, call) => sum + Number(call.completion_tokens), 0)
      for (const [index, item] of taskLogs.entries()) {
        const timestamp = Date.parse(item.created_at || '')
          || Date.parse(task.updated_at || task.created_at || '')
          || 0
        if (clearedAt && timestamp <= clearedAt) continue
        const isLatestLog = index === taskLogs.length - 1
        entries.push({
          time: item.time || formatProcessLogTime(item.created_at || task.updated_at || task.created_at),
          msg: item.message || String(item),
          type: item.level || logTypeFromMessage(item.message || String(item)),
          step: item.step || task.step || null,
          elapsed_seconds: item.elapsed_seconds ?? null,
          timestamp,
          task_id: task.task_id,
          task_name: taskName,
          task_status: task.status,
          task_progress: task.overall_progress,
          prompt_tokens: isLatestLog && reportedCalls.length ? promptTokens : null,
          completion_tokens: isLatestLog && reportedCalls.length ? completionTokens : null,
          total_tokens: isLatestLog && reportedCalls.length ? promptTokens + completionTokens : null,
        })
      }
      if (task.persistence_error) {
        const timestamp = Date.parse(task.updated_at || task.created_at || '') || now()
        if (!clearedAt || timestamp > clearedAt) {
          entries.push({
            time: formatProcessLogTime(task.updated_at || task.created_at),
            msg: `本地保存失败：${task.persistence_error}`,
            type: 'error',
            step: task.step || null,
            timestamp,
            task_id: task.task_id,
            task_name: taskName,
            task_status: task.status,
            task_progress: task.overall_progress,
          })
        }
      }
    }

    const deduplicated = new Map()
    for (const item of entries.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))) {
      const key = `${item.task_id}|${item.timestamp || 0}|${item.step || ''}|${item.msg}|${item.elapsed_seconds ?? ''}`
      deduplicated.set(key, item)
    }
    return [...deduplicated.values()].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
  })

  return { processLogEntries }
}
