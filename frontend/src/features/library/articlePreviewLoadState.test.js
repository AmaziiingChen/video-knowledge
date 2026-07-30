import assert from 'node:assert/strict'
import test from 'node:test'

import {
  pendingArticlePreview,
  revealArticlePreviewLoader,
  shouldShowArticlePreviewLoader,
} from './articlePreviewLoadState.js'

test('keeps a locally ready article preview loading state visually silent', () => {
  const preview = pendingArticlePreview(null, { status: 'ready' })

  assert.equal(preview.loading, true)
  assert.equal(preview.silent, true)
  assert.equal(shouldShowArticlePreviewLoader(preview), false)
})

test('shows a loader only while an article still needs local capture', () => {
  const preview = revealArticlePreviewLoader(pendingArticlePreview(null, { status: 'needs_fetch' }))

  assert.equal(preview.silent, false)
  assert.equal(preview.loading_label, '本地正文快照未就绪，正在获取原文…')
  assert.equal(shouldShowArticlePreviewLoader(preview), true)
})

test('labels a lightweight list row as a local snapshot check', () => {
  const preview = pendingArticlePreview(null, { status: 'pending' })

  assert.equal(preview.loading_label, '正在检查本地正文快照…')
})

test('does not flash a loader during a short local cache read', () => {
  const preview = pendingArticlePreview(null, { status: 'needs_fetch' })

  assert.equal(shouldShowArticlePreviewLoader(preview), false)
})
