import { nextTick, ref, watch } from 'vue'
import {
  loadOpenFolderIds as loadSavedOpenFolderIds,
  saveOpenFolderIds as saveSavedOpenFolderIds,
} from '../features/library/libraryTreePreferences.js'

export function useLibraryOpenFolderController({
  libraryFolders,
  folderHistoryStates,
  revealedLibraryFolderIds,
  folderUnreadCounts,
  emit,
  loadOpenFolderIds = loadSavedOpenFolderIds,
  saveOpenFolderIds = saveSavedOpenFolderIds,
}) {
  const openFolderIds = ref(loadOpenFolderIds())
  const unreadRootOpen = ref(false)
  const pinnedRootOpen = ref(true)
  const requestedThisFlush = new Set()

  function persistOpenFolderIds(folderIds) {
    saveOpenFolderIds(folderIds)
  }

  function folderHistoryState(folderId) {
    return folderHistoryStates.value[String(folderId)] || null
  }

  function ensureFolderItemsLoaded(folderId) {
    const id = String(folderId || '')
    if (!id) return
    const page = folderHistoryState(id)
    if (!page?.loaded && !page?.loading && !requestedThisFlush.has(id)) {
      requestedThisFlush.add(id)
      emit('load-folder-history', { folderId: id, append: false })
      nextTick(() => requestedThisFlush.delete(id))
    }
  }

  function isFolderOpen(id) {
    return openFolderIds.value.has(String(id))
  }

  function isNodeOpen(node) {
    if (node?.type === 'unread-root') return unreadRootOpen.value
    if (node?.type === 'pinned-root') return pinnedRootOpen.value
    return isFolderOpen(node?.id)
  }

  function toggleVirtualRoot(node) {
    if (node?.type === 'unread-root') {
      unreadRootOpen.value = !unreadRootOpen.value
      return true
    }
    if (node?.type === 'pinned-root') {
      pinnedRootOpen.value = !pinnedRootOpen.value
      return true
    }
    return false
  }

  function toggleFolder(id) {
    const folderId = String(id)
    const open = new Set(openFolderIds.value)
    const opening = !open.has(folderId)
    if (!opening) {
      open.delete(folderId)
    } else {
      open.add(folderId)
    }
    openFolderIds.value = open
    if (opening) ensureFolderItemsLoaded(folderId)
    persistOpenFolderIds(open)
  }

  function revealLibraryFolders(folderIds) {
    const foldersById = new Map(libraryFolders.value.map((folder) => [String(folder.id), folder]))
    const open = new Set(openFolderIds.value)
    let changed = false
    for (const rawId of folderIds || []) {
      let folderId = String(rawId || '')
      const visited = new Set()
      while (folderId && foldersById.has(folderId) && !visited.has(folderId)) {
        visited.add(folderId)
        if (!open.has(folderId)) {
          open.add(folderId)
          changed = true
        }
        folderId = foldersById.get(folderId)?.parent_folder_id
          ? String(foldersById.get(folderId).parent_folder_id)
          : ''
      }
    }
    if (changed) {
      openFolderIds.value = open
      persistOpenFolderIds(open)
    }
  }

  function expandUnreadInNode(node) {
    if (!node?.unreadCount) return
    if (node.type === 'unread-root') {
      unreadRootOpen.value = !unreadRootOpen.value
      return
    }
    if (node.type !== 'folder') return
    const open = new Set(openFolderIds.value)
    const rootId = String(node.id)
    const foldersById = new Map(libraryFolders.value.map((folder) => [String(folder.id), folder]))
    for (const folder of libraryFolders.value) {
      const folderId = String(folder.id)
      if (!(folderUnreadCounts.value.get(folderId) || 0)) continue
      let currentId = folderId
      const visited = new Set()
      while (currentId && !visited.has(currentId)) {
        visited.add(currentId)
        if (currentId === rootId) {
          open.add(folderId)
          break
        }
        currentId = foldersById.get(currentId)?.parent_folder_id
          ? String(foldersById.get(currentId).parent_folder_id)
          : ''
      }
    }
    openFolderIds.value = open
    persistOpenFolderIds(open)
  }

  watch(
    revealedLibraryFolderIds,
    (folderIds) => revealLibraryFolders(folderIds),
    { immediate: true, deep: true },
  )

  // Restore only explicitly open branches, then hydrate each branch through
  // the existing lazy loader instead of requesting a global article page.
  watch(
    [
      () => libraryFolders.value.map((folder) => String(folder.id)).join('|'),
      () => [...openFolderIds.value].sort().join('|'),
    ],
    () => {
      const knownFolderIds = new Set(libraryFolders.value.map((folder) => String(folder.id)))
      for (const folderId of openFolderIds.value) {
        if (knownFolderIds.has(String(folderId))) ensureFolderItemsLoaded(folderId)
      }
    },
    { immediate: true },
  )

  return {
    openFolderIds,
    persistOpenFolderIds,
    folderHistoryState,
    isFolderOpen,
    isNodeOpen,
    toggleVirtualRoot,
    toggleFolder,
    expandUnreadInNode,
  }
}
