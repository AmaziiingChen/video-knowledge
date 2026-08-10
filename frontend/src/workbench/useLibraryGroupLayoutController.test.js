import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useLibraryGroupLayoutController } from './useLibraryGroupLayoutController.js'

const folder = (id, name, sortOrder, presentationGroup = '') => ({
  id,
  name,
  sort_order: sortOrder,
  presentation_group: presentationGroup,
})

function createController({
  folders = [],
  nodes = [],
  searching = false,
  preferences = { initialized: true, separators: [] },
} = {}) {
  const saved = []
  const libraryFolders = ref(folders)
  const visibleLibraryNodes = ref(nodes)
  const searchActive = ref(searching)
  const controller = useLibraryGroupLayoutController({
    libraryFolders,
    visibleLibraryNodes,
    searchActive,
    loadPreferences: () => preferences,
    savePreferences: (groups) => saved.push(groups.map((group) => ({ ...group }))),
    createDefaultSeparatorId: (index) => `default-${index}`,
    createUserSeparatorId: () => 'manual',
  })
  return { controller, saved, libraryFolders, visibleLibraryNodes, searchActive }
}

test('initializes default group boundaries once only when the saved layout is uninitialized', async () => {
  const folders = [
    folder('inbox', '待整理收藏', 10, 'manual:default'),
    folder('video', '抖音', 20, 'provider:douyin'),
    folder('wechat', '微信公众号', 30, 'provider:wechat'),
  ]
  const state = createController({
    folders,
    preferences: { initialized: false, separators: [] },
  })
  await nextTick()

  assert.deepEqual(state.saved, [[
    { id: 'default-0', sortOrder: 15 },
    { id: 'default-1', sortOrder: 25 },
  ]])

  state.libraryFolders.value = folders.map((item) => ({ ...item }))
  await nextTick()
  assert.equal(state.saved.length, 1)
})

test('keeps an explicitly initialized empty layout and hides separators while searching', () => {
  const nodes = [{ type: 'folder', id: 'one', depth: 0, sortOrder: 10 }]
  const empty = createController({ folders: [folder('one', '资料', 10)], nodes })
  assert.equal(empty.saved.length, 0)
  assert.deepEqual(empty.controller.presentationLibraryNodes.value, nodes)

  const state = createController({
    folders: [folder('one', '资料', 10)],
    nodes,
    searching: true,
    preferences: { initialized: true, separators: [{ id: 'saved', sortOrder: 5 }] },
  })
  assert.deepEqual(state.controller.presentationLibraryNodes.value, nodes)
})

test('migrates a legacy anchor and persists manual add, move, and delete operations', () => {
  const folders = [folder('one', '资料一', 10), folder('two', '资料二', 20)]
  const nodes = [
    { type: 'folder', id: 'one', depth: 0, sortOrder: 10 },
    { type: 'folder', id: 'two', depth: 0, sortOrder: 20 },
  ]
  const state = createController({
    folders,
    nodes,
    preferences: {
      initialized: true,
      separators: [{ id: 'legacy', sortOrder: null, beforeFolderId: 'two' }],
    },
  })
  assert.deepEqual(state.saved[0], [
    { id: 'legacy', sortOrder: 0, beforeFolderId: undefined },
  ])

  state.controller.addUserGroupSeparator(15)
  assert.deepEqual(state.saved.at(-1).at(-1), { id: 'manual', sortOrder: 15 })

  state.controller.moveUserSeparator('manual', nodes[0], 'before')
  assert.equal(state.saved.at(-1).find((group) => group.id === 'manual').sortOrder, 5)

  state.controller.removeUserGroupSeparator('manual')
  assert.equal(state.saved.at(-1).some((group) => group.id === 'manual'), false)
})

test('derives insertion and drag sort orders from the current rendered root layout', () => {
  const nodes = [
    { type: 'folder', id: 'one', depth: 0, sortOrder: 10 },
    { type: 'folder', id: 'two', depth: 0, sortOrder: 20 },
  ]
  const state = createController({
    folders: [folder('one', '资料一', 10), folder('two', '资料二', 20)],
    nodes,
    preferences: { initialized: true, separators: [{ id: 'middle', sortOrder: 15 }] },
  })
  const rendered = state.controller.presentationLibraryNodes.value
  const separator = rendered.find((node) => node.type === 'user-group-separator')

  assert.equal(state.controller.separatorSortOrderAt(1, rendered), 12.5)
  assert.equal(state.controller.sortOrderNearSeparator(separator, 'before'), 12.5)
  assert.equal(state.controller.sortOrderNearSeparator(separator, 'after'), 17.5)

  state.controller.addUserGroupSeparator(undefined)
  assert.deepEqual(state.saved.at(-1).at(-1), { id: 'manual', sortOrder: 21 })
})
