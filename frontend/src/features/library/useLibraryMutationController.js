import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLibraryMutationController({
  libraryFolders,
  allContentItems,
  workspaceTabs,
  activeWorkspaceTabId,
  selectedContentItem,
  snapshotLibraryState,
  restoreLibraryState,
  recordLibraryHistory,
  discardLibraryHistoryForNodes,
  resetMarkdownState,
  applyContentFilter,
  updateLocalContentItem,
  loadLibraryTrash,
  showTrashUndoMessage,
  request = axios,
  apiBase = API,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  function descendantFolderIds(folderId) {
    const ids = new Set([folderId])
    let changed = true
    while (changed) {
      changed = false
      for (const folder of libraryFolders.value) {
        if (folder.parent_folder_id && ids.has(folder.parent_folder_id) && !ids.has(folder.id)) {
          ids.add(folder.id)
          changed = true
        }
      }
    }
    return ids
  }

  function isDescendantFolder(candidateId, parentId) {
    return descendantFolderIds(parentId).has(candidateId)
  }

  function siblingNodes(parentId) {
    const normalizedParent = parentId || null
    return [
      ...libraryFolders.value
        .filter((folder) => (folder.parent_folder_id || null) === normalizedParent)
        .map((folder) => ({ ...folder, kind: 'folder' })),
      ...allContentItems.value
        .filter((item) => (item.library_folder_id || null) === normalizedParent)
        .map((item) => ({ ...item, kind: 'content' })),
    ]
  }

  function nextSortOrder(parentId) {
    const orders = siblingNodes(parentId).map((node) => Number(node.sort_order || 0))
    return orders.length ? Math.max(...orders) + 1 : 1
  }

  function sortOrderForDrop(parentId, target, position) {
    if (position === 'inside') return nextSortOrder(parentId)
    const siblings = siblingNodes(parentId)
      .filter((node) => !(node.kind === target.type && node.id === target.id))
      .sort((left, right) => Number(left.sort_order || 0) - Number(right.sort_order || 0))
    const targetOrder = Number(target.sortOrder || 0)
    const before = siblings.filter((node) => Number(node.sort_order || 0) < targetOrder).at(-1)
    const after = siblings.find((node) => Number(node.sort_order || 0) > targetOrder)
    if (position === 'before') {
      return before ? (Number(before.sort_order || 0) + targetOrder) / 2 : targetOrder - 1
    }
    return after ? (targetOrder + Number(after.sort_order || 0)) / 2 : targetOrder + 1
  }

  function closeDeletedTabs(deletedItemIds) {
    workspaceTabs.value = workspaceTabs.value.filter((tab) => !deletedItemIds.has(tab.content_item_id))
    if (selectedContentItem.value && deletedItemIds.has(selectedContentItem.value.id)) {
      selectedContentItem.value = null
      resetMarkdownState()
    }
    if (!workspaceTabs.value.some((tab) => tab.id === activeWorkspaceTabId.value)) {
      activeWorkspaceTabId.value = workspaceTabs.value[0]?.id || ''
    }
  }

  async function deleteLibraryFolder(folder) {
    const snapshot = snapshotLibraryState()
    const folderIds = descendantFolderIds(folder.id)
    const deletedItemIds = new Set(allContentItems.value
      .filter((item) => folderIds.has(item.library_folder_id))
      .map((item) => item.id))
    libraryFolders.value = libraryFolders.value.filter((item) => !folderIds.has(item.id))
    allContentItems.value = allContentItems.value.filter((item) => !deletedItemIds.has(item.id))
    applyContentFilter()
    closeDeletedTabs(deletedItemIds)
    try {
      await request.delete(`${apiBase}/content/folders/${folder.id}`, { timeout: 10000 })
      discardLibraryHistoryForNodes([
        ...[...folderIds].map((id) => ({ type: 'folder', id })),
        ...[...deletedItemIds].map((id) => ({ type: 'content', id })),
      ])
      await loadLibraryTrash()
      showTrashUndoMessage([
        { entry_type: 'folder', id: folder.id, name: folder.name },
      ], '已移入回收站')
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '删除失败')
    }
  }

  async function renameContentItem(payload) {
    const snapshot = snapshotLibraryState()
    const currentItem = snapshot.allItems.find((item) => item.id === payload.id)
    if (!currentItem || currentItem.title === payload.title) return
    updateLocalContentItem(payload.id, (item) => ({ ...item, title: payload.title }))
    workspaceTabs.value = workspaceTabs.value.map((tab) => (
      tab.content_item_id === payload.id ? { ...tab, title: payload.title } : tab
    ))
    try {
      const response = await request.patch(`${apiBase}/content/${payload.id}`, {
        title: payload.title,
      }, { timeout: 10000 })
      updateLocalContentItem(payload.id, () => response.data)
      recordLibraryHistory('重命名内容', snapshot, snapshotLibraryState(), [{ type: 'content', id: payload.id }])
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '重命名失败')
    }
  }

  async function deleteContentItem(item) {
    const snapshot = snapshotLibraryState()
    const deletedIds = new Set([item.id])
    allContentItems.value = allContentItems.value.filter((current) => current.id !== item.id)
    applyContentFilter()
    closeDeletedTabs(deletedIds)
    try {
      await request.delete(`${apiBase}/content/${item.id}`, { timeout: 10000 })
      discardLibraryHistoryForNodes([{ type: 'content', id: item.id }])
      await loadLibraryTrash()
      showTrashUndoMessage([
        { entry_type: 'content', id: item.id, name: item.title },
      ], '已移入回收站')
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '删除失败')
    }
  }

  async function deleteLibraryNodes(nodes) {
    if (!Array.isArray(nodes) || !nodes.length) return
    const snapshot = snapshotLibraryState()
    const selectedFolders = nodes.filter((node) => node.type === 'folder')
    const selectedContents = nodes.filter((node) => node.type === 'content')
    const folderIds = new Set()
    selectedFolders.forEach((folder) => {
      descendantFolderIds(folder.id).forEach((id) => folderIds.add(id))
    })
    const deletedItemIds = new Set(selectedContents.map((item) => item.id))
    allContentItems.value.forEach((item) => {
      if (folderIds.has(item.library_folder_id)) deletedItemIds.add(item.id)
    })

    libraryFolders.value = libraryFolders.value.filter((folder) => !folderIds.has(folder.id))
    allContentItems.value = allContentItems.value.filter((item) => !deletedItemIds.has(item.id))
    applyContentFilter()
    closeDeletedTabs(deletedItemIds)

    const topFolders = selectedFolders.filter((folder) => {
      let parentId = snapshot.folders.find((candidate) => candidate.id === folder.id)?.parent_folder_id || null
      while (parentId) {
        if (selectedFolders.some((candidate) => candidate.id === parentId)) return false
        parentId = snapshot.folders.find((candidate) => candidate.id === parentId)?.parent_folder_id || null
      }
      return true
    })
    const contentIdsInDeletedFolders = new Set()
    snapshot.allItems.forEach((item) => {
      if (folderIds.has(item.library_folder_id)) contentIdsInDeletedFolders.add(item.id)
    })
    const directlyDeletedContents = selectedContents.filter((item) => !contentIdsInDeletedFolders.has(item.id))

    try {
      for (const folder of topFolders) {
        await request.delete(`${apiBase}/content/folders/${folder.id}`, { timeout: 10000 })
      }
      for (const item of directlyDeletedContents) {
        await request.delete(`${apiBase}/content/${item.id}`, { timeout: 10000 })
      }
      await loadLibraryTrash()
      discardLibraryHistoryForNodes([
        ...[...folderIds].map((id) => ({ type: 'folder', id })),
        ...[...deletedItemIds].map((id) => ({ type: 'content', id })),
      ])
      showTrashUndoMessage([
        ...topFolders.map((folder) => ({ entry_type: 'folder', id: folder.id, name: folder.name })),
        ...directlyDeletedContents.map((item) => ({ entry_type: 'content', id: item.id, name: item.title })),
      ], `已将 ${nodes.length} 个项目移入回收站`)
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '删除失败')
    }
  }

  async function moveLibraryNode(payload) {
    if (Array.isArray(payload?.drags) && payload.drags.length > 1) {
      await moveLibraryNodes(payload)
      return
    }
    const drag = payload.drag
    const target = payload.target
    if (!drag || !target || (drag.type === target.type && drag.id === target.id)) return
    if (drag.type === 'folder' && target.type === 'folder' && isDescendantFolder(target.id, drag.id)) {
      notify.warning('不能移动到自身或子文件夹')
      return
    }

    const snapshot = snapshotLibraryState()
    const parentId = Object.prototype.hasOwnProperty.call(payload, 'parentId')
      ? payload.parentId
      : payload.position === 'inside' && target.type === 'folder'
        ? target.id
        : target.parentId || null
    const requestedSortOrder = Number(payload.sortOrder)
    const sortOrder = Number.isFinite(requestedSortOrder)
      ? requestedSortOrder
      : sortOrderForDrop(parentId, target, payload.position)

    if (drag.type === 'folder') {
      libraryFolders.value = libraryFolders.value.map((folder) => {
        return folder.id === drag.id
          ? { ...folder, parent_folder_id: parentId, sort_order: sortOrder }
          : folder
      })
    } else {
      updateLocalContentItem(drag.id, (item) => ({ ...item, library_folder_id: parentId, sort_order: sortOrder }))
    }

    try {
      if (drag.type === 'folder') {
        await request.patch(`${apiBase}/content/folders/${drag.id}`, {
          parent_folder_id: parentId,
          sort_order: sortOrder,
        }, { timeout: 10000 })
      } else {
        await request.patch(`${apiBase}/content/${drag.id}`, {
          library_folder_id: parentId,
          sort_order: sortOrder,
        }, { timeout: 10000 })
      }
      recordLibraryHistory('移动项目', snapshot, snapshotLibraryState(), [{ type: drag.type, id: drag.id }])
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '移动失败')
    }
  }

  async function moveLibraryNodes(payload) {
    const drags = Array.isArray(payload?.drags) ? payload.drags : []
    const target = payload?.target
    if (!drags.length || !target) return
    const snapshot = snapshotLibraryState()
    const validDrags = drags.filter((drag) => {
      if (drag.type === target.type && drag.id === target.id) return false
      if (drag.type === 'folder' && target.type === 'folder' && isDescendantFolder(target.id, drag.id)) return false
      return true
    })
    if (!validDrags.length) return

    const parentId = Object.prototype.hasOwnProperty.call(payload, 'parentId')
      ? payload.parentId
      : payload.position === 'inside' && target.type === 'folder'
        ? target.id
        : target.parentId || null
    const requestedSortOrder = Number(payload.sortOrder)
    const baseSortOrder = Number.isFinite(requestedSortOrder)
      ? requestedSortOrder
      : sortOrderForDrop(parentId, target, payload.position)

    validDrags.forEach((drag, index) => {
      const sortOrder = baseSortOrder + index * 0.001
      if (drag.type === 'folder') {
        libraryFolders.value = libraryFolders.value.map((folder) => {
          return folder.id === drag.id
            ? { ...folder, parent_folder_id: parentId, sort_order: sortOrder }
            : folder
        })
      } else {
        updateLocalContentItem(drag.id, (item) => ({ ...item, library_folder_id: parentId, sort_order: sortOrder }))
      }
    })

    try {
      for (const [index, drag] of validDrags.entries()) {
        const sortOrder = baseSortOrder + index * 0.001
        if (drag.type === 'folder') {
          await request.patch(`${apiBase}/content/folders/${drag.id}`, {
            parent_folder_id: parentId,
            sort_order: sortOrder,
          }, { timeout: 10000 })
        } else {
          await request.patch(`${apiBase}/content/${drag.id}`, {
            library_folder_id: parentId,
            sort_order: sortOrder,
          }, { timeout: 10000 })
        }
      }
      recordLibraryHistory(`移动 ${validDrags.length} 个项目`, snapshot, snapshotLibraryState(), validDrags.map((drag) => ({ type: drag.type, id: drag.id })))
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '移动失败')
    }
  }

  return {
    deleteLibraryFolder,
    renameContentItem,
    deleteContentItem,
    deleteLibraryNodes,
    moveLibraryNode,
    moveLibraryNodes,
    nextSortOrder,
  }
}
