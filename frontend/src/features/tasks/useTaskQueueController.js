import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useTaskQueueController({
  batchTasks,
  batchTaskIds,
  batchTaskNames,
  progressiveTaskSnapshots,
  terminalStatuses,
  shouldDisplayTask,
  isActiveTask,
  shouldRefreshContentForTask,
  taskContentSnapshot,
  hydrateProgressiveTask,
  loadContentItems,
  isActiveContentTask = () => false,
  shouldContinueBatchPolling = () => false,
  getActiveTaskId = () => '',
  applyTaskData = () => {},
  notify = ElMessage,
  request = axios,
  apiBase = API,
  initialUpdatedAfter = '',
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  scheduleInterval = setInterval,
  cancelInterval = clearInterval,
}) {
  let batchPollTimer = null
  let taskQueueTimer = null
  let taskQueuePollingIntervalMs = 2000
  let taskQueueSyncing = false
  let taskQueueInitialized = false
  let taskQueueUpdatedAfter = initialUpdatedAfter
  const taskQueueSnapshots = new Map()
  const loadingBatchTaskDetailIds = new Set()

  function mergeBatchTasks(tasks) {
    const byId = new Map(batchTasks.value.map((task) => [task.task_id, task]))
    for (const task of tasks) {
      const existing = byId.get(task.task_id)
      if (task.details_included === false && existing) {
        const merged = { ...existing, ...task }
        const detailFields = [
          'text_source',
          'ai_calls',
          'cache_hits',
          'logs',
          'timings',
          'error_info',
          'transcript',
          'summary',
          'reasoning_content',
        ]
        detailFields.forEach((field) => {
          if (existing[field] !== undefined) merged[field] = existing[field]
        })
        merged.details_included = Boolean(
          existing.detail_updated_at
          && existing.detail_updated_at === task.updated_at
        )
        merged.detail_updated_at = existing.detail_updated_at || ''
        byId.set(task.task_id, merged)
        continue
      }
      byId.set(task.task_id, {
        ...existing,
        ...task,
        detail_updated_at: task.updated_at || existing?.detail_updated_at || '',
      })
    }
    batchTasks.value = batchTaskIds.value
      .map((id) => byId.get(id))
      .filter(Boolean)
  }

  function batchTaskName(task) {
    return batchTaskNames.value[task.task_id]
      || task.display_title
      || task.source_title
      || task.local_video_path?.split('/').pop()
      || task.local_subtitle_path?.split('/').pop()
      || task.video_path?.split('/').pop()
      || task.url
      || `任务 ${task.task_id}`
  }

  function registerBatchTask(task, item, { merge = true, allowSourceUrlFallback = true } = {}) {
    const taskId = task?.task_id
    if (!taskId) return
    batchTaskNames.value[taskId] = item?.title || (allowSourceUrlFallback ? item?.source_url : '') || `任务 ${taskId}`
    batchTaskIds.value = [...new Set([...batchTaskIds.value, taskId])]
    if (merge) mergeBatchTasks([task])
  }

  function stopBatchPolling() {
    if (!batchPollTimer) return
    cancelSchedule(batchPollTimer)
    batchPollTimer = null
  }

  function startTaskQueuePolling() {
    if (taskQueueTimer) return
    taskQueueTimer = scheduleInterval(loadTaskQueue, taskQueuePollingIntervalMs)
  }

  function stopTaskQueuePolling() {
    if (!taskQueueTimer) return
    cancelInterval(taskQueueTimer)
    taskQueueTimer = null
  }

  function setTaskQueuePollingInterval(intervalMs) {
    const nextInterval = Math.max(2000, Number(intervalMs) || 2000)
    if (taskQueuePollingIntervalMs === nextInterval) return
    taskQueuePollingIntervalMs = nextInterval
    if (!taskQueueTimer) return
    stopTaskQueuePolling()
    startTaskQueuePolling()
  }

  function resetTaskQueueCursor(updatedAfter = '') {
    taskQueueUpdatedAfter = updatedAfter
  }

  async function loadTaskQueue() {
    if (taskQueueSyncing) return
    taskQueueSyncing = true
    try {
      const requestStartedAt = new Date().toISOString()
      const params = taskQueueUpdatedAfter
        ? { updated_after: taskQueueUpdatedAfter }
        : undefined
      const response = await request.get(`${apiBase}/tasks`, { params, timeout: 10000 })
      taskQueueUpdatedAfter = requestStartedAt
      const tasks = response.data || []
      const visibleTasks = tasks.filter((task) => shouldDisplayTask(task))
      const taskIds = visibleTasks.map((task) => task.task_id).filter(Boolean)
      let shouldRefreshContent = false
      const progressiveUpdates = []
      for (const task of visibleTasks) {
        const previousSnapshot = taskQueueSnapshots.get(task.task_id)
        const previousProgressiveSnapshot = progressiveTaskSnapshots.get(task.task_id)
        shouldRefreshContent = shouldRefreshContent || shouldRefreshContentForTask(
          task,
          previousSnapshot,
          taskQueueInitialized,
          terminalStatuses
        )
        taskQueueSnapshots.set(task.task_id, taskContentSnapshot(task))
        if (
          taskQueueInitialized
          || isActiveTask(task)
          || isActiveContentTask(task)
        ) {
          progressiveUpdates.push(hydrateProgressiveTask(task, previousProgressiveSnapshot))
        }
      }

      if (!tasks.length) {
        taskQueueInitialized = true
        return
      }
      batchTaskIds.value = [...new Set([...batchTaskIds.value, ...taskIds])]
      mergeBatchTasks(visibleTasks)
      taskQueueInitialized = true
      await Promise.allSettled(progressiveUpdates)
      if (shouldRefreshContent) await loadContentItems()
      if (shouldContinueBatchPolling()) await pollBatchTasks()
    } catch {
      // Queue refresh remains a best-effort background operation. A manual
      // single-task flow continues to expose its own recovery message.
    } finally {
      taskQueueSyncing = false
    }
  }

  async function pollBatchTasks() {
    stopBatchPolling()
    if (!batchTaskIds.value.length) return

    try {
      const knownTasks = new Map(batchTasks.value.map((task) => [task.task_id, task]))
      const taskIds = batchTaskIds.value.filter((taskId) => {
        const task = knownTasks.get(taskId)
        return !task || isActiveTask(task)
      }).slice(0, 200)
      if (!taskIds.length) return
      const response = await request.get(`${apiBase}/tasks`, {
        params: { task_ids: taskIds.join(',') },
        timeout: 10000,
      })
      const byId = new Map((response.data || []).map((task) => [task.task_id, task]))
      const nextTasks = batchTaskIds.value.map((id) => byId.get(id)).filter(Boolean)
      const previousStatusByTaskId = new Map(batchTasks.value.map((task) => [task.task_id, task.status]))
      const previousProgressiveSnapshots = new Map(
        nextTasks.map((task) => [task.task_id, progressiveTaskSnapshots.get(task.task_id)])
      )
      const newlyCompletedContentTasks = nextTasks.filter((task) => (
        task.content_item_id
        && terminalStatuses.has(task.status)
        && !terminalStatuses.has(previousStatusByTaskId.get(task.task_id))
      ))
      mergeBatchTasks(nextTasks)
      await Promise.allSettled(nextTasks.map((task) => (
        hydrateProgressiveTask(task, previousProgressiveSnapshots.get(task.task_id))
      )))
      if (newlyCompletedContentTasks.length) await loadContentItems()
      if (shouldContinueBatchPolling()) {
        const hasStreamingSummary = nextTasks.some((task) => (
          task.status === 'running'
          && Number(task?.progress?.summarize || 0) > 0
          && Number(task?.progress?.summarize || 0) < 100
        ))
        batchPollTimer = schedule(pollBatchTasks, hasStreamingSummary ? 320 : 1500)
      } else {
        await loadContentItems()
      }
    } catch {
      batchPollTimer = schedule(pollBatchTasks, 3000)
    }
  }

  async function cancelBatchTask(task) {
    try {
      const response = await request.post(`${apiBase}/tasks/${task.task_id}/cancel`, {}, { timeout: 10000 })
      mergeBatchTasks([response.data])
      if (response.data.task_id === getActiveTaskId()) applyTaskData(response.data)
      notify.warning('已请求取消')
      await pollBatchTasks()
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '取消失败'
      notify.error(message)
    }
  }

  async function cancelActiveTasks() {
    try {
      const response = await request.post(`${apiBase}/tasks/cancel-active`, {}, { timeout: 10000 })
      const cancelled = Array.isArray(response.data?.tasks) ? response.data.tasks : []
      if (!cancelled.length) {
        notify.info('当前没有可取消的任务')
        return
      }
      mergeBatchTasks(cancelled)
      const activeResult = cancelled.find((task) => task.task_id === getActiveTaskId())
      if (activeResult) applyTaskData(activeResult)
      notify.warning(`已请求取消 ${response.data.cancelled_count || cancelled.length} 个任务`)
      await pollBatchTasks()
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '批量取消失败'
      notify.error(typeof message === 'string' ? message : '批量取消失败')
    }
  }

  async function loadBatchTaskDetails(task) {
    const taskId = task?.task_id
    if (!taskId || loadingBatchTaskDetailIds.has(taskId)) return
    if (
      task.details_included !== false
      && task.detail_updated_at
      && task.detail_updated_at === task.updated_at
    ) return

    loadingBatchTaskDetailIds.add(taskId)
    try {
      const response = await request.get(`${apiBase}/tasks/${taskId}`, { timeout: 10000 })
      mergeBatchTasks([response.data])
    } catch {
      // The queue summary remains usable when one historical detail request
      // fails; a later selection or task update retries it.
    } finally {
      loadingBatchTaskDetailIds.delete(taskId)
    }
  }

  async function retryBatchTask(task) {
    try {
      const response = await request.post(`${apiBase}/tasks/${task.task_id}/retry`, {}, { timeout: 10000 })
      mergeBatchTasks([response.data])
      notify.success('已重新加入队列')
      await pollBatchTasks()
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '重试失败'
      notify.error(message)
    }
  }

  return {
    mergeBatchTasks,
    batchTaskName,
    registerBatchTask,
    stopBatchPolling,
    startTaskQueuePolling,
    stopTaskQueuePolling,
    setTaskQueuePollingInterval,
    resetTaskQueueCursor,
    loadTaskQueue,
    pollBatchTasks,
    cancelBatchTask,
    cancelActiveTasks,
    loadBatchTaskDetails,
    retryBatchTask,
  }
}
