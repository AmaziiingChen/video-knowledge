import { computed, ref } from 'vue'

export function useLibraryTreeInteractionController({
  visibleLibraryNodes,
  libraryFolders,
  libraryContentItems,
  unreadContentItems,
  toggleVirtualRoot,
  toggleFolder,
  emit,
}) {
  const selectedKeys = ref(new Set())
  const anchorKey = ref(null)

  function isContentNode(node) {
    return ['content', 'unread-content'].includes(node?.type)
  }

  function isFolderHistoryNode(node) {
    return node?.type === 'folder-history-more'
  }

  function nodeKey(node) {
    if (node.type === 'draft-folder') return node.id
    return `${node.type}:${node.id}`
  }

  const selectedNodes = computed(() => {
    const selected = selectedKeys.value
    return visibleLibraryNodes.value.filter((node) => selected.has(nodeKey(node)))
  })

  const selectedContentNodes = computed(() => selectedNodes.value.filter(isContentNode))

  function isNodeSelected(node) {
    return selectedKeys.value.has(nodeKey(node))
  }

  function setSelectedKeys(keys) {
    selectedKeys.value = new Set(keys)
  }

  function setAnchorKey(key) {
    anchorKey.value = key
  }

  function selectRange(fromKey, toKey) {
    const keys = visibleLibraryNodes.value.map(nodeKey)
    const from = keys.indexOf(fromKey)
    const to = keys.indexOf(toKey)
    if (from === -1 || to === -1) {
      setSelectedKeys([toKey])
      anchorKey.value = toKey
      return
    }
    const [start, end] = from < to ? [from, to] : [to, from]
    setSelectedKeys(keys.slice(start, end + 1))
  }

  function updateSelection(event, node) {
    const key = nodeKey(node)
    if (event?.shiftKey && anchorKey.value) {
      selectRange(anchorKey.value, key)
      return
    }
    if (event?.metaKey || event?.ctrlKey) {
      const next = new Set(selectedKeys.value)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      setSelectedKeys(next)
      anchorKey.value = key
      return
    }
    setSelectedKeys([key])
    anchorKey.value = key
  }

  function activateNode(event, node) {
    if (toggleVirtualRoot(node)) return
    if (node.type === 'unread-content') {
      updateSelection(event, node)
      emit('open-content', node.raw)
      return
    }
    if (isFolderHistoryNode(node)) {
      if (!node.loading) emit('load-folder-history', { folderId: node.parentId, append: true })
      return
    }
    updateSelection(event, node)
    if (node.type === 'folder') {
      toggleFolder(node.id)
      return
    }
    emit('open-content', node.raw)
  }

  function ensureContextSelection(node) {
    const key = nodeKey(node)
    if (selectedKeys.value.has(key)) return
    setSelectedKeys([key])
    anchorKey.value = key
  }

  function markFolderViewed(folderNode) {
    const folderIds = new Set([String(folderNode.id)])
    let changed = true
    while (changed) {
      changed = false
      for (const folder of libraryFolders.value) {
        const parentId = folder.parent_folder_id ? String(folder.parent_folder_id) : ''
        if (parentId && folderIds.has(parentId) && !folderIds.has(String(folder.id))) {
          folderIds.add(String(folder.id))
          changed = true
        }
      }
    }
    const contentItemIds = libraryContentItems.value
      .filter((item) => folderIds.has(String(item?.library_folder_id || '')))
      .map((item) => item.id)
      .filter(Boolean)
    if (contentItemIds.length) emit('set-content-viewed', { contentItemIds, viewed: true })
  }

  function markAllUnreadViewed() {
    const contentItemIds = unreadContentItems.value.map((item) => item.id).filter(Boolean)
    if (contentItemIds.length) emit('set-content-viewed', { contentItemIds, viewed: true })
  }

  return {
    selectedKeys,
    anchorKey,
    selectedNodes,
    selectedContentNodes,
    isContentNode,
    isFolderHistoryNode,
    nodeKey,
    isNodeSelected,
    setSelectedKeys,
    setAnchorKey,
    updateSelection,
    activateNode,
    ensureContextSelection,
    markFolderViewed,
    markAllUnreadViewed,
  }
}
