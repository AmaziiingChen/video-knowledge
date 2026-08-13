import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useLibraryTreeDragController } from './useLibraryTreeDragController.js'

function dataTransfer({ files = [], types = [] } = {}) {
  return {
    files,
    types,
    dropEffect: '',
    effectAllowed: '',
    values: [],
    setData(type, value) { this.values.push([type, value]) },
  }
}

function dragEvent(options = {}) {
  return {
    clientY: 150,
    dataTransfer: dataTransfer(options),
    currentTarget: { getBoundingClientRect: () => ({ top: 100, height: 100 }) },
  }
}

function createController({ nodes = [], folders = [], search = false } = {}) {
  const events = []
  const selectedKeys = ref(new Set())
  const searchActive = ref(search)
  const cancelledSelections = []
  const separatorMoves = []
  const controller = useLibraryTreeDragController({
    searchActive,
    visibleLibraryNodes: ref(nodes),
    selectedKeys,
    nodeKey: (node) => `${node.type}:${node.id}`,
    setSelectedKeys: (keys) => { selectedKeys.value = new Set(keys) },
    setAnchorKey: () => {},
    libraryFolders: ref(folders),
    isMutableLibraryNode: (node) => ['folder', 'content'].includes(node?.type),
    sortOrderNearSeparator: () => 42,
    moveUserSeparator: (...args) => separatorMoves.push(args),
    emit: (...args) => events.push(args),
    cancelBoxSelection: () => cancelledSelections.push(true),
  })
  return { controller, events, selectedKeys, searchActive, cancelledSelections, separatorMoves }
}

test('imports external files only into the external-import tree branch', () => {
  const folders = [
    { id: 'imports', name: '外部导入' },
    { id: 'child', name: '项目资料', parent_folder_id: 'imports' },
    { id: 'other', name: '其他资料' },
  ]
  const { controller, events, cancelledSelections } = createController({ folders })
  const file = { name: 'notes.md' }
  const allowed = dragEvent({ files: [file], types: ['Files'] })
  controller.handleNodeDragOver(allowed, { type: 'folder', id: 'child' })
  assert.equal(allowed.dataTransfer.dropEffect, 'copy')
  assert.equal(controller.isDropTarget({ type: 'folder', id: 'child' }, 'inside'), true)
  controller.handleNodeDrop(allowed, { type: 'folder', id: 'child' })
  assert.deepEqual(events, [['import-markdown', { files: [file], libraryFolderId: 'child' }]])
  assert.equal(cancelledSelections.length, 1)

  const rejected = dragEvent({ files: [file], types: ['Files'] })
  controller.handleNodeDragOver(rejected, { type: 'folder', id: 'other' })
  controller.handleNodeDrop(rejected, { type: 'folder', id: 'other' })
  assert.equal(rejected.dataTransfer.dropEffect, '')
  assert.equal(events.length, 1)
})

test('preserves multi-node moves and separator sort-order transactions', () => {
  const rootA = { type: 'folder', id: 'a', name: 'A', depth: 0 }
  const rootB = { type: 'folder', id: 'b', name: 'B', depth: 0 }
  const separator = { type: 'user-group-separator', id: 'separator', name: '', depth: 0 }
  const { controller, events, selectedKeys, separatorMoves, cancelledSelections } = createController({ nodes: [rootA, rootB] })
  selectedKeys.value = new Set(['folder:a', 'folder:b'])
  controller.onDragStart(dragEvent(), rootA)
  controller.handleNodeDragOver(dragEvent(), separator)
  controller.handleNodeDrop(dragEvent(), separator)
  assert.deepEqual(events, [['move-nodes', {
    drag: rootA,
    drags: [rootA, rootB],
    target: separator,
    position: 'after',
    parentId: null,
    sortOrder: 42,
  }]])
  assert.equal(cancelledSelections.length, 1)

  controller.onDragStart(dragEvent(), separator)
  controller.handleNodeDragOver(dragEvent(), rootA)
  controller.handleNodeDrop(dragEvent(), rootA)
  assert.deepEqual(separatorMoves, [['separator', rootA, 'after']])
  assert.equal(cancelledSelections.length, 2)
})

test('does not create a move from a self-drop or a search-mode drop, and resets state on drag end', () => {
  const node = { type: 'content', id: 'one', name: 'One', depth: 1 }
  const target = { type: 'folder', id: 'target', name: 'Target', depth: 0 }
  const { controller, events, selectedKeys, searchActive, cancelledSelections } = createController({ nodes: [node, target] })
  selectedKeys.value = new Set(['content:one'])
  controller.onDragStart(dragEvent(), node)
  controller.handleNodeDragOver(dragEvent(), node)
  controller.handleNodeDrop(dragEvent(), node)
  assert.deepEqual(events, [])
  controller.clearDragState()
  assert.equal(controller.dragNode.value, null)
  assert.equal(cancelledSelections.length, 1)

  controller.onDragStart(dragEvent(), node)
  controller.handleNodeDragOver(dragEvent(), target)
  searchActive.value = true
  controller.handleNodeDrop(dragEvent(), target)
  assert.deepEqual(events, [])
  assert.equal(controller.dragNode.value, null)
  assert.equal(cancelledSelections.length, 2)
})
