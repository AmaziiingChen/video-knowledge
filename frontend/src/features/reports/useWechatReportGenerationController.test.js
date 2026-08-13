import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatReportGenerationController } from './useWechatReportGenerationController.js'

async function flush() {
  await Promise.resolve()
  await Promise.resolve()
}

function createController({ post, consumeStream } = {}) {
  const calls = { logs: [], notices: [], refreshContent: 0, refreshFolders: 0, refreshUsage: 0 }
  const controller = useWechatReportGenerationController({
    reportGroups: ref([{ id: 'group-1', name: '校园组' }]),
    reportGroupApi: '/api/wechat-report-groups',
    request: { post: post || (async () => ({ data: { group_name: '校园组' } })) },
    consumeStream: consumeStream || (async (_url, _payload, onProgress) => {
      onProgress({ message: '正在汇总', progress: 42, stage: 'report_write' })
      return { source_count: 3, ai_token_usage: { call_count: 2, total_tokens: 80 } }
    }),
    formatTaskWindow: () => '8/11 09:00–10:00',
    notify: {
      success: (message) => calls.notices.push(['success', message]),
      error: (message) => calls.notices.push(['error', message]),
    },
    addLog: (...entry) => calls.logs.push(entry),
    processLogOpen: ref(false),
    refreshContentItems: async () => { calls.refreshContent += 1 },
    refreshLibraryFolders: async () => { calls.refreshFolders += 1 },
    refreshAiTokenUsage: async () => { calls.refreshUsage += 1 },
    errorMessage: (error, fallback) => error?.message || fallback,
  })
  return { controller, calls }
}

test('runs preflight, confirmation, stream progress, and refreshes through one transaction', async () => {
  const streamCalls = []
  const { controller, calls } = createController({
    consumeStream: async (url, payload, onProgress) => {
      streamCalls.push({ url, payload })
      onProgress({ message: '正在汇总', progress: 42, stage: 'report_write' })
      return { source_count: 3, ai_token_usage: { call_count: 2, total_tokens: 80 } }
    },
  })

  const running = controller.generateWeChatReport('group-1', 'range', {
    windowStart: '2026-08-11T09:00:00+08:00',
    windowEnd: '2026-08-11T10:00:00+08:00',
    includeExternalImports: true,
  })
  await flush()

  assert.equal(controller.wechatPreparingGroupId.value, 'group-1:range')
  assert.equal(controller.reportGenerationDialog.value.phase, 'ready')
  controller.confirmReportGenerationDialog()
  await running

  assert.deepEqual(streamCalls, [{
    url: '/api/wechat-report-groups/group-1/generate-stream',
    payload: {
      report_type: 'range',
      window_start: '2026-08-11T09:00:00+08:00',
      window_end: '2026-08-11T10:00:00+08:00',
      include_history_context: true,
      include_external_imports: true,
    },
  }])
  assert.equal(controller.wechatPreparingGroupId.value, '')
  assert.equal(controller.wechatGeneratingGroupId.value, '')
  assert.equal(controller.reportGenerationDialog.value.visible, false)
  assert.deepEqual(calls.notices, [['success', '已生成区间报告，共汇总 3 篇文章']])
  assert.equal(calls.refreshContent, 1)
  assert.equal(calls.refreshFolders, 1)
  assert.equal(calls.refreshUsage, 1)
  assert.equal(calls.logs.at(-1)[1], 'success')
})

test('cancel aborts an in-flight preflight and releases its busy state', async () => {
  let signal
  const { controller, calls } = createController({
    post: (_url, _payload, options) => new Promise((_resolve, reject) => {
      signal = options.signal
      signal.addEventListener('abort', () => {
        const error = new Error('canceled')
        error.code = 'ERR_CANCELED'
        reject(error)
      })
    }),
  })

  const running = controller.generateWeChatReport('group-1', 'daily')
  await flush()
  controller.cancelReportGenerationDialog()
  await running

  assert.equal(signal.aborted, true)
  assert.equal(controller.wechatPreparingGroupId.value, '')
  assert.equal(controller.wechatGeneratingGroupId.value, '')
  assert.equal(controller.reportGenerationDialog.value.visible, false)
  assert.deepEqual(calls.notices, [])
})

test('rejects a duplicate generation while a preflight is pending', async () => {
  let resolvePreflight
  const post = () => new Promise((resolve) => { resolvePreflight = resolve })
  const { controller } = createController({ post })

  const first = controller.generateWeChatReport('group-1', 'daily')
  await flush()
  const duplicate = await controller.generateWeChatReport('group-1', 'weekly')

  assert.equal(duplicate, undefined)
  assert.equal(controller.wechatPreparingGroupId.value, 'group-1:daily')
  controller.cancelReportGenerationDialog()
  resolvePreflight?.({ data: {} })
  await first
})

test('reports a preflight failure and always releases the preparing state', async () => {
  const { controller, calls } = createController({
    post: async () => { throw new Error('预检不可用') },
  })

  await controller.generateWeChatReport('group-1', 'weekly')

  assert.equal(controller.wechatPreparingGroupId.value, '')
  assert.equal(controller.reportGenerationDialog.value.visible, false)
  assert.deepEqual(calls.notices, [['error', '预检不可用']])
})
