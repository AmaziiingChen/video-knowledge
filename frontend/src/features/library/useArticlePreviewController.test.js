import assert from 'node:assert/strict'
import test from 'node:test'

import { useArticlePreviewController } from './useArticlePreviewController.js'

function makeStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  }
}

function makeTimers() {
  let nextId = 0
  const active = new Map()
  return {
    active,
    setTimeout(callback, delay) {
      const id = ++nextId
      active.set(id, { callback, delay })
      return id
    },
    clearTimeout(id) {
      active.delete(id)
    },
  }
}

test('owns the full preview lifecycle and releases loader and formatting timers', async () => {
  const timers = makeTimers()
  const refreshed = []
  const request = {
    async get() {
      return { data: { html: '<p>正文</p>', formatting_status: 'running' } }
    },
  }
  const controller = useArticlePreviewController({
    refreshContentTextReadiness: (contentItemId) => refreshed.push(contentItemId),
    request,
    apiBase: 'http://local.test',
    timers,
    storage: makeStorage(),
  })

  await controller.loadArticlePreview({
    id: 'article-1',
    updated_at: '2026-08-09T00:00:00Z',
    text_readiness: { status: 'needs_fetch' },
  })

  assert.equal(controller.articlePreviews['article-1'].html, '<p>正文</p>')
  assert.deepEqual(refreshed, ['article-1'])
  assert.equal(timers.active.size, 1)

  controller.disposeArticlePreviews()
  assert.equal(timers.active.size, 0)
})

test('keeps a cached preview readable when background revalidation fails', async () => {
  const storage = makeStorage()
  const item = {
    id: 'article-2',
    updated_at: '2026-08-09T00:00:00Z',
    text_readiness: { status: 'ready' },
  }
  const successful = useArticlePreviewController({
    request: { get: async () => ({ data: { html: '<p>缓存正文</p>' } }) },
    apiBase: 'http://local.test',
    timers: makeTimers(),
    storage,
  })
  await successful.loadArticlePreview(item)

  const revalidating = useArticlePreviewController({
    request: { get: async () => { throw new Error('offline') } },
    apiBase: 'http://local.test',
    timers: makeTimers(),
    storage,
  })
  await revalidating.loadArticlePreview(item)

  assert.equal(revalidating.articlePreviews[item.id].html, '<p>缓存正文</p>')
  assert.equal(revalidating.articlePreviews[item.id].error, undefined)
})
