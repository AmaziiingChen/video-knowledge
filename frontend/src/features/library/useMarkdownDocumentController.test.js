import assert from 'node:assert/strict'
import test from 'node:test'

import { useMarkdownDocumentController } from './useMarkdownDocumentController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createController({ request = {}, selectedId = null } = {}) {
  const messages = []
  const requests = []
  const selectedItems = []
  let activeSelectedId = selectedId
  const controller = useMarkdownDocumentController({
    request: {
      get: async (...args) => {
        requests.push(['get', ...args])
        return { data: {} }
      },
      put: async (...args) => {
        requests.push(['put', ...args])
        return { data: {} }
      },
      post: async (...args) => {
        requests.push(['post', ...args])
        return { data: {} }
      },
      ...request,
    },
    apiBase: 'http://api.test',
    notify: {
      success: (message) => messages.push(['success', message]),
      error: (message) => messages.push(['error', message]),
    },
    setSelectedContentItem: (item) => {
      selectedItems.push(item)
      activeSelectedId = item?.id || null
    },
    isSelectedContentItem: (itemId) => String(activeSelectedId || '') === String(itemId || ''),
  })
  return {
    controller,
    messages,
    requests,
    selectedItems,
    select: (itemId) => { activeSelectedId = itemId },
  }
}

test('projects backend Markdown state and resets every persisted field', () => {
  const { controller } = createController()
  controller.applyMarkdownState({
    content_item_id: 'item-1',
    markdown_draft_path: '/draft.md',
    obsidian_path: '/vault/draft.md',
    markdown: '# Draft',
    markdown_size_bytes: '17',
    sync_status: 'synced',
    conflict: 1,
    last_synced_at: '2026-08-10T10:00:00Z',
  })
  assert.deepEqual({ ...controller.markdownState }, {
    content_item_id: 'item-1',
    markdown_draft_path: '/draft.md',
    obsidian_path: '/vault/draft.md',
    markdown: '# Draft',
    markdown_size_bytes: 17,
    sync_status: 'synced',
    conflict: true,
    last_synced_at: '2026-08-10T10:00:00Z',
  })

  controller.resetMarkdownState()
  assert.deepEqual({ ...controller.markdownState }, {
    content_item_id: null,
    markdown_draft_path: null,
    obsidian_path: null,
    markdown: '',
    markdown_size_bytes: 0,
    sync_status: 'unknown',
    conflict: false,
    last_synced_at: null,
  })
})

test('loads only the still-selected item and ignores a stale response', async () => {
  const first = deferred()
  const second = deferred()
  const { controller, requests, select } = createController({
    selectedId: 'item-a',
    request: {
      get: (url) => url.endsWith('/item-a') ? first.promise : second.promise,
    },
  })

  const firstLoad = controller.loadMarkdownForItem({ id: 'item-a' })
  select('item-b')
  const secondLoad = controller.loadMarkdownForItem({ id: 'item-b' })
  second.resolve({ data: { content_item_id: 'item-b', markdown: '# B' } })
  await secondLoad
  first.resolve({ data: { content_item_id: 'item-a', markdown: '# A' } })
  await firstLoad

  assert.equal(controller.markdownState.content_item_id, 'item-b')
  assert.equal(controller.markdownState.markdown, '# B')
  assert.equal(controller.loadingMarkdown.value, false)
  assert.deepEqual(requests, [])
})

test('opens the editor with the exact read contract and closes it on failure', async () => {
  const { controller, requests, selectedItems } = createController({
    request: {
      get: async (...args) => {
        requests.push(['get', ...args])
        return { data: { content_item_id: 'item-1', markdown: '# Draft' } }
      },
    },
  })
  const item = { id: 'item-1', title: 'Draft' }
  await controller.openMarkdownDialog(item)
  assert.equal(controller.showMarkdownDialog.value, true)
  assert.deepEqual(controller.currentMarkdownItem.value, item)
  assert.equal(controller.markdownState.markdown, '# Draft')
  assert.deepEqual(selectedItems, [item])
  assert.deepEqual(requests, [[
    'get',
    'http://api.test/markdown/content/item-1',
    { timeout: 10000 },
  ]])

  const failure = createController({
    request: {
      get: async () => { throw { response: { data: { detail: '草稿不存在' } } } },
    },
  })
  await failure.controller.openMarkdownDialog(item)
  assert.equal(failure.controller.showMarkdownDialog.value, false)
  assert.equal(failure.controller.loadingMarkdown.value, false)
  assert.deepEqual(failure.messages, [['error', '草稿不存在']])
})

test('saves and syncs the current document without changing request payloads', async () => {
  const { controller, requests, messages, selectedItems } = createController({
    request: {
      put: async (...args) => {
        requests.push(['put', ...args])
        return { data: { content_item_id: 'item-1', markdown: '# Saved' } }
      },
      post: async (...args) => {
        requests.push(['post', ...args])
        return { data: { content_item_id: 'item-1', markdown: '# Saved', sync_status: 'synced' } }
      },
    },
  })
  const item = { id: 'item-1' }
  controller.currentMarkdownItem.value = item
  controller.markdownState.markdown = '# Edited'

  await controller.saveMarkdownDraft()
  await controller.syncMarkdownDraft()

  assert.deepEqual(requests, [
    [
      'put',
      'http://api.test/markdown/content/item-1',
      { markdown: '# Edited' },
      { timeout: 10000 },
    ],
    [
      'post',
      'http://api.test/markdown/content/item-1/sync',
      {},
      { timeout: 10000 },
    ],
  ])
  assert.deepEqual(messages, [
    ['success', '草稿已保存'],
    ['success', '已写入指定 Markdown 目录'],
  ])
  assert.deepEqual(selectedItems, [item, item])
  assert.equal(controller.savingMarkdown.value, false)
  assert.equal(controller.syncingMarkdown.value, false)
  assert.equal(controller.markdownState.sync_status, 'synced')
})

test('reports write failures and always releases pending state', async () => {
  const failure = { message: 'offline' }
  const { controller, messages } = createController({
    request: {
      put: async () => { throw failure },
      post: async () => { throw failure },
    },
  })
  controller.currentMarkdownItem.value = { id: 'item-1' }

  await controller.saveMarkdownDraft()
  await controller.syncMarkdownDraft()

  assert.deepEqual(messages, [
    ['error', 'offline'],
    ['error', 'offline'],
  ])
  assert.equal(controller.savingMarkdown.value, false)
  assert.equal(controller.syncingMarkdown.value, false)
})
