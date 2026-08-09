import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useLibraryHistoryController } from './useLibraryHistoryController.js'

function createController({ request = {} } = {}) {
  const libraryFolders = ref([{ id: 'folder-1', name: '旧文件夹', parent_folder_id: null, sort_order: 0, is_pinned: false }])
  const allContentItems = ref([{ id: 'content-1', title: '旧标题', library_folder_id: null, sort_order: 0 }])
  const contentItems = ref([...allContentItems.value])
  const selectedContentItem = ref(allContentItems.value[0])
  const workspaceTabs = ref([{ id: 'tab-1', content_item_id: 'content-1', title: '旧标题' }])
  const activeWorkspaceTabId = ref('tab-1')
  const successes = []
  const errors = []
  let refreshes = 0
  const controller = useLibraryHistoryController({
    libraryFolders,
    allContentItems,
    contentItems,
    selectedContentItem,
    workspaceTabs,
    activeWorkspaceTabId,
    updateLocalContentItem: (id, updater) => {
      allContentItems.value = allContentItems.value.map((item) => item.id === id ? updater(item) : item)
      contentItems.value = [...allContentItems.value]
      selectedContentItem.value = allContentItems.value.find((item) => item.id === selectedContentItem.value?.id) || null
    },
    loadContentItems: async () => { refreshes += 1 },
    notify: { success: (message) => successes.push(message), error: (message) => errors.push(message) },
    request: { patch: async () => ({ data: {} }), ...request },
    apiBase: 'http://api.test',
  })
  return {
    controller,
    libraryFolders,
    allContentItems,
    contentItems,
    selectedContentItem,
    workspaceTabs,
    successes,
    errors,
    refreshes: () => refreshes,
  }
}

test('records at most twenty commands and clears redo after a new action', async () => {
  let patches = 0
  const { controller } = createController({ request: { patch: async () => { patches += 1; return { data: {} } } } })
  const snapshot = controller.snapshotLibraryState()
  for (let index = 0; index < 21; index += 1) {
    controller.recordLibraryHistory(`action-${index}`, snapshot, snapshot, [{ type: 'content', id: 'content-1' }])
  }

  assert.equal(controller.canUndoLibraryAction.value, true)
  for (let index = 0; index < 21; index += 1) await controller.undoLibraryAction()
  assert.equal(patches, 20)
  assert.equal(controller.canUndoLibraryAction.value, false)
  assert.equal(controller.canRedoLibraryAction.value, true)
  controller.recordLibraryHistory('new action', snapshot, snapshot, [{ type: 'content', id: 'content-1' }])
  assert.equal(controller.canRedoLibraryAction.value, false)
})

test('undo restores content through the existing API and rewrites tab titles', async () => {
  const patches = []
  const { controller, allContentItems, workspaceTabs, successes } = createController({
    request: {
      patch: async (...args) => {
        patches.push(args)
        return { data: { id: 'content-1', title: '旧标题', library_folder_id: null, sort_order: 0 } }
      },
    },
  })
  const before = controller.snapshotLibraryState()
  allContentItems.value = [{ ...allContentItems.value[0], title: '新标题' }]
  workspaceTabs.value = [{ ...workspaceTabs.value[0], title: '新标题' }]
  const after = controller.snapshotLibraryState()
  controller.recordLibraryHistory('重命名内容', before, after, [{ type: 'content', id: 'content-1' }])

  await controller.undoLibraryAction()
  assert.deepEqual(patches, [[
    'http://api.test/content/content-1',
    { title: '旧标题', library_folder_id: null, sort_order: 0 },
    { timeout: 10000 },
  ]])
  assert.equal(allContentItems.value[0].title, '旧标题')
  assert.equal(workspaceTabs.value[0].title, '旧标题')
  assert.equal(controller.canUndoLibraryAction.value, false)
  assert.equal(controller.canRedoLibraryAction.value, true)
  assert.deepEqual(successes, ['已撤回：重命名内容'])
})

test('failed undo keeps the command available and reloads the canonical list', async () => {
  const { controller, errors, refreshes } = createController({
    request: { patch: async () => { throw new Error('网络不可用') } },
  })
  const snapshot = controller.snapshotLibraryState()
  controller.recordLibraryHistory('移动项目', snapshot, snapshot, [{ type: 'folder', id: 'folder-1' }])
  await controller.undoLibraryAction()
  assert.deepEqual(errors, ['网络不可用'])
  assert.equal(refreshes(), 1)
  assert.equal(controller.canUndoLibraryAction.value, true)
})

test('keyboard shortcuts preserve editable fields and map shifted Z to redo', async () => {
  const { controller } = createController()
  const snapshot = controller.snapshotLibraryState()
  controller.recordLibraryHistory('重命名内容', snapshot, snapshot, [])
  let prevented = false
  controller.handleLibraryHistoryShortcut({
    metaKey: true,
    key: 'z',
    target: { closest: () => true },
    preventDefault: () => { prevented = true },
  })
  assert.equal(prevented, false)

  controller.recordLibraryHistory('重命名内容', snapshot, snapshot, [{ type: 'content', id: 'missing' }])
  controller.handleLibraryHistoryShortcut({
    ctrlKey: true,
    shiftKey: false,
    key: 'z',
    target: { closest: () => false },
    preventDefault: () => { prevented = true },
  })
  await Promise.resolve()
  assert.equal(prevented, true)
  assert.equal(controller.canRedoLibraryAction.value, true)
  controller.handleLibraryHistoryShortcut({
    ctrlKey: true,
    shiftKey: true,
    key: 'z',
    target: { closest: () => false },
    preventDefault: () => {},
  })
  await Promise.resolve()
  assert.equal(controller.canUndoLibraryAction.value, true)
  assert.equal(controller.canRedoLibraryAction.value, false)
})
