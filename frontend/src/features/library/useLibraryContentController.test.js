import test from 'node:test'
import assert from 'node:assert/strict'

import { useLibraryContentController } from './useLibraryContentController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function mergeById(currentItems, incomingItems) {
  const byId = new Map(currentItems.map((item) => [item.id, item]))
  for (const item of incomingItems) {
    if (!byId.has(item.id)) byId.set(item.id, item)
  }
  return [...byId.values()]
}

function notificationRecorder() {
  const messages = { warning: [], error: [] }
  return {
    messages,
    notify: {
      warning: (message) => messages.warning.push(message),
      error: (message) => messages.error.push(message),
    },
  }
}

function controllerHarness(overrides = {}) {
  const folderLoads = []
  const workspaceSyncs = []
  const reconciliations = []
  const scheduled = []
  const cancelled = []
  const getCalls = []
  const postCalls = []
  const selectedContentItem = { value: null }
  const { messages, notify } = notificationRecorder()
  const controller = useLibraryContentController({
    selectedContentItem,
    mergeContentItems: mergeById,
    reconcileContentViewState: (...args) => reconciliations.push(args),
    loadLibraryFolders: async (...args) => folderLoads.push(args),
    syncActiveWorkspaceTabSelection: (...args) => workspaceSyncs.push(args),
    request: {
      async get(...args) {
        getCalls.push(args)
        return { data: { items: [], has_more: false } }
      },
      async post(...args) {
        postCalls.push(args)
        return { data: [] }
      },
    },
    apiBase: '/api',
    notify,
    schedule: (callback, delay) => {
      const timer = scheduled.length + 1
      scheduled.push({ timer, callback, delay })
      return timer
    },
    cancel: (timer) => cancelled.push(timer),
    ...overrides,
  })
  return {
    controller,
    selectedContentItem,
    folderLoads,
    workspaceSyncs,
    reconciliations,
    scheduled,
    cancelled,
    getCalls,
    postCalls,
    messages,
  }
}

test('loads a bounded recent window during startup so unread state is available before expansion', async () => {
  const harness = controllerHarness()
  harness.controller.allContentItems.value = [{ id: 'loaded-1' }]

  await harness.controller.loadContentItems({ startup: true })

  assert.deepEqual(harness.folderLoads, [[{ throwOnError: true }]])
  assert.deepEqual(harness.getCalls, [[
    '/api/content/page',
    { params: { limit: 200 }, timeout: 15000 },
  ]])
  assert.equal(harness.workspaceSyncs.length, 1)
  assert.equal(harness.controller.startupBlocking.value, false)
  assert.equal(harness.controller.startupCanRetry.value, false)
  assert.deepEqual(harness.controller.startupStatus.value, {
    title: '正在连接本机服务',
    detail: '资料库与后台任务正在准备中。',
  })
  assert.deepEqual(harness.controller.contentPageLoadStatus, {
    state: 'ready',
    loaded: 1,
    total: 1,
  })
  assert.deepEqual(harness.reconciliations, [[[{ id: 'loaded-1' }], { initialWindowComplete: true }]])
})

test('ignores a stale startup completion when a newer load wins', async () => {
  const first = deferred()
  const second = deferred()
  let callCount = 0
  const harness = controllerHarness({
    loadLibraryFolders: () => {
      callCount += 1
      return callCount === 1 ? first.promise : second.promise
    },
  })

  const olderLoad = harness.controller.loadContentItems({ startup: true })
  const newerLoad = harness.controller.loadContentItems({ startup: true })
  first.resolve()
  await olderLoad
  assert.equal(harness.workspaceSyncs.length, 0)
  assert.equal(harness.controller.startupBlocking.value, true)

  second.resolve()
  await newerLoad
  assert.equal(harness.workspaceSyncs.length, 1)
  assert.equal(harness.controller.startupBlocking.value, false)
})

