import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useArticlePreparationController } from './useArticlePreparationController.js'

function deferred() {
  let resolve
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function createController({ content = { id: 'article-1', content_type: 'article' }, request = {} } = {}) {
  const current = ref(content)
  const errors = []
  const timers = []
  const cancelled = []
  const controller = useArticlePreparationController({
    currentContent: () => current.value,
    notifyError: (message) => errors.push(message),
    request: {
      get: async () => ({ data: {} }),
      post: async () => ({ data: {} }),
      ...request,
    },
    apiBase: 'http://api.test',
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      timers.push(timer)
      return timer
    },
    cancelSchedule: (timer) => cancelled.push(timer),
  })
  return { controller, current, errors, timers, cancelled }
}

test('loads OCR status only for the currently selected article', async () => {
  const requests = []
  const { controller, current } = createController({
    request: {
      get: async (...args) => {
        requests.push(args)
        return { data: { status: 'queued', has_images: true } }
      },
    },
  })

  await controller.loadCurrentArticleOcrStatus()
  assert.deepEqual(requests, [['http://api.test/content/article-1/article-ocr-status', { timeout: 5000 }]])
  assert.deepEqual(controller.currentArticleOcrStatus.value, { status: 'queued', has_images: true, priority: false })

  current.value = { id: 'video-1', content_type: 'video' }
  await controller.loadCurrentArticleOcrStatus()
  assert.deepEqual(controller.currentArticleOcrStatus.value, { status: 'unavailable', has_images: false, priority: false })
  assert.equal(requests.length, 1)
})

test('a stale OCR response cannot replace the status for a new selection', async () => {
  const pending = deferred()
  const { controller, current } = createController({ request: { get: async () => pending.promise } })
  const loading = controller.loadCurrentArticleOcrStatus()
  current.value = { id: 'article-2', content_type: 'article' }
  pending.resolve({ data: { status: 'ready', has_images: true } })
  await loading

  assert.deepEqual(controller.currentArticleOcrStatus.value, { status: 'unavailable', has_images: false, priority: false })
})

test('prioritizing reports a usable error and always unlocks the action', async () => {
  const { controller, errors } = createController({
    request: { post: async () => { throw { response: { data: { detail: '任务不存在' } } } } },
  })

  await controller.prioritizeCurrentArticleOcr()
  assert.deepEqual(errors, ['任务不存在'])
  assert.equal(controller.prioritizingArticleOcr.value, false)
})

test('polling chooses the pending cadence and cancels the prior timer', async () => {
  const { controller, timers, cancelled } = createController({
    request: {
      get: async (url) => url.endsWith('article-preparation-status')
        ? { data: { pending_count: 1 } }
        : { data: { status: 'queued' } },
    },
  })

  controller.startArticlePreparationStatusPolling()
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(timers.length, 1)
  assert.equal(timers[0].delay, 3000)
  controller.stopArticlePreparationStatusPolling()
  assert.deepEqual(cancelled, [timers[0]])
})
