import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useCreatorSyncTaskMonitorController } from './useCreatorSyncTaskMonitorController.js'

function createController({ items = [], request } = {}) {
  const calls = {
    loads: 0,
    opened: [],
    requests: [],
    merged: [],
    resets: 0,
    applied: [],
    logs: [],
    polled: [],
    batchPolls: 0,
    errors: [],
  }
  const batchTaskIds = ref(['existing'])
  const batchTaskNames = ref({})
  const running = ref(false)
  const controller = useCreatorSyncTaskMonitorController({
    allContentItems: ref(items),
    batchTaskIds,
    batchTaskNames,
    running,
    terminalStatuses: new Set(['succeeded', 'failed', 'cancelled']),
    loadContentItems: async () => { calls.loads += 1 },
    openContentTab: async (item) => { calls.opened.push(item) },
    mergeBatchTasks: (tasks) => { calls.merged.push(tasks) },
    resetRunState: () => { calls.resets += 1 },
    applyTaskData: (task) => { calls.applied.push(task) },
    addLog: (...args) => { calls.logs.push(args) },
    batchTaskName: (task) => batchTaskNames.value[task.task_id] || `任务 ${task.task_id}`,
    pollTask: (taskId) => { calls.polled.push(taskId) },
    pollBatchTasks: async () => { calls.batchPolls += 1 },
    request: request || {
      async get(...args) {
        calls.requests.push(args)
        return { data: [] }
      },
    },
    apiBase: '/api',
    notify: { error: (message) => calls.errors.push(message) },
  })
  return { controller, calls, batchTaskIds, batchTaskNames, running }
}

test('refreshes and opens the matching content item even when no task was created', async () => {
  const item = { id: 'content-2', title: '新资料' }
  const harness = createController({ items: [{ id: 'content-1' }, item] })

  await harness.controller.monitorCreatorSyncTasks({ contentItemIds: ['content-2'] })

  assert.equal(harness.calls.loads, 1)
  assert.deepEqual(harness.calls.opened, [item])
  assert.deepEqual(harness.calls.requests, [])
  assert.equal(harness.calls.batchPolls, 0)
})

test('keeps requested task order, registers names and activates the first running task', async () => {
  const first = { task_id: 'task-2', status: 'running', display_title: '第二个任务' }
  const second = { task_id: 'task-1', status: 'queued', source_title: '第一个任务' }
  const harness = createController({
    request: {
      async get(...args) {
        harness.calls.requests.push(args)
        return { data: [second, first] }
      },
    },
  })

  await harness.controller.monitorCreatorSyncTasks({ taskIds: ['task-2', 'task-1', 'task-2'] })

  assert.deepEqual(harness.calls.requests, [[
    '/api/tasks',
    { params: { task_ids: 'task-2,task-1' }, timeout: 10000 },
  ]])
  assert.deepEqual(harness.batchTaskIds.value, ['existing', 'task-2', 'task-1'])
  assert.deepEqual(harness.batchTaskNames.value, {
    'task-2': '第二个任务',
    'task-1': '第一个任务',
  })
  assert.deepEqual(harness.calls.merged, [[first, second]])
  assert.equal(harness.calls.resets, 1)
  assert.equal(harness.running.value, true)
  assert.deepEqual(harness.calls.applied, [first])
  assert.deepEqual(harness.calls.logs, [['创作者同步已加入处理队列：第二个任务', 'info']])
  assert.deepEqual(harness.calls.polled, ['task-2'])
  assert.equal(harness.calls.batchPolls, 1)
})

test('projects a terminal first task without starting single-task polling', async () => {
  const task = { task_id: 'done', status: 'succeeded', url: 'https://creator.test/video' }
  const harness = createController({ request: { async get() { return { data: [task] } } } })
  harness.running.value = true

  await harness.controller.monitorCreatorSyncTasks({ taskIds: ['done'] })

  assert.equal(harness.running.value, false)
  assert.deepEqual(harness.calls.applied, [task])
  assert.deepEqual(harness.calls.polled, [])
  assert.equal(harness.calls.batchPolls, 1)
})

test('reports a request failure without mutating the active task projection', async () => {
  const harness = createController({
    request: {
      async get() {
        throw { response: { data: { detail: '任务读取失败' } } }
      },
    },
  })

  await harness.controller.monitorCreatorSyncTasks({ taskIds: ['missing'] })

  assert.deepEqual(harness.calls.errors, ['任务读取失败'])
  assert.equal(harness.calls.resets, 0)
  assert.deepEqual(harness.calls.merged, [])
  assert.equal(harness.calls.batchPolls, 0)
})
