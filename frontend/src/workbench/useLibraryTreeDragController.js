import { ref } from 'vue'

import {
  canDropOnUserSeparator,
  externalImportTargetFolderId,
  hasExternalFiles,
  libraryTreeDropPosition,
  separatorDropPosition,
} from '../features/library/libraryTreeDragPolicy.js'

export function useLibraryTreeDragController({
  searchActive,
  visibleLibraryNodes,
  selectedKeys,
  nodeKey,
  setSelectedKeys,
  setAnchorKey,
  libraryFolders,
  isMutableLibraryNode,
  sortOrderNearSeparator,
  moveUserSeparator,
  emit,
  cancelBoxSelection,
}) {
  const dragNode = ref(null)
  const dragNodes = ref([])
  const dropState = ref(null)

  function onDragStart(event, node) {
    if (searchActive.value) return
    if (node.type === 'user-group-separator') {
      dragNode.value = node
      dragNodes.value = []
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', '分割线')
      return
    }
    const key = nodeKey(node)
    if (!selectedKeys.value.has(key)) {
      setSelectedKeys([key])
      setAnchorKey(key)
    }
    dragNode.value = node
    dragNodes.value = visibleLibraryNodes.value.filter((item) => selectedKeys.value.has(nodeKey(item)))
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', dragNodes.value.map((item) => item.name).join(', '))
  }

  function handleNodeDragOver(event, node) {
    if (hasExternalFiles(event.dataTransfer)) {
      const folderId = externalImportTargetFolderId(node, libraryFolders.value)
      if (!folderId) return
      event.dataTransfer.dropEffect = 'copy'
      dropState.value = { targetType: node.type, targetId: node.id, position: 'inside' }
      return
    }
    if (node.type === 'user-group-separator') {
      onSeparatorDragOver(event, node)
    } else if (isMutableLibraryNode(node)) {
      onDragOver(event, node)
    }
  }

  function handleNodeDrop(event, node) {
    if (hasExternalFiles(event.dataTransfer)) {
      const files = Array.from(event.dataTransfer?.files || [])
      const libraryFolderId = externalImportTargetFolderId(node, libraryFolders.value)
      clearDragState()
      if (files.length && libraryFolderId) emit('import-markdown', { files, libraryFolderId })
      return
    }
    if (node.type === 'user-group-separator') {
      onSeparatorDrop(node)
    } else if (dragNode.value?.type === 'user-group-separator') {
      onSeparatorDropOnFolder(node)
    } else if (isMutableLibraryNode(node)) {
      onDrop(node)
    }
  }

  function onSeparatorDragOver(event, node) {
    if (searchActive.value || !dragNode.value || !canDropOnUserSeparator(dragNode.value, dragNodes.value)) return
    const rect = event.currentTarget.getBoundingClientRect()
    const position = separatorDropPosition({ clientY: event.clientY, rect })
    event.dataTransfer.dropEffect = 'move'
    dropState.value = { targetType: node.type, targetId: node.id, position }
  }

  function onSeparatorDrop(node) {
    if (searchActive.value || !dragNode.value || !dropState.value || !canDropOnUserSeparator(dragNode.value, dragNodes.value)) {
      clearDragState()
      return
    }
    if (dragNode.value.type === 'user-group-separator') {
      moveUserSeparator(dragNode.value.id, node, dropState.value.position)
      clearDragState()
      return
    }
    const sortOrder = sortOrderNearSeparator(node, dropState.value.position, dragNodes.value)
    emitMove({
      drag: dragNode.value,
      drags: dragNodes.value.length ? dragNodes.value : [dragNode.value],
      target: node,
      position: dropState.value.position,
      parentId: null,
      sortOrder,
    })
    clearDragState()
  }

  function onSeparatorDropOnFolder(target) {
    if (searchActive.value || !dragNode.value || !dropState.value || target.type !== 'folder' || target.depth !== 0) {
      clearDragState()
      return
    }
    moveUserSeparator(dragNode.value.id, target, dropState.value.position)
    clearDragState()
  }

  function onDragOver(event, node) {
    if (searchActive.value) return
    if (!dragNode.value || dragNodes.value.some((item) => item.type === node.type && item.id === node.id)) return
    if (dragNode.value.type === 'user-group-separator' && (node.type !== 'folder' || node.depth !== 0)) return
    const rect = event.currentTarget.getBoundingClientRect()
    const position = libraryTreeDropPosition({
      clientY: event.clientY,
      rect,
      node,
      dragNode: dragNode.value,
    })
    dropState.value = { targetType: node.type, targetId: node.id, position }
  }

  function onDrop(node) {
    if (searchActive.value) {
      clearDragState()
      return
    }
    if (!dragNode.value || !dropState.value) return
    emitMove({
      drag: dragNode.value,
      drags: dragNodes.value.length ? dragNodes.value : [dragNode.value],
      target: node,
      position: dropState.value.position,
    })
    clearDragState()
  }

  function emitMove(payload) {
    emit(payload.drags.length > 1 ? 'move-nodes' : 'move-node', payload)
  }

  function isDropTarget(node, position) {
    return dropState.value
      && dropState.value.targetType === node.type
      && dropState.value.targetId === node.id
      && dropState.value.position === position
  }

  function clearDropState() {
    dropState.value = null
  }

  function clearDragState() {
    dragNode.value = null
    dragNodes.value = []
    dropState.value = null
    cancelBoxSelection()
  }

  return {
    dragNode,
    dragNodes,
    dropState,
    onDragStart,
    handleNodeDragOver,
    handleNodeDrop,
    isDropTarget,
    clearDropState,
    clearDragState,
  }
}
