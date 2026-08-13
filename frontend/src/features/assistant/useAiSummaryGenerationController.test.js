import test from 'node:test'
import assert from 'node:assert/strict'

import { createQaResponseStreamController } from './createQaResponseStreamController.js'
import { useAiSummaryGenerationController } from './useAiSummaryGenerationController.js'

function streamResponse(blocks) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      blocks.forEach((block) => controller.enqueue(encoder.encode(block)))
      controller.close()
    },
  }))
}

function immediateRenderer({ onCommit }) {
  return {
    enqueue: (text) => onCommit(text),
    drain: () => Promise.resolve(),
    flush: () => {},
  }
}

function createSession() {
  return {
    asking: false,
    generatingSummary: false,
    generatingSummaryText: '',
    lastSaved: false,
    history: [],
  }
}

function notificationRecorder() {
  const messages = { warning: [], info: [], success: [], error: [] }
  return {
    messages,
    notify: {
      warning: (message) => messages.warning.push(message),
      info: (message) => messages.info.push(message),
      success: (message) => messages.success.push(message),
      error: (message) => messages.error.push(message),
    },
  }
}

function controllerHarness({ session = createSession(), item, ...overrides } = {}) {
  const fetchCalls = []
  const logCalls = []
  const logs = []
  const syncCalls = []
  const refreshCalls = []
  const scheduled = []
  const cancelled = []
  const { messages, notify } = notificationRecorder()
  const controller = useAiSummaryGenerationController({
    ensureQaSession: () => session,
    syncQaSessionIfActive: (...args) => syncCalls.push(args),
    refreshQaSessionHistory: (...args) => refreshCalls.push(args),
    readQaStream: async () => {},
    addLog: (...args) => {
      logCalls.push(args)
      logs.push({
        message: args[0],
        task_id: args[4]?.task_id,
        task_status: args[4]?.task_status,
      })
    },
    getActiveItem: () => item || { id: 'content-1', title: '内容标题', source_url: 'https://example.com/source' },
    getCurrentSummary: () => '',
    getAiModel: () => 'assistant-model',
    getLogs: () => logs,
    fetchRequest: async (...args) => {
      fetchCalls.push(args)
      return { ok: true }
    },
    apiBase: '/api',
    requestUrl: (url) => `protected:${url}`,
    authHeaders: async (headers) => ({ ...headers, 'X-Test-Token': 'token' }),
    schedule: (callback, delay) => {
      scheduled.push({ callback, delay })
      return 7
    },
    cancel: (timer) => cancelled.push(timer),
    now: () => 12345,
    timeLabel: () => '10:30:00',
    notify,
    ...overrides,
  })
  return {
    controller,
    fetchCalls,
    logCalls,
    logs,
    syncCalls,
    refreshCalls,
    scheduled,
    cancelled,
    messages,
    session,
  }
}

test('rejects missing, busy and already summarized content before network access', async () => {
  const missing = controllerHarness({ item: null, getActiveItem: () => null })
  await missing.controller.generateAiSummary()
  assert.deepEqual(missing.messages.warning, ['请先打开一篇公众号文章或一个已处理的视频'])

  const summarized = controllerHarness({ getCurrentSummary: () => '已有摘要' })
  await summarized.controller.generateAiSummary()
  assert.deepEqual(summarized.messages.info, ['当前内容已有 AI 摘要'])

  const busySession = createSession()
  busySession.asking = true
  const busy = controllerHarness({ session: busySession })
  await busy.controller.generateAiSummary()

  assert.equal(missing.fetchCalls.length, 0)
  assert.equal(summarized.fetchCalls.length, 0)
  assert.equal(busy.fetchCalls.length, 0)
})

