export function useActiveTaskEventStreamController({
  apiBase,
  eventSourceFactory = null,
  mergeBatchTasks,
  applyTaskData,
  hydrateProgressiveTask,
  progressiveTaskSnapshots,
  terminalStatuses,
  isActiveTask,
}) {
  let eventSource = null
  let eventSourceTaskId = ''

  function stopTaskEventStream() {
    eventSource?.close()
    eventSource = null
    eventSourceTaskId = ''
  }

  function startTaskEventStream(taskId) {
    const normalizedTaskId = String(taskId || '')
    if (!normalizedTaskId || !eventSourceFactory) return
    if (eventSource && eventSourceTaskId === normalizedTaskId) return
    stopTaskEventStream()

    const source = eventSourceFactory(`${apiBase}/tasks/${encodeURIComponent(normalizedTaskId)}/events`)
    eventSource = source
    eventSourceTaskId = normalizedTaskId
    source.addEventListener('task', (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (String(data?.task_id || '') !== normalizedTaskId) return
      mergeBatchTasks([data])
      applyTaskData(data)
      const previousSnapshot = progressiveTaskSnapshots.get(normalizedTaskId)
      void hydrateProgressiveTask(data, previousSnapshot)
      if (terminalStatuses.has(data.status) && eventSourceTaskId === normalizedTaskId) {
        stopTaskEventStream()
      }
    })
    source.addEventListener('error', () => {
      // EventSource retries itself; durable queue polling remains the fallback
      // if a local backend restart closes this channel.
    })
  }

  function syncTaskEventStream({ activeContentItemId, batchTasks }) {
    const contentItemId = String(activeContentItemId || '')
    const activeTask = contentItemId
      ? batchTasks.find((task) => (
        String(task?.content_item_id || '') === contentItemId && isActiveTask(task)
      ))
      : null
    if (activeTask?.task_id) {
      startTaskEventStream(activeTask.task_id)
      return
    }
    if (eventSourceTaskId) stopTaskEventStream()
  }

  return {
    startTaskEventStream,
    stopTaskEventStream,
    syncTaskEventStream,
  }
}
