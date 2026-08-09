import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useLibraryFolderController } from './useLibraryFolderController.js'

function createController({ folders = [{ id: 'folder-1', name: '原文件夹', is_pinned: false }], request = {} } = {}) {
  const libraryFolders = ref(folders)
  const events = []
  const snapshotLibraryState = () => ({ folders: libraryFolders.value.map((folder) => ({ ...folder })) })
  const controller = useLibraryFolderController({
    libraryFolders,
    snapshotLibraryState,
    restoreLibraryState: (snapshot) => { libraryFolders.value = snapshot.folders },
    nextSortOrder: () => 7,
    recordLibraryHistory: (...args) => events.push(args),
    request: { get: async () => ({ data: [] }), post: async () => ({ data: {} }), patch: async () => ({ data: {} }), ...request },
    apiBase: 'http://api.test',
    notify: { success: (message) => events.push(['success', message]), error: (message) => events.push(['error', message]) },
  })
  return { controller, libraryFolders, events }
}

test('loads folder rows from the stable library endpoint', async () => {
  const calls = []
  const { controller, libraryFolders } = createController({
    request: { get: async (...args) => { calls.push(args); return { data: [{ id: 'folder-2', name: '已加载' }] } } },
  })
  await controller.loadLibraryFolders()
  assert.deepEqual(calls, [['http://api.test/content/folders', { timeout: 10000 }]])
  assert.deepEqual(libraryFolders.value, [{ id: 'folder-2', name: '已加载' }])
})

test('creates a folder optimistically and replaces its temporary row with the API response', async () => {
  const calls = []
  const { controller, libraryFolders } = createController({
    request: { post: async (...args) => { calls.push(args); return { data: { id: 'folder-2', name: '新文件夹', sort_order: 7 } } } },
  })
  await controller.createLibraryFolder({ name: '新文件夹' })
  assert.deepEqual(calls, [[
    'http://api.test/content/folders',
    { name: '新文件夹', parent_folder_id: null, sort_order: 7 },
    { timeout: 10000 },
  ]])
  assert.deepEqual(libraryFolders.value.at(-1), { id: 'folder-2', name: '新文件夹', sort_order: 7 })
})

test('renaming a folder keeps the optimistic update and records its undo history', async () => {
  const { controller, libraryFolders, events } = createController({
    request: { patch: async () => ({ data: { updated_at: '2026-08-09T00:00:00Z' } }) },
  })
  await controller.renameLibraryFolder({ id: 'folder-1', name: '新名称' })
  assert.equal(libraryFolders.value[0].name, '新名称')
  assert.equal(events[0][0], '重命名文件夹')
})

test('pinning a folder preserves its request contract, success notice and history', async () => {
  const calls = []
  const { controller, libraryFolders, events } = createController({
    request: { patch: async (...args) => { calls.push(args); return { data: { is_pinned: true } } } },
  })
  await controller.setLibraryFolderPinned({ folder: libraryFolders.value[0], pinned: true })
  assert.deepEqual(calls, [[
    'http://api.test/content/folders/folder-1',
    { is_pinned: true },
    { timeout: 10000 },
  ]])
  assert.equal(libraryFolders.value[0].is_pinned, true)
  assert.equal(events[0][0], '置顶文件夹')
  assert.deepEqual(events.at(-1), ['success', '文件夹已置顶'])
})
