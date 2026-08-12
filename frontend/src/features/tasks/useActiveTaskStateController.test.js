import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useActiveTaskStateController } from './useActiveTaskStateController.js'

function createController() {
  const calls = {
    stopped: 0,
    clearedBackendLogs: 0,
    resetQa: 0,
    backendLogs: [],
    logs: [],
  }
  const logs = ref([{ msg: '旧日志' }])
  const backendLogCount = ref(3)
  const openSections = ref(['logs'])
  const controller = useActiveTaskStateController({
    logs,
    backendLogCount,
    openSections,
    stopPolling: () => { calls.stopped += 1 },
    clearBackendLogCounts: () => { calls.clearedBackendLogs += 1 },
    resetQaState: () => { calls.resetQa += 1 },
    addBackendLogs: (...args) => calls.backendLogs.push(args),
    addLog: (...args) => calls.logs.push(args),
  })
  return { controller, calls, logs, backendLogCount, openSections }
}

test('reset restores the complete idle projection and releases task-owned state', () => {
  const harness = createController()
  const { controller } = harness
  controller.running.value = true
  controller.cancelling.value = true
  controller.activeStep.value = 4
  controller.currentStep.value = 'transcribe'
  controller.taskStatus.value = 'running'
  controller.taskCancelRequested.value = true
  Object.assign(controller.result, {
    task_id: 'task-1',
    content_item_id: 'content-1',
    summary: '摘要',
    reasoning_content: '思考',
    reasoning_truncated: true,
    suggested_questions: ['接下来呢？'],
    ai_calls: [{ id: 1 }],
    timings: { total: 2 },
    overall_progress: 80,
  })

  controller.resetRunState()

  assert.equal(controller.running.value, false)
  assert.equal(controller.cancelling.value, false)
  assert.equal(controller.activeStep.value, 0)
  assert.equal(controller.currentStep.value, null)
  assert.equal(controller.taskStatus.value, 'idle')
  assert.equal(controller.taskCancelRequested.value, false)
  assert.equal(controller.result.task_id, null)
  assert.equal(controller.result.content_item_id, null)
  assert.equal(controller.result.summary, null)
  assert.equal(controller.result.reasoning_content, '')
  assert.equal(controller.result.reasoning_truncated, false)
  assert.deepEqual(controller.result.suggested_questions, [])
  assert.deepEqual(controller.result.ai_calls, [])
  assert.deepEqual(controller.result.timings, {})
  assert.equal(controller.result.overall_progress, 0)
  assert.deepEqual(harness.logs.value, [])
  assert.equal(harness.backendLogCount.value, 0)
  assert.deepEqual(harness.openSections.value, ['source', 'timings'])
  assert.deepEqual(harness.calls, {
    stopped: 1,
    clearedBackendLogs: 1,
    resetQa: 1,
    backendLogs: [],
    logs: [],
  })
})

test('applies a backend snapshot, forwards logs, and advances the visible step', () => {
  const harness = createController()
  const data = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
    step: 'transcribe',
    url: 'https://example.test/video',
    platform: 'bilibili',
    transcript: '正文',
    summary: '摘要',
    reasoning_content: '思考',
    reasoning_truncated: true,
    suggested_questions: ['问题一？', '问题二？', '问题三？', '问题四？'],
    display_title: '显示标题',
    source_title: '来源标题',
    logs: [{ message: '处理中' }],
    timings: { download: 1 },
    progress: { transcribe: 40 },
    overall_progress: 42.5,
    ai_calls: [{ model: 'test' }],
    cache_hits: ['metadata'],
    cancel_requested: true,
  }

  harness.controller.applyTaskData(data)

  assert.equal(harness.controller.result.task_id, 'task-1')
  assert.equal(harness.controller.result.content_item_id, 'content-1')
  assert.equal(harness.controller.result.url, 'https://example.test/video')
  assert.equal(harness.controller.result.transcript, '正文')
  assert.equal(harness.controller.result.reasoning_content, '思考')
  assert.equal(harness.controller.result.reasoning_truncated, true)
  assert.deepEqual(harness.controller.result.suggested_questions, ['问题一？', '问题二？', '问题三？'])
  assert.equal(harness.controller.result.overall_progress, 42.5)
  assert.deepEqual(harness.controller.result.progress, { transcribe: 40 })
  assert.equal(harness.controller.taskStatus.value, 'running')
  assert.equal(harness.controller.taskCancelRequested.value, true)
  assert.equal(harness.controller.currentStep.value, 'transcribe')
  assert.equal(harness.controller.activeStep.value, 4)
  assert.deepEqual(harness.calls.backendLogs, [[data.logs, data]])
})

test('resets QA on task identity changes and reports each new persistence error once', () => {
  const harness = createController()
  harness.controller.applyTaskData({ task_id: 'old', status: 'running', step: 'download' })
  harness.controller.applyTaskData({
    task_id: 'new',
    status: 'running',
    step: 'save',
    display_title: '新任务',
    persistence_error: '数据库繁忙',
    overall_progress: 99,
  })
  harness.controller.applyTaskData({
    task_id: 'new',
    status: 'succeeded',
    step: 'total',
    persistence_error: '数据库繁忙',
    overall_progress: 100,
  })

  assert.equal(harness.calls.resetQa, 1)
  assert.equal(harness.calls.logs.length, 1)
  assert.deepEqual(harness.calls.logs[0], [
    '本地保存失败：数据库繁忙',
    'error',
    'save',
    null,
    {
      task_id: 'new',
      task_name: '新任务',
      task_status: 'running',
      task_progress: 99,
    },
  ])
  assert.equal(harness.controller.taskStatus.value, 'succeeded')
  assert.equal(harness.controller.activeStep.value, 6)
})
