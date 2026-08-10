import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { REPORT_LOG_HISTORY_KEY } from './processLogHistory.js'
import { useProcessLogController } from './useProcessLogController.js'

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

function createController({ storage = memoryStorage(), now = () => 500 } = {}) {
  const batchTasks = ref([
    { task_id: 'active', status: 'running' },
    { task_id: 'done', status: 'succeeded' },
  ])
  const batchTaskIds = ref(['active', 'done'])
  const cursors = []
  const deferred = []
  const result = { task_id: 'active', overall_progress: 42 }
  const controller = useProcessLogController({
    batchTasks,
    batchTaskIds,
    getResult: () => result,
    getTaskStatus: () => 'running',
    isActiveTask: (task) => task.status === 'running',
    logTypeFromMessage: (message) => message.includes('失败') ? 'error' : 'info',
    resetTaskQueueCursor: (cursor) => cursors.push(cursor),
    storage,
    now,
    defer: (callback) => deferred.push(callback),
  })
  return { controller, batchTasks, batchTaskIds, cursors, deferred, result, storage }
}

test('restores report logs and marks an unfinished report as interrupted', () => {
  const storage = memoryStorage({
    [REPORT_LOG_HISTORY_KEY]: JSON.stringify([{
      task_id: 'report:daily:1',
      task_name: '日报',
      task_status: 'running',
      task_progress: 60,
      msg: '生成中',
      timestamp: 100,
    }]),
  })
  const { controller } = createController({ storage, now: () => 500 })

  assert.equal(controller.logs.value.length, 2)
  assert.equal(controller.logs.value.at(-1).task_status, 'failed')
  assert.equal(controller.logs.value.at(-1).msg.includes('任务已中断'), true)
  assert.equal(JSON.parse(storage.getItem(REPORT_LOG_HISTORY_KEY)).length, 2)
})

test('adds bounded report history and scrolls the attached log container', () => {
  const harness = createController()
  harness.controller.logContainer.value = { scrollTop: 0, scrollHeight: 240 }

  harness.controller.addLog('报告完成', 'success', 'report_save', null, {
    task_id: 'report:daily:1',
    task_status: 'succeeded',
    timestamp: 300,
  })

  assert.equal(harness.controller.logs.value[0].msg, '报告完成')
  assert.equal(JSON.parse(harness.storage.getItem(REPORT_LOG_HISTORY_KEY)).length, 1)
  harness.deferred[0]()
  assert.equal(harness.controller.logContainer.value.scrollTop, 240)
})

test('ingests only new backend logs and preserves task context', () => {
  const harness = createController()
  const first = { message: '开始', created_at: '2026-01-01T00:00:01Z' }
  const second = { message: '失败一次', level: 'warn', step: 'download', created_at: '2026-01-01T00:00:02Z' }
  const task = {
    task_id: 'active',
    display_title: '测试任务',
    status: 'running',
    overall_progress: 40,
  }

  harness.controller.addBackendLogs([first], task)
  harness.controller.addBackendLogs([first, second], task)

  assert.equal(harness.controller.logs.value.length, 2)
  assert.equal(harness.controller.logs.value[1].msg, '失败一次')
  assert.equal(harness.controller.logs.value[1].task_name, '测试任务')
  assert.equal(harness.controller.logs.value[1].task_progress, 40)
  assert.equal(harness.controller.backendLogCount.value, 2)
})

test('clear removes persisted logs, advances the queue cursor, and retains active tasks', () => {
  const harness = createController({ now: () => 1000 })
  harness.controller.addLog('报告日志', 'info', null, null, {
    task_id: 'report:daily:1',
    timestamp: 900,
  })

  harness.controller.clearLogs()

  assert.deepEqual(harness.controller.logs.value, [])
  assert.deepEqual(harness.batchTasks.value.map((task) => task.task_id), ['active'])
  assert.deepEqual(harness.batchTaskIds.value, ['active'])
  assert.deepEqual(harness.cursors, [new Date(1000).toISOString()])
  assert.equal(harness.controller.logClearedAt.value, 1000)
  assert.equal(harness.controller.backendLogCount.value, 0)
  assert.equal(harness.storage.getItem(REPORT_LOG_HISTORY_KEY), null)
})
