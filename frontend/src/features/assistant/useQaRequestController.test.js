import test from 'node:test'
import assert from 'node:assert/strict'

import { useQaRequestController } from './useQaRequestController.js'

function createSession(history = []) {
  return {
    draft: '',
    history,
    asking: false,
    generatingSummary: false,
    lastSaved: false,
  }
}

function notificationRecorder() {
  const messages = { warning: [], info: [], success: [], error: [], completion: [] }
  return {
    messages,
    notify: {
      warning: (message) => messages.warning.push(message),
      info: (message) => messages.info.push(message),
      success: (message) => messages.success.push(message),
      error: (message) => messages.error.push(message),
    },
    notifyCompletion: (options) => messages.completion.push(options),
  }
}

function controllerHarness({ session = createSession(), context = {}, ...overrides } = {}) {
  const fetchCalls = []
  const notificationCalls = []
  const syncCalls = []
  const historyRefreshes = []
  const { messages, notify, notifyCompletion } = notificationRecorder()
  const controller = useQaRequestController({
    ensureQaSession: () => session,
    syncQaSessionIfActive: (...args) => syncCalls.push(args),
    refreshQaSessionHistory: (...args) => historyRefreshes.push(args),
    resolveQaQuestion: (question) => ({ prompt: question, autoShortcutName: '' }),
    removeSelectedTextContextToken: (question) => question.replace('@选中文本', ''),
    readQaStream: async (_response, item) => {
      item.answer = '流式回答'
      item.pending = false
    },
    getRequestContext: () => ({
      contentItemId: 'content-1',
      summary: '已有摘要',
      transcript: '已有原文',
      videoTitle: '内容标题',
      sourceUrl: 'https://example.com/source',
      obsidianAutoWrite: false,
      obsidianPath: '',
      aiModel: 'assistant-model',
      ...context,
    }),
    getActiveContentId: () => 'content-1',
    fetchRequest: async (...args) => {
      fetchCalls.push(args)
      return { ok: true }
    },
    apiBase: '/api',
    requestUrl: (url) => `protected:${url}`,
    authHeaders: async (headers) => ({ ...headers, 'X-Test-Token': 'token' }),
    request: {
      async post(...args) {
        notificationCalls.push(args)
        return { data: {} }
      }
    },
    timeLabel: () => '10:30:00',
    now: () => 12345,
    notify,
    notifyCompletion,
    ...overrides,
  })
  return {
    controller,
    fetchCalls,
    notificationCalls,
    syncCalls,
    historyRefreshes,
    messages,
    session,
  }
}

test('submits selected text, bounded history and Obsidian options through the protected stream', async () => {
  const savedHistory = {
    id: 'answer-0',
    question: '上一问',
    answer: '上一答',
    pending: false,
    error: false,
  }
  const session = createSession([savedHistory])
  session.draft = '@选中文本 这是什么意思'
  const harness = controllerHarness({
    session,
    context: {
      selectionContext: { text: '第一行\n第二行' },
      obsidianAutoWrite: true,
      obsidianPath: '/vault/article.md',
    },
    resolveQaQuestion: () => ({ prompt: '合成后的问题', autoShortcutName: '术语' }),
    readQaStream: async (_response, item, contentItemId, options) => {
      assert.equal(contentItemId, 'content-1')
      assert.equal(options.session, session)
      item.answer = '已保存回答'
      item.pending = false
      item.savedToContent = true
    },
  })

  await harness.controller.askQuestion()

  assert.equal(harness.fetchCalls.length, 1)
  assert.equal(harness.fetchCalls[0][0], 'protected:/api/qa/stream')
  assert.deepEqual(harness.fetchCalls[0][1].headers, {
    'Content-Type': 'application/json',
    'X-Test-Token': 'token',
  })
  const body = JSON.parse(harness.fetchCalls[0][1].body)
  assert.deepEqual(body, {
    question: '【用户选中的原文】\n第一行\n第二行\n\n【用户的问题】\n合成后的问题',
    display_question: '@选中文本\n> 第一行\n> 第二行\n\n这是什么意思',
    summary: '已有摘要',
    transcript: '已有原文',
    video_title: '内容标题',
    source_url: 'https://example.com/source',
    content_item_id: 'content-1',
    obsidian_path: '/vault/article.md',
    history: [{ question: '上一问', answer: '上一答' }],
    append_to_obsidian: true,
    ai_model: 'assistant-model',
  })
  assert.equal(session.history.length, 2)
  assert.equal(session.history[1].selectedText, '第一行\n第二行')
  assert.equal(session.history[1].time, '10:30:00')
  assert.equal(session.draft, '')
  assert.equal(session.asking, false)
  assert.deepEqual(harness.messages.info, ['已按本地规则附加 @术语 追问指引'])
  assert.deepEqual(harness.messages.success, ['已保存到内容记录，可在重新打开时继续追问'])
  assert.equal(harness.notificationCalls.length, 0)
})

test('records a bounded completion notification after the user switches content', async () => {
  let completionReloads = 0
  const harness = controllerHarness({
    getActiveContentId: () => 'content-2',
    getVisibilityState: () => 'visible',
    loadCompletionNotifications: async () => {
      completionReloads += 1
    },
    readQaStream: async (_response, item) => {
      item.id = 'assistant-1'
      item.answer = '完成后的回答'
      item.pending = false
    },
  })

  await harness.controller.askQuestion('离开页面后完成的问题')

  assert.equal(harness.notificationCalls.length, 1)
  assert.deepEqual(harness.notificationCalls[0], [
    '/api/completion-notifications',
    {
      event_key: 'qa:content-1:assistant-1',
      event_type: 'assistant_response',
      title: '离开页面后完成的问题',
      body: '完成后的回答',
      content_item_id: 'content-1',
      target_view: 'library',
    },
    { timeout: 10000 },
  ])
  assert.equal(completionReloads, 1)
  assert.deepEqual(harness.messages.completion, [{
    title: '离开页面后完成的问题',
    message: '完成后的回答',
    duration: 6000,
  }])
})