test('schedules a bounded timeout retry and supports an immediate manual retry', async () => {
  let callCount = 0
  const harness = controllerHarness({
    loadLibraryFolders: async () => {
      callCount += 1
      if (callCount === 1) throw Object.assign(new Error('request timeout'), { code: 'ECONNABORTED' })
    },
  })

  await harness.controller.loadContentItems({ startup: true })

  assert.equal(harness.controller.startupCanRetry.value, true)
  assert.deepEqual(harness.scheduled.map(({ delay }) => delay), [600])
  assert.deepEqual(harness.messages.warning, ['资料库暂未响应，正在重新连接'])

  harness.controller.retryStartupHydration()
  await new Promise((resolve) => globalThis.setTimeout(resolve, 0))

  assert.deepEqual(harness.cancelled, [1])
  assert.equal(callCount, 2)
  assert.equal(harness.controller.startupBlocking.value, false)
})

test('resolves at most 300 unique items and reveals their folders', async () => {
  const ids = Array.from({ length: 305 }, (_, index) => `content-${index}`)
  ids.push('content-1')
  const resolvedItems = [
    { id: 'content-1', library_folder_id: 'folder-a' },
    { id: 'content-2', library_folder_id: 'folder-b' },
  ]
  const harness = controllerHarness({
    request: {
      async post(...args) {
        harness.postCalls.push(args)
        return { data: resolvedItems }
      },
      async get() {
        return { data: { items: [], has_more: false } }
      },
    },
  })
  harness.controller.allContentItems.value = [{ id: 'existing' }]

  const result = await harness.controller.revealContentItems(ids)

  assert.equal(harness.postCalls[0][1].content_item_ids.length, 300)
  assert.deepEqual(harness.postCalls[0][2], { timeout: 15000 })
  assert.equal(harness.controller.allContentItems.value.length, 3)
  assert.deepEqual(harness.controller.libraryFolderRevealIds.value, ['folder-a', 'folder-b'])
  assert.deepEqual(result, resolvedItems)
  assert.equal(harness.reconciliations.length, 1)
})

test('paginates one folder in 80-item requests and preserves state after failure', async () => {
  const pages = [
    { data: { items: [{ id: 'a' }, { id: 'b' }], has_more: true } },
    { data: { items: [{ id: 'c' }], has_more: false } },
  ]
  const harness = controllerHarness({
    request: {
      async get(...args) {
        harness.getCalls.push(args)
        if (pages.length) return pages.shift()
        throw { response: { data: { detail: '文件夹读取失败' } } }
      },
      async post() {
        return { data: [] }
      },
    },
  })

  await harness.controller.loadLibraryFolderHistory({ folderId: 'folder/one' })
  await harness.controller.loadLibraryFolderHistory({ folderId: 'folder/one', append: true })

  assert.deepEqual(harness.getCalls.slice(0, 2), [
    ['/api/content/folders/folder%2Fone/items', { params: { limit: 80, offset: 0 }, timeout: 15000 }],
    ['/api/content/folders/folder%2Fone/items', { params: { limit: 80, offset: 2 }, timeout: 15000 }],
  ])
  assert.deepEqual(harness.controller.allContentItems.value.map((item) => item.id), ['a', 'b', 'c'])
  assert.deepEqual(harness.controller.libraryFolderHistoryStates.value['folder/one'], {
    offset: 3,
    hasMore: false,
    loaded: true,
    loading: false,
  })

  await harness.controller.loadLibraryFolderHistory({ folderId: 'broken' })
  assert.deepEqual(harness.controller.libraryFolderHistoryStates.value.broken, {
    offset: 0,
    hasMore: true,
    loaded: false,
    loading: false,
  })
  assert.deepEqual(harness.messages.error, ['文件夹读取失败'])
})

test('updates the collection and selected item through one local mutation boundary', () => {
  const harness = controllerHarness()
  harness.controller.allContentItems.value = [{ id: 'a', title: '旧标题' }, { id: 'b', title: '保留' }]
  harness.selectedContentItem.value = harness.controller.allContentItems.value[0]

  harness.controller.updateLocalContentItem('a', (item) => ({ ...item, title: '新标题' }))

  assert.deepEqual(harness.controller.contentItems.value, [
    { id: 'a', title: '新标题' },
    { id: 'b', title: '保留' },
  ])
  assert.equal(harness.selectedContentItem.value.title, '新标题')
})
