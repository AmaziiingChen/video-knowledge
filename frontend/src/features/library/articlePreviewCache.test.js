import assert from 'node:assert/strict'
import test from 'node:test'

import {
  readArticlePreviewCache,
  removeArticlePreviewCache,
  writeArticlePreviewCache,
} from './articlePreviewCache.js'

function makeStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  }
}

test('restores a persisted article snapshot only when the content revision matches', () => {
  const storage = makeStorage()
  const item = { id: 'article-1', updated_at: '2026-07-19T10:00:00+00:00' }
  writeArticlePreviewCache(item, { html: '<p>已缓存正文</p>', author: '公众号' }, storage)

  assert.deepEqual(readArticlePreviewCache(item.id, item.updated_at, storage), {
    html: '<p>已缓存正文</p>',
    author: '公众号',
  })
  assert.equal(readArticlePreviewCache(item.id, '2026-07-20T10:00:00+00:00', storage), null)
})

test('removes a stale snapshot before a user explicitly refetches an article', () => {
  const storage = makeStorage()
  const item = { id: 'article-1', updated_at: '2026-07-19T10:00:00+00:00' }
  writeArticlePreviewCache(item, { html: '<p>旧正文</p>' }, storage)
  removeArticlePreviewCache(item.id, storage)

  assert.equal(readArticlePreviewCache(item.id, item.updated_at, storage), null)
})
