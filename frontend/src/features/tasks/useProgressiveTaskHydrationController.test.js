import assert from 'node:assert/strict'
import test from 'node:test'

import { progressiveTaskSnapshot } from '../../composables/contentRefreshState.js'
import { useProgressiveTaskHydrationController } from './useProgressiveTaskHydrationController.js'

function deferred() {
  let resolve
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function createController({
  contentById = {},
  activeContentItemId = null,
  activeResultContentItemId = null,
  request = {},
} = {}) {
  const calls = {
    details: [],
    tabMetadata: [],
    selected: [],
    markdownItems: [],
    readiness: [],
    previews: [],
    merged: [],
    logs: [],
    applied: [],
    requests: [],
  }
  const snapshots = new Map()
  const articlePreviews = {}
  const controller = useProgressiveTaskHydrationController({
    progressiveTaskSnapshots: snapshots,
    getContentItemDetail: async (contentItemId) => {
      calls.details.push(contentItemId)
      const value = contentById[contentItemId]
      return typeof value === 'function' ? value() : value || null
    },
    syncTaskTabMetadata: (content) => calls.tabMetadata.push(content),
    getActiveContentItemId: () => activeContentItemId,
    setSelectedContentItem: (content) => calls.selected.push(content),
    setCurrentMarkdownItem: (content) => calls.markdownItems.push(content),
    updatePendingArticlePreviewReadiness: (content) => calls.readiness.push(content),
    articlePreviews,
    loadArticlePreview: async (...args) => { calls.previews.push(args) },
    mergeBatchTasks: (tasks) => calls.merged.push(tasks),
    addBackendLogs: (...args) => calls.logs.push(args),
    getActiveResultContentItemId: () => activeResultContentItemId,
    applyTaskData: (task) => calls.applied.push(task),
    request: {
      get: async (...args) => {
        calls.requests.push(args)
        return { data: null }
      },
      ...request,
    },
    apiBase: 'http://api.test',
  })
  return { controller, calls, snapshots, articlePreviews }
}

test('hydrates tab metadata without stealing focus and refreshes only an active readable article', async () => {
  const article = { id: 'content-1', content_type: 'article', source_provider: 'wechat' }
  const background = createController({ contentById: { 'content-1': article } })
  assert.equal(await background.controller.syncVisibleProgressiveContent({ content_item_id: 'content-1' }), article)
  assert.deepEqual(background.calls.tabMetadata, [article])
  assert.deepEqual(background.calls.selected, [])
  assert.deepEqual(background.calls.previews, [])

  const active = createController({
    contentById: { 'content-1': article },
    activeContentItemId: 'content-1',
  })
  active.articlePreviews['content-1'] = { error: 'stale' }
  await active.controller.syncVisibleProgressiveContent({ content_item_id: 'content-1' })
  assert.deepEqual(active.calls.selected, [article])
  assert.deepEqual(active.calls.markdownItems, [article])
  assert.deepEqual(active.calls.readiness, [article])
  assert.deepEqual(active.calls.previews, [[article, { force: true }]])
})

test('hydrates compact task details once, reconciles the active result, and stores the resolved snapshot', async () => {
  const content = { id: 'content-1', content_type: 'video', source_provider: 'bilibili' }
  const detailTask = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
    step: 'transcribe',
    progress: { transcribe: 100 },
    logs: [{ msg: 'ready' }],
  }
  const state = createController({
    contentById: { 'content-1': content },
    activeContentItemId: 'content-1',
    activeResultContentItemId: 'content-1',
    request: {
      get: async (...args) => {
        state.calls.requests.push(args)
        return { data: detailTask }
      },
    },
  })
  const compactTask = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
    step: 'transcribe',
    progress: { transcribe: 100 },
    details_included: false,
  }

  await state.controller.hydrateProgressiveTask(compactTask, '')

  assert.deepEqual(state.calls.requests, [[
    'http://api.test/tasks/task-1',
    { timeout: 10000 },
  ]])
  assert.deepEqual(state.calls.merged, [[detailTask]])
  assert.deepEqual(state.calls.logs, [[detailTask.logs, detailTask]])
  assert.deepEqual(state.calls.applied, [detailTask])
  assert.deepEqual(state.calls.details, ['content-1'])
  assert.equal(state.snapshots.get('task-1'), progressiveTaskSnapshot(detailTask))
})

test('does not acknowledge a milestone when content hydration still races the database', async () => {
  const task = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
    step: 'download',
  }
  const state = createController()
  await state.controller.hydrateProgressiveTask(task, '')
  assert.equal(state.snapshots.has('task-1'), false)
})

test('coalesces concurrent hydration for the same task and releases the guard afterward', async () => {
  const content = deferred()
  const item = { id: 'content-1', content_type: 'video', source_provider: 'bilibili' }
  const state = createController({ contentById: { 'content-1': () => content.promise } })
  const task = {
    task_id: 'task-1',
    content_item_id: 'content-1',
    status: 'running',
    step: 'download',
  }

  const first = state.controller.hydrateProgressiveTask(task, '')
  const duplicate = state.controller.hydrateProgressiveTask(task, '')
  content.resolve(item)
  await Promise.all([first, duplicate])
  assert.deepEqual(state.calls.details, ['content-1'])

  state.snapshots.delete('task-1')
  await state.controller.hydrateProgressiveTask(task, '')
  assert.deepEqual(state.calls.details, ['content-1', 'content-1'])
})

test('reveals each article, video, and transcript milestone at most once', async () => {
  const item = { id: 'content-1', content_type: 'video', source_provider: 'wechat' }
  const state = createController({ contentById: { 'content-1': item } })
  const articleTask = {
    task_id: 'article-1',
    content_item_id: 'content-1',
    platform: 'wechat',
    text_source: { kind: 'article' },
    transcript: 'article body',
  }
  const videoTask = {
    task_id: 'video-1',
    content_item_id: 'content-1',
    video_path: '/video.mp4',
  }
  const transcriptTask = {
    task_id: 'transcript-1',
    content_item_id: 'content-1',
    transcript: 'timed text',
  }

  await state.controller.revealWechatArticleSnapshot(articleTask)
  await state.controller.revealWechatArticleSnapshot(articleTask)
  await state.controller.revealVideoSnapshot(videoTask)
  await state.controller.revealVideoSnapshot(videoTask)
  await state.controller.revealTranscriptSnapshot(transcriptTask)
  await state.controller.revealTranscriptSnapshot(transcriptTask)

  assert.deepEqual(state.calls.details, ['content-1', 'content-1', 'content-1'])
})