test('streams a summary with the established request, progress logs and timer lifecycle', async () => {
  const session = createSession()
  const harness = controllerHarness({
    session,
    readQaStream: async (_response, pendingItem, contentItemId, options) => {
      assert.equal(contentItemId, 'content-1')
      assert.equal(options.session, session)
      harness.scheduled[0].callback()
      options.onFirstDelta()
      options.onFirstReasoning()
      options.onReasoning('摘要思考')
      options.onSuggestions(['继续理解？'])
      options.onLog({ message: '模型完成摘要', progress: 90, status: 'running' })
      options.onCommit('正在显示的摘要')
      pendingItem.answer = '最终摘要'
      pendingItem.pending = false
      pendingItem.savedToContent = true
    },
  })

  await harness.controller.generateAiSummary()

  assert.equal(harness.fetchCalls.length, 1)
  assert.equal(harness.fetchCalls[0][0], 'protected:/api/qa/stream')
  assert.deepEqual(harness.fetchCalls[0][1].headers, {
    'Content-Type': 'application/json',
    'X-Test-Token': 'token',
  })
  assert.deepEqual(JSON.parse(harness.fetchCalls[0][1].body), {
    question: '请基于当前内容的完整原文生成 AI 摘要。',
    display_question: '生成 AI 摘要',
    summary: '',
    transcript: '',
    video_title: '内容标题',
    source_url: 'https://example.com/source',
    content_item_id: 'content-1',
    obsidian_path: null,
    history: [],
    append_to_obsidian: false,
    ai_model: 'assistant-model',
    regenerate_summary: true,
  })
  assert.deepEqual(harness.scheduled.map(({ delay }) => delay), [15000])
  assert.deepEqual(harness.logCalls.map((call) => call[0]), [
    '开始生成 AI 摘要',
    'AI 服务仍在生成，最长等待约 90 秒',
    'AI 已开始返回总结内容',
    '模型完成摘要',
  ])
  assert.equal(harness.logCalls[0][4].task_id, 'manual:summary:content-1:12345')
  assert.deepEqual(harness.cancelled, [7, null])
  assert.equal(session.generatingSummaryText, '')
  assert.equal(session.generatingSummaryReasoning, '摘要思考')
  assert.equal(session.generatingSummaryReasoningExpanded, false)
  assert.deepEqual(session.suggestedQuestions, ['继续理解？'])
  assert.equal(session.asking, false)
  assert.equal(session.generatingSummary, false)
  assert.deepEqual(harness.messages.success, ['AI 摘要已保存到内容记录'])
})

test('projects reasoning from a real summary response stream into the summary session', async () => {
  const session = createSession()
  const responseController = createQaResponseStreamController({
    appendContentAiCall: () => {},
    getSelectedContentItem: () => ({ id: 'content-1' }),
    applyMarkdownState: () => {},
    refreshQaSessionHistory: () => {},
    refreshFallbackHistory: () => {},
    setLastQaSaved: () => {},
    createStreamRenderer: immediateRenderer,
  })
  const harness = controllerHarness({
    session,
    readQaStream: responseController.readQaStream,
    fetchRequest: async () => streamResponse([
      'event: reasoning_delta\ndata: {"text":"先检查资料"}\n\n',
      'event: delta\ndata: {"text":"摘要正文"}\n\n',
      'event: done\ndata: {"answer":"摘要正文","reasoning_content":"先检查资料","saved_to_content":true}\n\n',
    ]),
  })

  await harness.controller.generateAiSummary()

  assert.equal(session.generatingSummaryReasoning, '先检查资料')
  assert.equal(session.generatingSummaryReasoningExpanded, false)
  assert.equal(session.generatingSummaryText, '')
  assert.deepEqual(harness.messages.success, ['AI 摘要已保存到内容记录'])
})

test('clears transient summary state and writes one failed log after a server error', async () => {
  const session = createSession()
  session.generatingSummaryText = '旧的临时摘要'
  const harness = controllerHarness({
    session,
    fetchRequest: async () => ({
      ok: false,
      text: async () => JSON.stringify({ detail: '摘要模型不可用' }),
    }),
  })

  await harness.controller.generateAiSummary()

  assert.equal(session.generatingSummaryText, '')
  assert.equal(session.asking, false)
  assert.equal(session.generatingSummary, false)
  assert.equal(harness.refreshCalls.length, 1)
  assert.deepEqual(harness.logCalls.map((call) => call[0]), [
    '开始生成 AI 摘要',
    '生成 AI 摘要失败：摘要模型不可用',
  ])
  assert.equal(harness.logCalls[1][4].task_status, 'failed')
  assert.deepEqual(harness.cancelled, [7])
  assert.deepEqual(harness.messages.error, ['摘要模型不可用'])
})
