import assert from 'node:assert/strict'
import test from 'node:test'

import { contentIsUnread, normalizeContentReadState } from './contentReadState.js'

test('an explicitly viewed historical item stays read after the recent window is reloaded', () => {
  const state = normalizeContentReadState({
    initialized: true,
    viewed_content_ids: ['history-1'],
    viewed_before: '2026-07-01T00:00:00.000Z',
  })

  assert.equal(contentIsUnread(
    { id: 'history-1', created_at: '2025-01-01T00:00:00.000Z' },
    {
      viewedContentIds: new Set(state.viewedContentIds),
      explicitlyUnreadContentIds: new Set(state.explicitlyUnreadContentIds),
      viewedBefore: state.viewedBefore,
    },
  ), false)
})

test('documents that existed before the first-read baseline are not surfaced as unread on demand', () => {
  assert.equal(contentIsUnread(
    { id: 'archived', created_at: '2025-01-01T00:00:00.000Z' },
    { viewedBefore: '2026-07-01T00:00:00.000Z' },
  ), false)
  assert.equal(contentIsUnread(
    { id: 'new', created_at: '2026-07-02T00:00:00.000Z' },
    { viewedBefore: '2026-07-01T00:00:00.000Z' },
  ), true)
})

test('an explicit unread override remains unread even for an older document', () => {
  assert.equal(contentIsUnread(
    { id: 'history-1', created_at: '2025-01-01T00:00:00.000Z' },
    {
      explicitlyUnreadContentIds: new Set(['history-1']),
      viewedBefore: '2026-07-01T00:00:00.000Z',
    },
  ), true)
})

test('legacy read state is preserved and marked for a non-destructive baseline migration', () => {
  const state = normalizeContentReadState({
    initialized: true,
    viewed_content_ids: ['read-1', 'read-1'],
  })

  assert.deepEqual(state.viewedContentIds, ['read-1'])
  assert.equal(state.needsBaselineMigration, true)
})
