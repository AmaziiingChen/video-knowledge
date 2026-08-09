import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useLibraryMutationController } from './useLibraryMutationController.js'

function copy(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value))
}

function createController({ request = {} } = {}) {
  const libraryFolders = ref([
    { id: 'folder-root', name: '根目录', parent_folder_id: null, sort_order: 1 },
    { id: 'folder-child', name: '子目录', parent_folder_id: 'folder-root', sort_order: 1 },
    { id: 'folder-target', name: '目标', parent_folder_id: null, sort_order: 3 },
  ])
  const allContentItems = ref([
    { id: 'content-root', title: '根资料', library_folder_id: 'folder-root', sort_order: 1 },
    { id: 'content-child', title: '子资料', library_folder_id: 'folder-child', sort_order: 1 },
    { id: 'content-free', title: '独立资料', library_folder_id: null, sort_order: 2 },
  ])
  const workspaceTabs = ref([
    { id: 'tab-root', content_item_id: 'content-root', title: '根资料' },
    { id: 'tab-free', content_item_id: 'content-free', title: '独立资料' },
  ])
  const activeWorkspaceTabId = ref('tab-root')
  const selectedContentItem = ref(allContentItems.value[0])
  const calls = []
  const events = []
  const snapshotLibraryState = () => ({
    folders: copy(libraryFolders.value),
    allItems: copy(allContentItems.value),
    workspaceTabs: copy(workspaceTabs.value),
    activeWorkspaceTabId: activeWorkspaceTabId.value,
    selectedContentItem: copy(selectedContentItem.value),
  })
  const restoreLibraryState = (snapshot) => {
    libraryFolders.value = snapshot.folders
    allContentItems.value = snapshot.allItems
    workspaceTabs.value = snapshot.workspaceTabs
    activeWorkspaceTabId.value = snapshot.activeWorkspaceTabId
    selectedContentItem.value = snapshot.selectedContentItem
  }
  const controller = useLibraryMutationController({
    libraryFolders,
    allContentItems,
    workspaceTabs,
    activeWorkspaceTabId,
    selectedContentItem,
    snapshotLibraryState,
    restoreLibraryState,
    recordLibraryHistory: (...args) => events.push(['history', ...args]),
    discardLibraryHistoryForNodes: (nodes) => events.push(['discard', nodes]),
    resetMarkdownState: () => events.push(['reset-markdown']),
    applyContentFilter: () => events.push(['filter']),
    updateLocalContentItem: (id, updater) => {
      allContentItems.value = allContentItems.value.map((item) => item.id === id ? updater({ ...item }) : item)
      if (selectedContentItem.value?.id === id) {
        selectedContentItem.value = allContentItems.value.find((item) => item.id === id) || selectedContentItem.value
      }
    },
    loadLibraryTrash: async () => events.push(['load-trash']),
    showTrashUndoMessage: (...args) => events.push(['undo', ...args]),
    request: {
      delete: async (...args) => { calls.push(['delete', ...args]); return { data: {} } },
      patch: async (...args) => {
        calls.push(['patch', ...args])
        const id = String(args[0]).split('/').at(-1)
        const current = allContentItems.value.find((item) => item.id === id) || {}
        return { data: { ...current, ...args[1] } }
      },
      ...request,
    },
    apiBase: 'http://api.test',
    notify: {
      error: (message) => events.push(['error', message]),
      warning: (message) => events.push(['warning', message]),
    },
  })
  return {
    controller,
    libraryFolders,
    allContentItems,
    workspaceTabs,
    activeWorkspaceTabId,
    selectedContentItem,
    calls,
    events,
  }
}

test('renames a content item optimistically, keeps its tab title in sync, then records undo history', async () => {
  const { controller, allContentItems, workspaceTabs, calls, events } = createController()

  await controller.renameContentItem({ id: 'content-root', title: '新标题' })

  assert.equal(allContentItems.value[0].title, '新标题')
  assert.equal(workspaceTabs.value[0].title, '新标题')
  assert.equal(events.find((event) => event[0] === 'history')[1], '重命名内容')
  assert.deepEqual(calls, [[
    'patch',
    'http://api.test/content/content-root',
    { title: '新标题' },
    { timeout: 10000 },
  ]])
})

