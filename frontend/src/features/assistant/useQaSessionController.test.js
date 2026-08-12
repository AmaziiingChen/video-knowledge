import test from 'node:test'
import assert from 'node:assert/strict'

import { useQaSessionController } from './useQaSessionController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function notificationRecorder() {
  const messages = { success: [], error: [] }
  return {
    messages,
    notify: {
      success: (message) => messages.success.push(message),
      error: (message) => messages.error.push(message)
    }
  }
}

test('starts a local empty conversation without making an API request', async () => {
  const { messages, notify } = notificationRecorder()
  const controller = useQaSessionController({
    getActiveContentId: () => null,
    notify,
    request: {
      post() {
        throw new Error('unexpected request')
      }
    }
  })
  const session = controller.activateQaSession(null)
  session.history = [{ question: '临时问题', answer: '临时回答' }]
  session.draft = '临时草稿'

  await controller.startNewChat()

  assert.deepEqual(session.history, [])
  assert.equal(session.draft, '')
  assert.equal(session.historyLoaded, true)
  assert.deepEqual(messages.success, ['已开启新对话'])
  assert.deepEqual(messages.error, [])
})

test('archives the active conversation with the established request contract', async () => {
  const calls = []
  const { messages, notify } = notificationRecorder()
  const controller = useQaSessionController({
    apiBase: '/api',
    getActiveContentId: () => 'article-chat',
    notify,
    request: {
      async post(url, body, options) {
        calls.push({ url, body, options })
        return { data: { archived: true } }
      }
    }
  })
  const session = controller.activateQaSession('article-chat')
  session.history = [{ question: '原问题', answer: '原回答' }]
  session.draft = '未发送草稿'

  await controller.startNewChat()

  assert.deepEqual(calls, [{
    url: '/api/content/article-chat/qa/new-conversation',
    body: {},
    options: { timeout: 10000 }
  }])
  assert.deepEqual(session.history, [])
  assert.equal(session.draft, '')
  assert.equal(controller.startingNewChat.value, false)
  assert.deepEqual(messages.success, ['已开启新对话；上一轮追问已归档到 Markdown'])
})

test('a failed or busy new-conversation request preserves the current session', async () => {
  let callCount = 0
  const { messages, notify } = notificationRecorder()
  const controller = useQaSessionController({
    getActiveContentId: () => 'article-failure',
    notify,
    request: {
      async post() {
        callCount += 1
        throw { response: { data: { detail: '无法归档当前对话' } } }
      }
    }
  })
  const session = controller.activateQaSession('article-failure')
  session.history = [{ question: '保留问题', answer: '保留回答' }]

  session.asking = true
  await controller.startNewChat()
  assert.equal(callCount, 0)
  session.asking = false

  await controller.startNewChat()

  assert.equal(callCount, 1)
  assert.deepEqual(session.history, [{ question: '保留问题', answer: '保留回答' }])
  assert.equal(controller.startingNewChat.value, false)
  assert.deepEqual(messages.error, ['无法归档当前对话'])
})

test('keeps completed suggestions isolated when their content is no longer active', () => {
  const controller = useQaSessionController()
  const first = controller.activateQaSession('article-one')
  first.suggestedQuestions = []
  const second = controller.activateQaSession('article-two')
  second.suggestedQuestions = ['第二篇建议']
  controller.syncQaSessionIfActive('article-two', second)

  first.suggestedQuestions = ['第一篇迟到建议']
  controller.syncQaSessionIfActive('article-one', first)

  assert.deepEqual(controller.suggestedQuestions.value, ['第二篇建议'])
})

test('projects terminal pipeline suggestions once into their matching content session', () => {
  const controller = useQaSessionController()
  const first = controller.activateQaSession('article-one')

  assert.equal(controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'task-one',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: [' 问题一？ ', '', '问题二？', '问题三？', '问题四？'],
  }), true)
  assert.deepEqual(first.suggestedQuestions, ['问题一？', '问题二？', '问题三？'])
  assert.deepEqual(controller.suggestedQuestions.value, ['问题一？', '问题二？', '问题三？'])

  first.suggestedQuestions = []
  controller.syncQaSessionIfActive('article-one', first)
  assert.equal(controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'task-one',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['不应复活？'],
  }), false)
  assert.deepEqual(controller.suggestedQuestions.value, [])

  assert.equal(controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'task-two',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['新任务建议？'],
  }), true)
  assert.deepEqual(controller.suggestedQuestions.value, ['新任务建议？'])
})

