import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useLibraryTreeInteractionController } from './useLibraryTreeInteractionController.js'

const folderNode = (id) => ({ type: 'folder', id, raw: { id } })
const contentNode = (id, type = 'content') => ({ type, id, raw: { id } })

function createController({ nodes = [], folders = [], items = [], unread = [] } = {}) {
  const events = []
  const toggledFolders = []
  const toggledRoots = []
  const controller = useLibraryTreeInteractionController({
    visibleLibraryNodes: ref(nodes),
    libraryFolders: ref(folders),
    libraryContentItems: ref(items),
    unreadContentItems: ref(unread),
    toggleVirtualRoot: (node) => {
      if (!['unread-root', 'pinned-root'].includes(node.type)) return false
      toggledRoots.push(node.id)
      return true
    },
    toggleFolder: (folderId) => toggledFolders.push(folderId),
    emit: (...args) => events.push(args),
  })
  return { controller, events, toggledFolders, toggledRoots }
}

test('preserves ordinary, additive, and range selection semantics', () => {
  const nodes = [folderNode('a'), contentNode('one'), contentNode('two'), folderNode('b')]
  const { controller } = createController({ nodes })

  controller.updateSelection({}, nodes[1])
  assert.deepEqual([...controller.selectedKeys.value], ['content:one'])

  controller.updateSelection({ metaKey: true }, nodes[3])
  assert.deepEqual([...controller.selectedKeys.value], ['content:one', 'folder:b'])
  assert.equal(controller.anchorKey.value, 'folder:b')

  controller.updateSelection({ ctrlKey: true }, nodes[3])
  assert.deepEqual([...controller.selectedKeys.value], ['content:one'])
  assert.equal(controller.anchorKey.value, 'folder:b')

  controller.setAnchorKey('folder:a')
  controller.updateSelection({ shiftKey: true }, nodes[2])
  assert.deepEqual([...controller.selectedKeys.value], ['folder:a', 'content:one', 'content:two'])
  assert.equal(controller.anchorKey.value, 'folder:a')

  controller.setAnchorKey('missing')
  controller.updateSelection({ shiftKey: true }, nodes[1])
  assert.deepEqual([...controller.selectedKeys.value], ['content:one'])
  assert.equal(controller.anchorKey.value, 'content:one')
})

test('keeps a multi-selection for an already selected context node', () => {
  const nodes = [contentNode('one'), contentNode('two'), folderNode('a')]
  const { controller } = createController({ nodes })
  controller.setSelectedKeys(['content:one', 'content:two'])
  controller.setAnchorKey('content:two')

  controller.ensureContextSelection(nodes[0])
  assert.deepEqual([...controller.selectedKeys.value], ['content:one', 'content:two'])
  assert.equal(controller.anchorKey.value, 'content:two')

  controller.ensureContextSelection(nodes[2])
  assert.deepEqual([...controller.selectedKeys.value], ['folder:a'])
  assert.equal(controller.anchorKey.value, 'folder:a')
})

test('routes virtual roots, history rows, folders, and content through their existing actions', () => {
  const unreadRoot = { type: 'unread-root', id: '__unread__' }
  const history = { type: 'folder-history-more', id: 'history', parentId: 'folder', loading: false }
  const loadingHistory = { ...history, id: 'loading', loading: true }
  const folder = folderNode('folder')
  const unread = contentNode('unread', 'unread-content')
  const content = contentNode('content')
  const state = createController({ nodes: [unreadRoot, history, loadingHistory, folder, unread, content] })

  state.controller.setSelectedKeys(['content:content'])
  state.controller.activateNode({}, unreadRoot)
  state.controller.activateNode({}, history)
  state.controller.activateNode({}, loadingHistory)
  assert.deepEqual([...state.controller.selectedKeys.value], ['content:content'])

  state.controller.activateNode({}, folder)
  state.controller.activateNode({}, unread)
  state.controller.activateNode({}, content)

  assert.deepEqual(state.toggledRoots, ['__unread__'])
  assert.deepEqual(state.toggledFolders, ['folder'])
  assert.deepEqual(state.events, [
    ['load-folder-history', { folderId: 'folder', append: true }],
    ['open-content', unread.raw],
    ['open-content', content.raw],
  ])
  assert.deepEqual([...state.controller.selectedKeys.value], ['content:content'])
})

test('projects selected nodes and retains the draft key format', () => {
  const nodes = [contentNode('one'), contentNode('two', 'unread-content')]
  const { controller } = createController({ nodes })
  controller.setSelectedKeys(['content:one', 'unread-content:two'])

  assert.deepEqual(controller.selectedNodes.value, nodes)
  assert.deepEqual(controller.selectedContentNodes.value, nodes)
  assert.equal(controller.isNodeSelected(nodes[1]), true)
  assert.equal(controller.nodeKey({ type: 'draft-folder', id: 'new-folder:root' }), 'new-folder:root')
})

test('marks a folder subtree and the current unread projection as viewed', () => {
  const folders = [
    { id: 'root', parent_folder_id: null },
    { id: 'child', parent_folder_id: 'root' },
    { id: 'leaf', parent_folder_id: 'child' },
    { id: 'cycle-a', parent_folder_id: 'cycle-b' },
    { id: 'cycle-b', parent_folder_id: 'cycle-a' },
  ]
  const items = [
    { id: 'root-item', library_folder_id: 'root' },
    { id: 'leaf-item', library_folder_id: 'leaf' },
    { id: 'other-item', library_folder_id: 'cycle-a' },
  ]
  const state = createController({
    folders,
    items,
    unread: [{ id: 'unread-one' }, { id: null }, { id: 'unread-two' }],
  })

  state.controller.markFolderViewed({ id: 'root' })
  state.controller.markAllUnreadViewed()

  assert.deepEqual(state.events, [
    ['set-content-viewed', { contentItemIds: ['root-item', 'leaf-item'], viewed: true }],
    ['set-content-viewed', { contentItemIds: ['unread-one', 'unread-two'], viewed: true }],
  ])
})
