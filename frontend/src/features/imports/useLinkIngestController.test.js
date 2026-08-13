import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'

import { useLinkIngestController } from './useLinkIngestController.js'

function deferred() {
  let resolve
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function createController({ request } = {}) {
  const calls = {
    reset: 0,
    applied: [],
    logs: [],
    backendLogs: [],
    telemetry: [],
    registered: [],
    hydrated: [],
    polled: [],
    notices: [],
    schedules: [],
    cancelled: [],
    requests: [],
  }
  const result = reactive({ task_id: null, url: null, platform: null, timings: {} })
  const activeStep = ref(0)
  const running = ref(false)
  const openSections = ref(['source'])
  const controller = useLinkIngestController({
    result,
    activeStep,
    running,
    openSections,
    useCache: ref(true),
    resetRunState: () => {
      calls.reset += 1
      result.task_id = null
    },
    applyTaskData: (task) => {
      calls.applied.push(task)
      result.task_id = task.task_id || null
    },
    addLog: (...args) => calls.logs.push(args),
    addBackendLogs: (...args) => calls.backendLogs.push(args),
    recordTelemetry: (...args) => calls.telemetry.push(args),
    registerBatchTask: (...args) => calls.registered.push(args),
    hydrateProgressiveTask: async (...args) => calls.hydrated.push(args),
    getProgressiveSnapshot: () => 'previous',
    pollTask: (taskId) => calls.polled.push(taskId),
    getAsrRequestOptions: () => ({ asr_backend: 'auto' }),
    getAiRequestOptions: () => ({ ai_model: 'model-a' }),
    request: request || {
      async post(...args) {
        calls.requests.push(args)
        return { data: { success: false } }
      },
    },
    apiBase: '/api',
    notify: {
      warning: (message) => calls.notices.push(['warning', message]),
      error: (message) => calls.notices.push(['error', message]),
    },
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      calls.schedules.push(timer)
      return timer
    },
    cancel: (timer) => calls.cancelled.push(timer),
  })
  return { controller, calls, result, activeStep, running, openSections }
}

test('debounces parsing, applies only the current input, and cancels pending work', async () => {
  const first = deferred()
  const second = deferred()
  let requestCount = 0
  const harness = createController({
    request: {
      post: () => {
        requestCount += 1
        return requestCount === 1 ? first.promise : second.promise
      },
    },
  })
  harness.controller.shareText.value = ' https://old.test '
  await harness.controller.onInputChange()
  assert.equal(harness.calls.schedules[0].delay, 260)
  harness.calls.schedules[0].callback()

  harness.controller.shareText.value = 'https://new.test'
  await harness.controller.onInputChange()
  harness.calls.schedules[1].callback()
  first.resolve({ data: { success: true, url: 'https://old.test', platform: 'old' } })
  second.resolve({ data: { success: true, url: 'https://new.test', platform: 'new' } })
  await Promise.all([first.promise, second.promise])
  await Promise.resolve()

  assert.deepEqual(harness.controller.parsedUrl.value, {
    url: 'https://new.test',
    platform: 'new',
  })
  assert.equal(harness.result.url, 'https://new.test')
  assert.equal(harness.activeStep.value, 1)

  harness.controller.shareText.value = 'pending'
  await harness.controller.onInputChange()
  harness.controller.dispose()
  assert.deepEqual(harness.calls.cancelled, [harness.calls.schedules[2]])
})

test('submits the established link payload and registers one durable task', async () => {
  const task = { task_id: 'task-1', status: 'queued', source_title: '来源标题' }
  const harness = createController({
    request: {
      async post(...args) {
        harness.calls.requests.push(args)
        return { data: { task, item: { title: '条目标题' } } }
      },
    },
  })
  harness.controller.shareText.value = '  https://example.test/video  '

  await harness.controller.runFullPipeline()

  assert.deepEqual(harness.calls.requests, [[
    '/api/ingest/link',
    {
      text: 'https://example.test/video',
      mode: 'process',
      asr_backend: 'auto',
      ai_model: 'model-a',
      use_cache: true,
    },
    { timeout: 10000 },
  ]])
  assert.equal(harness.calls.reset, 1)
  assert.equal(harness.running.value, true)
  assert.deepEqual(harness.calls.applied, [task])
  assert.deepEqual(harness.calls.registered, [[task, { title: '条目标题' }]])
  assert.deepEqual(harness.calls.hydrated, [[task, 'previous']])
  assert.deepEqual(harness.calls.polled, ['task-1'])
  assert.deepEqual(harness.calls.telemetry, [
    ['import_started', { input_kind: 'link' }],
    ['import_completed', { result: 'accepted' }],
  ])
  assert.deepEqual(harness.calls.logs, [
    ['提交任务…', 'info'],
    ['任务已创建: task-1', 'success'],
  ])
  assert.equal(harness.controller.shareText.value, '')
  assert.equal(harness.controller.parsedUrl.value, null)
})

test('preserves structured backend failure details and releases a rejected run', async () => {
  const detail = {
    error: '解析失败',
    logs: [{ message: '后端日志' }],
    timings: { parse: 2 },
  }
  const harness = createController({
    request: {
      async post() {
        throw { response: { data: { detail } } }
      },
    },
  })
  harness.controller.shareText.value = 'https://example.test'

  await harness.controller.runFullPipeline()

  assert.equal(harness.running.value, false)
  assert.deepEqual(harness.calls.backendLogs, [[detail.logs]])
  assert.deepEqual(harness.result.timings, { parse: 2 })
  assert.deepEqual(harness.calls.logs.at(-1), ['失败: 解析失败', 'error'])
  assert.deepEqual(harness.openSections.value, ['logs'])
  assert.deepEqual(harness.calls.notices, [['error', '解析失败']])
})

test('rejects an empty input before resetting or requesting', async () => {
  const harness = createController()
  harness.controller.shareText.value = '   '

  await harness.controller.runFullPipeline()

  assert.equal(harness.calls.reset, 0)
  assert.deepEqual(harness.calls.requests, [])
  assert.deepEqual(harness.calls.notices, [['warning', '请输入链接']])
})