test('moves a content item into a folder with the established API contract and history', async () => {
  const { controller, allContentItems, calls, events } = createController()

  await controller.moveLibraryNode({
    drag: { type: 'content', id: 'content-free' },
    target: { type: 'folder', id: 'folder-target' },
    position: 'inside',
  })

  assert.equal(allContentItems.value.find((item) => item.id === 'content-free').library_folder_id, 'folder-target')
  assert.deepEqual(calls, [[
    'patch',
    'http://api.test/content/content-free',
    { library_folder_id: 'folder-target', sort_order: 1 },
    { timeout: 10000 },
  ]])
  assert.equal(events.find((event) => event[0] === 'history')[1], '移动项目')
})

test('rejects attempts to move a folder into one of its descendants before changing local state', async () => {
  const { controller, libraryFolders, calls, events } = createController()
  const before = copy(libraryFolders.value)

  await controller.moveLibraryNode({
    drag: { type: 'folder', id: 'folder-root' },
    target: { type: 'folder', id: 'folder-child' },
    position: 'inside',
  })

  assert.deepEqual(libraryFolders.value, before)
  assert.deepEqual(calls, [])
  assert.deepEqual(events, [['warning', '不能移动到自身或子文件夹']])
})

test('deletes nested selections once at their roots and preserves a single undo transaction', async () => {
  const { controller, libraryFolders, allContentItems, workspaceTabs, activeWorkspaceTabId, selectedContentItem, calls, events } = createController()

  await controller.deleteLibraryNodes([
    { type: 'folder', id: 'folder-root', name: '根目录' },
    { type: 'folder', id: 'folder-child', name: '子目录' },
    { type: 'content', id: 'content-child', title: '子资料' },
    { type: 'content', id: 'content-free', title: '独立资料' },
  ])

  assert.deepEqual(calls, [
    ['delete', 'http://api.test/content/folders/folder-root', { timeout: 10000 }],
    ['delete', 'http://api.test/content/content-free', { timeout: 10000 }],
  ])
  assert.deepEqual(libraryFolders.value.map((folder) => folder.id), ['folder-target'])
  assert.deepEqual(allContentItems.value, [])
  assert.deepEqual(workspaceTabs.value, [])
  assert.equal(activeWorkspaceTabId.value, '')
  assert.equal(selectedContentItem.value, null)
  assert.deepEqual(events.find((event) => event[0] === 'undo').slice(1), [[
    { entry_type: 'folder', id: 'folder-root', name: '根目录' },
    { entry_type: 'content', id: 'content-free', name: '独立资料' },
  ], '已将 4 个项目移入回收站'])
})

test('restores local state and reports the original failure path when deletion fails', async () => {
  const failure = new Error('网络中断')
  const { controller, allContentItems, workspaceTabs, selectedContentItem, events } = createController({
    request: { delete: async () => { throw failure } },
  })

  await controller.deleteContentItem(allContentItems.value[0])

  assert.equal(allContentItems.value[0].id, 'content-root')
  assert.equal(workspaceTabs.value[0].id, 'tab-root')
  assert.equal(selectedContentItem.value.id, 'content-root')
  assert.deepEqual(events.at(-1), ['error', '网络中断'])
})

test('assigns stable fractional ordering to a multi-node move', async () => {
  const { controller, libraryFolders, allContentItems, calls, events } = createController()

  await controller.moveLibraryNodes({
    drags: [
      { type: 'folder', id: 'folder-root' },
      { type: 'content', id: 'content-free' },
    ],
    target: { type: 'folder', id: 'folder-target' },
    position: 'inside',
  })

  assert.equal(libraryFolders.value.find((folder) => folder.id === 'folder-root').sort_order, 1)
  assert.equal(allContentItems.value.find((item) => item.id === 'content-free').sort_order, 1.001)
  assert.deepEqual(calls, [
    ['patch', 'http://api.test/content/folders/folder-root', { parent_folder_id: 'folder-target', sort_order: 1 }, { timeout: 10000 }],
    ['patch', 'http://api.test/content/content-free', { library_folder_id: 'folder-target', sort_order: 1.001 }, { timeout: 10000 }],
  ])
  assert.equal(events.find((event) => event[0] === 'history')[1], '移动 2 个项目')
})