test('reads dynamic content fields after desktop authentication resolves', async () => {
  const dynamicContext = {
    contentItemId: 'content-1',
    summary: '认证前摘要',
    transcript: '认证前原文',
    aiModel: 'assistant-model',
  }
  const harness = controllerHarness({
    getRequestContext: () => ({ ...dynamicContext }),
    authHeaders: async (headers) => {
      dynamicContext.summary = '认证后摘要'
      dynamicContext.transcript = '认证后原文'
      return headers
    },
  })

  await harness.controller.askQuestion('保持时序的问题')

  const body = JSON.parse(harness.fetchCalls[0][1].body)
  assert.equal(body.summary, '认证后摘要')
  assert.equal(body.transcript, '认证后原文')
})

test('uses a custom template without clearing the current draft', async () => {
  const session = createSession()
  session.draft = '用户尚未发送的草稿'
  const harness = controllerHarness({
    session,
    resolveQaQuestion: () => assert.fail('custom templates bypass shortcut composition'),
  })

  await harness.controller.askQuestion('', {
    customTemplate: { name: '证据检查', template: '逐项核对证据与结论。' },
  })

  const body = JSON.parse(harness.fetchCalls[0][1].body)
  assert.equal(body.question, '已选择的追问方式：\n证据检查\n逐项核对证据与结论。')
  assert.equal(body.display_question, '自定义按钮：证据检查')
  assert.equal(session.draft, '用户尚未发送的草稿')
})

test('marks a pending question as failed and releases the session after a server error', async () => {
  const harness = controllerHarness({
    fetchRequest: async () => ({
      ok: false,
      text: async () => JSON.stringify({ detail: '模型服务不可用' }),
    }),
  })

  await harness.controller.askQuestion('失败的问题')

  assert.equal(harness.session.history.length, 1)
  assert.equal(harness.session.history[0].pending, false)
  assert.equal(harness.session.history[0].error, true)
  assert.equal(harness.session.history[0].answer, '追问失败')
  assert.equal(harness.session.asking, false)
  assert.deepEqual(harness.messages.error, ['模型服务不可用'])
})

test('regenerates only the last persisted answer with the prior history snapshot', async () => {
  const previous = {
    id: 'answer-0',
    question: '上一问',
    answer: '上一答',
    pending: false,
    error: false,
  }
  const current = {
    id: 'answer-1',
    question: '当前问题',
    modelQuestion: '模型原问题',
    displayQuestion: '展示原问题',
    answer: '旧回答',
    pending: false,
    error: false,
  }
  const session = createSession([previous, current])
  const harness = controllerHarness({
    session,
    readQaStream: async (_response, item) => {
      assert.equal(item, current)
      item.answer = '新回答'
      item.pending = false
    },
  })

  await harness.controller.regenerateQaAnswer(current)

  const body = JSON.parse(harness.fetchCalls[0][1].body)
  assert.deepEqual(body, {
    question: '模型原问题',
    display_question: '展示原问题',
    summary: '已有摘要',
    transcript: '已有原文',
    video_title: '内容标题',
    source_url: 'https://example.com/source',
    content_item_id: 'content-1',
    history: [{ question: '上一问', answer: '上一答' }],
    append_to_obsidian: false,
    ai_model: 'assistant-model',
    regenerate_assistant_message_id: 'answer-1',
  })
  assert.equal(current.answer, '新回答')
  assert.equal(session.asking, false)
  assert.deepEqual(harness.messages.success, ['回答已重新生成'])
})

test('restores the previous answer when regeneration fails', async () => {
  const current = {
    id: 'answer-1',
    question: '当前问题',
    answer: '必须保留的旧回答',
    pending: false,
    error: false,
  }
  const session = createSession([current])
  const harness = controllerHarness({
    session,
    fetchRequest: async () => ({
      ok: false,
      json: async () => ({ detail: '重新生成被拒绝' }),
    }),
  })

  await harness.controller.regenerateQaAnswer(current)

  assert.equal(current.answer, '必须保留的旧回答')
  assert.equal(current.pending, false)
  assert.equal(current.error, false)
  assert.equal(session.asking, false)
  assert.deepEqual(harness.messages.error, ['重新生成被拒绝'])
})

test('rejects an empty question and a non-final regeneration before network access', async () => {
  const earlier = { id: 'answer-0', question: '较早问题', answer: '较早回答' }
  const latest = { id: 'answer-1', question: '最新问题', answer: '最新回答' }
  const session = createSession([earlier, latest])
  session.draft = '   '
  const harness = controllerHarness({ session })

  await harness.controller.askQuestion()
  await harness.controller.regenerateQaAnswer(earlier)

  assert.equal(harness.fetchCalls.length, 0)
  assert.deepEqual(harness.messages.warning, [
    '请输入追问内容',
    '只能重新生成当前会话最后一条回答',
  ])
})

test('does not start overlapping question or regeneration requests', async () => {
  const current = { id: 'answer-1', question: '当前问题', answer: '当前回答' }
  const session = createSession([current])
  session.asking = true
  const harness = controllerHarness({ session })

  await harness.controller.askQuestion('重复问题')
  await harness.controller.regenerateQaAnswer(current)

  assert.equal(harness.fetchCalls.length, 0)
  assert.deepEqual(harness.messages.warning, [])
  assert.deepEqual(harness.messages.error, [])
})