test('rejects non-terminal and mismatched suggestions without leaking across content', () => {
  const controller = useQaSessionController()
  controller.activateQaSession('article-two').suggestedQuestions = ['当前建议']
  controller.syncQaSessionIfActive('article-two', controller.ensureQaSession('article-two'))

  const rejectedTasks = [
    { task_id: 'running', content_item_id: 'article-one', status: 'running', success: false, suggested_questions: ['过早？'] },
    { task_id: 'failed', content_item_id: 'article-one', status: 'failed', success: false, suggested_questions: ['失败？'] },
    { task_id: 'mismatch', content_item_id: 'article-three', status: 'succeeded', success: true, suggested_questions: ['串台？'] },
    { task_id: 'empty', content_item_id: 'article-one', status: 'succeeded', success: true, suggested_questions: [] },
  ]
  rejectedTasks.forEach((task) => {
    assert.equal(controller.projectPipelineSuggestedQuestions('article-one', task), false)
  })
  assert.deepEqual(controller.suggestedQuestions.value, ['当前建议'])
  assert.deepEqual(controller.ensureQaSession('article-one').suggestedQuestions, [])
})

test('consumes a terminal task without overwriting or reviving it after a clear', () => {
  const controller = useQaSessionController()
  const session = controller.activateQaSession('article-one')
  session.history = [{ question: '已有问题', answer: '已有回答' }]

  assert.equal(controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'old-task',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['旧任务建议？'],
  }), false)
  assert.deepEqual(session.suggestedQuestions, [])

  controller.clearQaSession('article-one', session)
  assert.equal(session.lastProjectedSummaryTaskId, 'old-task')
  assert.equal(controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'old-task',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['仍不应复活？'],
  }), false)
  assert.deepEqual(session.suggestedQuestions, [])
})

test('keeps pipeline suggestions when empty history finishes loading', async () => {
  const response = deferred()
  const controller = useQaSessionController({
    request: { get: () => response.promise },
  })
  const session = controller.activateQaSession('article-one')
  const loading = controller.loadContentQaHistory('article-one', session)
  controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'summary-task',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['保留建议？'],
  })
  response.resolve({ data: { items: [], has_more: false, next_before: '' } })
  await loading

  assert.deepEqual(session.history, [])
  assert.deepEqual(session.suggestedQuestions, ['保留建议？'])
  assert.deepEqual(controller.suggestedQuestions.value, ['保留建议？'])
})

test('saved history remains authoritative over pipeline suggestions', async () => {
  const controller = useQaSessionController({
    request: {
      async get() {
        return {
          data: {
            items: [{
              id: 'saved',
              question: '历史问题',
              answer: '历史回答',
              suggested_questions: ['历史建议？'],
            }],
            has_more: false,
            next_before: '',
          },
        }
      },
    },
  })
  const session = controller.activateQaSession('article-one')
  controller.projectPipelineSuggestedQuestions('article-one', {
    task_id: 'summary-task',
    content_item_id: 'article-one',
    status: 'succeeded',
    success: true,
    suggested_questions: ['摘要建议？'],
  })

  await controller.loadContentQaHistory('article-one', session)

  assert.deepEqual(session.suggestedQuestions, ['历史建议？'])
  assert.deepEqual(controller.suggestedQuestions.value, ['历史建议？'])
})

test('composes shortcuts from the current session dependencies', () => {
  let autoRecognitionEnabled = true
  const templates = [{ name: '总结', template: '提炼核心观点' }]
  const controller = useQaSessionController({
    getQaShortcutTemplates: () => templates,
    isAutoQaShortcutRecognitionEnabled: () => autoRecognitionEnabled
  })

  controller.questionInput.value = '请处理'
  controller.insertQaShortcut('总结')
  assert.equal(controller.questionInput.value, '请处理 @总结 ')
  assert.deepEqual(controller.resolveQaQuestion('帮我总结一下'), {
    prompt: [
      '已选择的追问方式：\n@总结\n提炼核心观点',
      '用户补充：\n帮我总结一下'
    ].join('\n\n'),
    autoShortcutName: '总结'
  })

  autoRecognitionEnabled = false
  assert.deepEqual(controller.resolveQaQuestion('帮我总结一下'), {
    prompt: '用户补充：\n帮我总结一下',
    autoShortcutName: ''
  })
})

