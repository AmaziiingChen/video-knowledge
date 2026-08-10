import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'

import { useProcessLogProjectionController } from './useProcessLogProjectionController.js'

function createController({
  logs = [],
  clearedAt = 0,
  result = {},
  statusDetail = '',
  tasks = [],
} = {}) {
  return useProcessLogProjectionController({
    logs: ref(logs),
    logClearedAt: ref(clearedAt),
    result: reactive(result),
    statusbarProgress: ref({ detail: statusDetail }),
    batchTasks: ref(tasks),
    batchTaskName: (task) => task.display_title || `任务 ${task.task_id}`,
    formatProcessLogTime: (value) => `time:${value || 'missing'}`,
    logTypeFromMessage: (message) => String(message).includes('失败') ? 'error' : 'info',
    now: () => 9000,
  })
}

test('filters cleared local logs and fills their task identity from the active runner', () => {
  const controller = createController({
    clearedAt: 100,
    result: { task_id: 'active-1', url: 'https://source.test' },
    statusDetail: '当前资料',
    logs: [
      { timestamp: 99, msg: 'old' },
      { timestamp: 100, msg: 'boundary' },
      { timestamp: 101, msg: 'new', task_id: 'explicit', task_name: '显式名称' },
    ],
  })
  assert.deepEqual(controller.processLogEntries.value, [
    { timestamp: 100, msg: 'boundary', task_id: 'active-1', task_name: '当前资料' },
    { timestamp: 101, msg: 'new', task_id: 'explicit', task_name: '显式名称' },
  ])
})

test('adds valid AI token totals only to the latest log of each queue task', () => {
  const controller = createController({
    tasks: [{
      task_id: 'task-1',
      display_title: '资料处理',
      status: 'running',
      step: 'summarize',
      overall_progress: 70,
      logs: [
        { created_at: '2026-08-10T10:00:00Z', message: '开始' },
        { created_at: '2026-08-10T10:00:01Z', message: '完成', elapsed_seconds: 1 },
      ],
      ai_calls: [
        { prompt_tokens: 10, completion_tokens: 4 },
        { prompt_tokens: '6', completion_tokens: '2' },
        { prompt_tokens: null, completion_tokens: 99 },
        { prompt_tokens: 'invalid', completion_tokens: 1 },
      ],
    }],
  })
  const [first, latest] = controller.processLogEntries.value
  assert.equal(first.total_tokens, null)
  assert.equal(latest.prompt_tokens, 16)
  assert.equal(latest.completion_tokens, 6)
  assert.equal(latest.total_tokens, 22)
  assert.equal(latest.task_name, '资料处理')
  assert.equal(latest.elapsed_seconds, 1)
})

test('projects persistence failures with deterministic fallback time and respects clear boundaries', () => {
  const visible = createController({
    clearedAt: 8000,
    tasks: [{ task_id: 'task-1', persistence_error: '磁盘只读', status: 'succeeded' }],
  })
  assert.deepEqual(visible.processLogEntries.value, [{
    time: 'time:missing',
    msg: '本地保存失败：磁盘只读',
    type: 'error',
    step: null,
    timestamp: 9000,
    task_id: 'task-1',
    task_name: '任务 task-1',
    task_status: 'succeeded',
    task_progress: undefined,
  }])

  const hidden = createController({
    clearedAt: 9000,
    tasks: [{ task_id: 'task-1', persistence_error: '磁盘只读' }],
  })
  assert.deepEqual(hidden.processLogEntries.value, [])
})

test('deduplicates equal task events while retaining chronological order', () => {
  const duplicate = {
    timestamp: 200,
    task_id: 'task-1',
    step: 'save',
    msg: '完成',
    elapsed_seconds: 2,
  }
  const controller = createController({
    logs: [
      { timestamp: 300, task_id: 'task-2', msg: 'later' },
      duplicate,
      { ...duplicate, type: 'success' },
    ],
  })
  assert.equal(controller.processLogEntries.value.length, 2)
  assert.equal(controller.processLogEntries.value[0].type, 'success')
  assert.equal(controller.processLogEntries.value[1].task_id, 'task-2')
})
