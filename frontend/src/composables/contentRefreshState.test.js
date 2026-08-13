import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mergeUniqueContentItems,
  progressiveTaskSnapshot,
  shouldHydrateProgressiveTask,
  shouldRefreshContentForTask,
  taskContentSnapshot
} from './contentRefreshState.js'

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled'])

test('merges paginated content without duplicating an item', () => {
  assert.deepEqual(
    mergeUniqueContentItems([{ id: 'a' }, { id: 'b' }], [{ id: 'b' }, { id: 'c' }]),
    [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
  )
})

test('does not refresh content for the initial task queue snapshot', () => {
  const task = { status: 'succeeded', content_item_id: 'content-a' }
  assert.equal(shouldRefreshContentForTask(task, undefined, false, terminalStatuses), false)
})

test('does not refresh content for progress-only task changes', () => {
  const task = { status: 'running', content_item_id: 'content-a' }
  assert.equal(shouldRefreshContentForTask(task, 'queued|content-a', true, terminalStatuses), false)
})

test('refreshes content once when a task reaches a terminal state', () => {
  const task = { status: 'succeeded', content_item_id: 'content-a' }
  assert.equal(shouldRefreshContentForTask(task, 'running|content-a', true, terminalStatuses), true)
  assert.equal(
    shouldRefreshContentForTask(task, taskContentSnapshot(task), true, terminalStatuses),
    false
  )
})

test('refreshes after a source sync finishes even without one content item id', () => {
  const task = { task_type: 'source_sync', status: 'succeeded' }
  assert.equal(shouldRefreshContentForTask(task, 'running|', true, terminalStatuses), true)
})

test('hydrates a task only when a readable or playable milestone changes', () => {
  const queued = { status: 'queued', content_item_id: 'content-a', step: 'parse' }
  assert.equal(shouldHydrateProgressiveTask(queued, undefined), true)

  const downloading = {
    status: 'running',
    content_item_id: 'content-a',
    step: 'download',
    progress: { transcribe: 0 },
  }
  assert.equal(shouldHydrateProgressiveTask(downloading, progressiveTaskSnapshot(downloading)), false)

  const subtitlesReady = {
    ...downloading,
    step: 'transcribe',
    progress: { transcribe: 100 },
  }
  assert.equal(
    shouldHydrateProgressiveTask(subtitlesReady, progressiveTaskSnapshot(downloading)),
    true
  )

  const reasoningStarted = {
    ...subtitlesReady,
    step: 'summarize',
    reasoning_length: 8,
  }
  assert.equal(
    shouldHydrateProgressiveTask(reasoningStarted, progressiveTaskSnapshot(subtitlesReady)),
    true
  )
})
