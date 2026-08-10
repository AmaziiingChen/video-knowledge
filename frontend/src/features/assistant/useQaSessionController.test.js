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
