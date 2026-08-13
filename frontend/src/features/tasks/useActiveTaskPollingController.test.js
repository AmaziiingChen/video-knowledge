import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useActiveTaskPollingController } from './useActiveTaskPollingController.js'

function createController({
  responses = [],
  isPipelineSummaryGenerating = () => false,
} = {}) {
  const calls = {
    applied: [],
    streamsStarted: [],
    streamsStopped: 0,
    hydrated: [],
    articleSnapshots: [],
    videoSnapshots: [],
    transcriptSnapshots: [],
    completedContent: [],
    logs: [],
    notices: [],
    schedules: [],
    cancelledTimers: [],
  }
  const running = ref(true)
  const cancelling = ref(false)
  const openSections = ref(['source'])
  const queue = [...responses]
  const controller = useActiveTaskPollingController({
    running,
    cancelling,
    openSections,
    progressiveTaskSnapshots: new Map([['task-1', 'previous']]),
    terminalStatuses: new Set(['succeeded', 'failed', 'cancelled']),
    applyTaskData: (task) => calls.applied.push(task),
    startTaskEventStream: (taskId) => calls.streamsStarted.push(taskId),
    stopTaskEventStream: () => { calls.streamsStopped += 1 },
    hydrateProgressiveTask: async (...args) => calls.hydrated.push(args),
    revealWechatArticleSnapshot: async (task) => calls.articleSnapshots.push(task),
    revealVideoSnapshot: async (task) => calls.videoSnapshots.push(task),
    revealTranscriptSnapshot: async (task) => calls.transcriptSnapshots.push(task),
    syncCompletedTaskContent: async (contentItemId) => calls.completedContent.push(contentItemId),
    addLog: (...args) => calls.logs.push(args),
    isPipelineSummaryGenerating,
    request: {
      async get() {
        const next = queue.shift()
        if (next instanceof Error) throw next
        return { data: next }
      },
    },
    apiBase: '/api',
    notify: {
      success: (message) => calls.notices.push(['success', message]),
      warning: (message) => calls.notices.push(['warning', message]),
      error: (message) => calls.notices.push(['error', message]),
    },
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      calls.schedules.push(timer)
      return timer
    },
    cancel: (timer) => calls.cancelledTimers.push(timer),
  })
  return { controller, calls, running, cancelling, openSections }
}

test('hydrates a running task and preserves the fast summary polling cadence', async () => {
  const runningTask = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
  }
  const harness = createController({
    responses: [runningTask],
    isPipelineSummaryGenerating: () => true,
  })

  await harness.controller.pollTask('task-1')

  assert.deepEqual(harness.calls.applied, [runningTask])
  assert.deepEqual(harness.calls.streamsStarted, ['task-1'])
  assert.deepEqual(harness.calls.hydrated, [[runningTask, 'previous']])
  assert.deepEqual(harness.calls.articleSnapshots, [runningTask])
  assert.deepEqual(harness.calls.videoSnapshots, [runningTask])
  assert.deepEqual(harness.calls.transcriptSnapshots, [runningTask])
  assert.deepEqual(harness.calls.schedules.map(({ delay }) => delay), [220])
  assert.equal(harness.running.value, true)
})

test('completes a successful task and reports a persistence failure without hiding content', async () => {
  const completedTask = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'succeeded',
    persistence_error: 'database busy',
  }
  const harness = createController({ responses: [completedTask] })
  harness.cancelling.value = true

  await harness.controller.pollTask('task-1')

  assert.equal(harness.running.value, false)
  assert.equal(harness.cancelling.value, false)
  assert.equal(harness.calls.streamsStopped, 1)
  assert.deepEqual(harness.calls.completedContent, ['content-1'])
  assert.deepEqual(harness.calls.logs, [[
    '处理结果已生成，但任务状态未能保存；重启后任务记录可能不完整',
    'error',
  ]])
  assert.deepEqual(harness.openSections.value, ['logs'])
  assert.deepEqual(harness.calls.notices, [['error', '处理已完成，但任务状态未保存']])
  assert.deepEqual(harness.calls.schedules, [])
})

test('keeps cancelled and failed terminal feedback distinct', async () => {
  const cancelled = createController({
    responses: [{ task_id: 'task-1', status: 'cancelled' }],
  })
  await cancelled.controller.pollTask('task-1')
  assert.deepEqual(cancelled.calls.logs, [['任务已取消', 'warn']])
  assert.deepEqual(cancelled.calls.notices, [['warning', '任务已取消']])

  const failed = createController({
    responses: [{ task_id: 'task-1', status: 'failed', error: '转写失败' }],
  })
  await failed.controller.pollTask('task-1')
  assert.deepEqual(failed.calls.logs, [['失败: 转写失败', 'error']])
  assert.deepEqual(failed.calls.notices, [['error', '转写失败']])
})

test('backs off repeated request failures and resets timers on stop', async () => {
  const harness = createController({
    responses: Array.from({ length: 5 }, () => new Error('offline')),
  })

  for (let attempt = 0; attempt < 5; attempt += 1) {
    await harness.controller.pollTask('task-1')
  }

  assert.deepEqual(harness.calls.schedules.map(({ delay }) => delay), [1500, 3000, 4500, 6000, 7500])
  assert.deepEqual(harness.calls.logs, [
    ['任务状态暂时不可达：offline；2 秒后重试', 'warn'],
    ['任务状态暂时不可达：offline；8 秒后重试', 'warn'],
  ])
  harness.controller.stopPolling()
  assert.deepEqual(harness.calls.cancelledTimers, [harness.calls.schedules.at(-1)])
  assert.equal(harness.calls.streamsStopped, 1)
})