test('loads saved history without replacing a pending local turn', async () => {
  const response = deferred()
  const calls = []
  const controller = useQaSessionController({
    apiBase: '/api',
    request: {
      get(url, options) {
        calls.push({ url, options })
        return response.promise
      }
    }
  })
  const session = controller.activateQaSession('article-1')

  const loading = controller.loadContentQaHistory('article-1', session)
  session.history.push({
    id: 'pending-1',
    question: '刚刚提出的问题',
    answer: '',
    pending: true,
    saved: false,
    error: false,
    time: ''
  })
  response.resolve({
    data: {
      items: [{
        id: 'saved-1',
        question: '较早的问题',
        answer: '较早的回答',
        created_at: '2026-08-10T10:00:00Z'
      }],
      has_more: true,
      next_before: 'cursor-1'
    }
  })
  await loading

  assert.deepEqual(calls, [{
    url: '/api/content/article-1/qa-history',
    options: { params: { limit: 12 }, timeout: 10000 }
  }])
  assert.deepEqual(session.history, [
    {
      id: 'saved-1',
      question: '较早的问题',
      answer: '较早的回答',
      reasoning: '',
      reasoningExpanded: false,
      suggestedQuestions: [],
      saved: true,
      pending: false,
      error: false,
      time: '2026-08-10T10:00:00Z'
    },
    {
      id: 'pending-1',
      question: '刚刚提出的问题',
      answer: '',
      pending: true,
      saved: false,
      error: false,
      time: ''
    }
  ])
  assert.equal(controller.qaHistory.value, session.history)
  assert.equal(controller.qaHistoryLoading.value, false)
  assert.equal(controller.qaHistoryHasMore.value, true)
  assert.equal(session.historyNextBefore, 'cursor-1')
})

test('retries initial history twice before exposing the server error', async () => {
  const waits = []
  let callCount = 0
  const controller = useQaSessionController({
    request: {
      async get() {
        callCount += 1
        throw { response: { data: { detail: '历史服务暂不可用' } } }
      }
    },
    wait: async (milliseconds) => waits.push(milliseconds)
  })
  const session = controller.activateQaSession('article-2')

  await controller.loadContentQaHistory('article-2', session)

  assert.equal(callCount, 3)
  assert.deepEqual(waits, [500, 1000])
  assert.equal(session.historyLoaded, false)
  assert.equal(controller.qaHistoryLoading.value, false)
  assert.equal(controller.qaHistoryError.value, '历史服务暂不可用')
})

test('clearing a session while waiting cancels subsequent history retries', async () => {
  const retryDelay = deferred()
  let callCount = 0
  const controller = useQaSessionController({
    request: {
      async get() {
        callCount += 1
        throw new Error('temporary failure')
      }
    },
    wait: () => retryDelay.promise
  })
  const session = controller.activateQaSession('article-3')

  const loading = controller.loadContentQaHistory('article-3', session)
  await Promise.resolve()
  controller.clearQaSession('article-3', session)
  retryDelay.resolve()
  await loading

  assert.equal(callCount, 1)
  assert.deepEqual(session.history, [])
  assert.equal(session.historyLoaded, true)
  assert.equal(controller.qaHistoryLoading.value, false)
  assert.equal(controller.qaHistoryError.value, '')
})

test('retry routes to cursor pagination and prepends older saved history', async () => {
  let activeContentId = 'article-4'
  const calls = []
  const controller = useQaSessionController({
    apiBase: '/api',
    getActiveContentId: () => activeContentId,
    request: {
      async get(url, options) {
        calls.push({ url, options })
        return {
          data: {
            items: [{
              id: 'older-1',
              question: '更早的问题',
              answer: '更早的回答',
              created_at: '2026-08-09T10:00:00Z'
            }],
            has_more: false,
            next_before: ''
          }
        }
      }
    }
  })
  const session = controller.ensureQaSession(activeContentId)
  session.historyLoaded = true
  session.historyHasMore = true
  session.historyNextBefore = 'cursor-2'
  session.history = [{
    id: 'newer-1',
    question: '较新的问题',
    answer: '较新的回答',
    saved: true,
    pending: false,
    error: false,
    time: '2026-08-10T10:00:00Z'
  }]
  controller.activateQaSession(activeContentId)

  await controller.retryContentQaHistory()

  assert.deepEqual(calls, [{
    url: '/api/content/article-4/qa-history',
    options: { params: { limit: 12, before: 'cursor-2' }, timeout: 10000 }
  }])
  assert.deepEqual(session.history.map((item) => item.id), ['older-1', 'newer-1'])
  assert.equal(session.historyHasMore, false)
  assert.equal(session.historyNextBefore, '')
  assert.equal(controller.qaHistoryLoadingMore.value, false)
  assert.deepEqual(controller.qaHistory.value.map((item) => item.id), ['older-1', 'newer-1'])

  activeContentId = null
  await controller.retryContentQaHistory()
  assert.equal(calls.length, 1)
})
