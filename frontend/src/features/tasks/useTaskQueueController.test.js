import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useTaskQueueController } from './useTaskQueueController.js'

function createController({
  batchTasks = [],
  batchTaskIds = [],
  request = {},
  shouldContinueBatchPolling = () => false,
  shouldRefreshContentForTask = () => false,
  getActiveTaskId = () => '',
} = {}) {
  const calls = { hydrated: [], loaded: 0, applied: [], requests: [], timers: [] }
  const notices = []
  const tasks = ref(batchTasks)
  const taskIds = ref(batchTaskIds)
  const taskNames = ref({})
  const controller = useTaskQueueController({
    batchTasks: tasks,
    batchTaskIds: taskIds,
    batchTaskNames: taskNames,
    progressiveTaskSnapshots: new Map(),
    terminalStatuses: new Set(['succeeded', 'failed', 'cancelled']),
    shouldDisplayTask: () => true,
    isActiveTask: (task) => ['queued', 'running', 'paused'].includes(task?.status),
    shouldRefreshContentForTask,
    taskContentSnapshot: (task) => `${task.status}:${task.content_item_id || ''}`,
    hydrateProgressiveTask: async (task, snapshot) => calls.hydrated.push([task, snapshot]),
    loadContentItems: async () => { calls.loaded += 1 },
    isActiveContentTask: () => false,
    shouldContinueBatchPolling,
    getActiveTaskId,
    applyTaskData: (task) => calls.applied.push(task),
    notify: {
      success: (message) => notices.push(['success', message]),
      warning: (message) => notices.push(['warning', message]),
      info: (message) => notices.push(['info', message]),
      error: (message) => notices.push(['error', message]),
    },
    request: {
      get: async (...args) => {
        calls.requests.push(['get', ...args])
        return { data: [] }
      },
      post: async (...args) => {
        calls.requests.push(['post', ...args])
        return { data: {} }
      },
      ...request,
    },
    apiBase: 'http://api.test',
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      calls.timers.push(timer)
      return timer
    },
  })
  return { controller, calls, notices, tasks, taskIds, taskNames }
}

test('keeps already-loaded task details when a compact queue update arrives', () => {
  const { controller, tasks, taskIds } = createController({
    batchTaskIds: ['task-1'],
    batchTasks: [{
      task_id: 'task-1',
      status: 'running',
      detail_updated_at: 'previous',
      logs: [{ message: 'kept' }],
      transcript: 'kept transcript',
    }],
  })

  controller.mergeBatchTasks([{
    task_id: 'task-1',
    status: 'running',
    details_included: false,
    updated_at: 'current',
  }])

  assert.deepEqual(taskIds.value, ['task-1'])
  assert.equal(tasks.value[0].transcript, 'kept transcript')
  assert.deepEqual(tasks.value[0].logs, [{ message: 'kept' }])
  assert.equal(tasks.value[0].details_included, false)
})

test('does not hydrate historical completed tasks during the first queue snapshot', async () => {
  const historical = { task_id: 'done', status: 'succeeded', content_item_id: 'old' }
  const active = { task_id: 'active', status: 'running', content_item_id: 'current' }
  const { controller, calls, taskIds } = createController({
    request: { get: async () => ({ data: [historical, active] }) },
  })

  await controller.loadTaskQueue()

  assert.deepEqual(taskIds.value, ['done', 'active'])
  assert.deepEqual(calls.hydrated.map(([task]) => task.task_id), ['active'])
})

test('refreshes content for a terminal queue transition and schedules streaming summaries quickly', async () => {
  const previous = { task_id: 'task-1', status: 'running', content_item_id: 'content-1' }
  const completed = { task_id: 'task-1', status: 'succeeded', content_item_id: 'content-1' }
  const { controller, calls } = createController({
    batchTaskIds: ['task-1'],
    batchTasks: [previous],
    request: { get: async () => ({ data: [completed] }) },
  })

  await controller.pollBatchTasks()

  assert.deepEqual(calls.hydrated.map(([task]) => task.task_id), ['task-1'])
  assert.equal(calls.loaded, 2)

  const running = { task_id: 'task-1', status: 'running', progress: { summarize: 50 } }
  const scheduled = createController({
    batchTaskIds: ['task-1'],
    batchTasks: [running],
    shouldContinueBatchPolling: () => true,
    request: { get: async () => ({ data: [running] }) },
  })
  await scheduled.controller.pollBatchTasks()
  assert.deepEqual(scheduled.calls.timers.map((timer) => timer.delay), [320])
})

test('cancelling the active task preserves the endpoint, active result update, and queue refresh', async () => {
  const cancelled = { task_id: 'task-1', status: 'cancelled' }
  const { controller, calls, notices } = createController({
    batchTaskIds: ['task-1'],
    batchTasks: [{ task_id: 'task-1', status: 'running' }],
    getActiveTaskId: () => 'task-1',
    request: {
      post: async (...args) => {
        calls.requests.push(['post', ...args])
        return { data: cancelled }
      },
      get: async (...args) => {
        calls.requests.push(['get', ...args])
        return { data: [] }
      },
    },
  })

  await controller.cancelBatchTask({ task_id: 'task-1' })

  assert.deepEqual(calls.requests[0], ['post', 'http://api.test/tasks/task-1/cancel', {}, { timeout: 10000 }])
  assert.deepEqual(calls.applied, [cancelled])
  assert.deepEqual(notices, [['warning', '已请求取消']])
})
