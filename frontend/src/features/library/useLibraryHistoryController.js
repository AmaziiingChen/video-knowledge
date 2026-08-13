import { computed, ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLibraryHistoryController({
  libraryFolders,
  allContentItems,
  contentItems,
  selectedContentItem,
  workspaceTabs,
  activeWorkspaceTabId,
  updateLocalContentItem,
  loadContentItems,
  notify,
  request = axios,
  apiBase = API,
}) {
  const libraryUndoStack = ref([])
  const libraryRedoStack = ref([])
  const applyingLibraryHistory = ref(false)
  const canUndoLibraryAction = computed(() => libraryUndoStack.value.length > 0 && !applyingLibraryHistory.value)
  const canRedoLibraryAction = computed(() => libraryRedoStack.value.length > 0 && !applyingLibraryHistory.value)

  function snapshotLibraryState() {
    return {
      folders: libraryFolders.value.map((item) => ({ ...item })),
      allItems: allContentItems.value.map((item) => ({ ...item })),
      items: contentItems.value.map((item) => ({ ...item })),
      selectedId: selectedContentItem.value?.id || null,
      tabs: workspaceTabs.value.map((tab) => ({ ...tab })),
      activeTabId: activeWorkspaceTabId.value,
    }
  }

  function restoreLibraryState(snapshot) {
    libraryFolders.value = snapshot.folders
    allContentItems.value = snapshot.allItems
    contentItems.value = snapshot.items
    workspaceTabs.value = snapshot.tabs
    activeWorkspaceTabId.value = snapshot.activeTabId
    selectedContentItem.value = snapshot.selectedId
      ? allContentItems.value.find((item) => item.id === snapshot.selectedId) || null
      : null
  }

  function resetLibraryHistory() {
    libraryUndoStack.value = []
    libraryRedoStack.value = []
  }

  function recordLibraryHistory(label, before, after, nodes) {
    if (applyingLibraryHistory.value || !nodes.length) return
    libraryUndoStack.value = [...libraryUndoStack.value.slice(-19), { label, before, after, nodes }]
    libraryRedoStack.value = []
  }

  function discardLibraryHistoryForNodes(nodes) {
    const keys = new Set(nodes.map((node) => `${node.type}:${node.id}`))
    const keep = (command) => !command.nodes.some((node) => keys.has(`${node.type}:${node.id}`))
    libraryUndoStack.value = libraryUndoStack.value.filter(keep)
    libraryRedoStack.value = libraryRedoStack.value.filter(keep)
  }

  async function applyLibraryHistorySnapshot(command, snapshot) {
    for (const node of command.nodes) {
      if (node.type === 'folder') {
        const folder = snapshot.folders.find((candidate) => candidate.id === node.id)
        if (!folder) continue
        const res = await request.patch(`${apiBase}/content/folders/${node.id}`, {
          name: folder.name,
          parent_folder_id: folder.parent_folder_id || null,
          sort_order: Number(folder.sort_order || 0),
          is_pinned: Boolean(folder.is_pinned),
        }, { timeout: 10000 })
        libraryFolders.value = libraryFolders.value.map((current) => current.id === node.id ? res.data : current)
        continue
      }
      const item = snapshot.allItems.find((candidate) => candidate.id === node.id)
      if (!item) continue
      const res = await request.patch(`${apiBase}/content/${node.id}`, {
        title: item.title,
        library_folder_id: item.library_folder_id || null,
        sort_order: Number(item.sort_order || 0),
      }, { timeout: 10000 })
      updateLocalContentItem(node.id, () => res.data)
      workspaceTabs.value = workspaceTabs.value.map((tab) => tab.content_item_id === node.id ? { ...tab, title: res.data.title } : tab)
    }
  }

  async function undoLibraryAction() {
    if (!canUndoLibraryAction.value) return
    const command = libraryUndoStack.value.at(-1)
    applyingLibraryHistory.value = true
    try {
      await applyLibraryHistorySnapshot(command, command.before)
      libraryUndoStack.value = libraryUndoStack.value.slice(0, -1)
      libraryRedoStack.value = [...libraryRedoStack.value, command]
      notify.success(`已撤回：${command.label}`)
    } catch (error) {
      notify.error(error.response?.data?.detail || error.message || '撤回失败')
      await loadContentItems()
    } finally {
      applyingLibraryHistory.value = false
    }
  }

  async function redoLibraryAction() {
    if (!canRedoLibraryAction.value) return
    const command = libraryRedoStack.value.at(-1)
    applyingLibraryHistory.value = true
    try {
      await applyLibraryHistorySnapshot(command, command.after)
      libraryRedoStack.value = libraryRedoStack.value.slice(0, -1)
      libraryUndoStack.value = [...libraryUndoStack.value, command]
      notify.success(`已重做：${command.label}`)
    } catch (error) {
      notify.error(error.response?.data?.detail || error.message || '重做失败')
      await loadContentItems()
    } finally {
      applyingLibraryHistory.value = false
    }
  }

  function handleLibraryHistoryShortcut(event) {
    if (!(event.metaKey || event.ctrlKey) || String(event.key).toLowerCase() !== 'z') return
    if (event.target?.closest?.('input, textarea, [contenteditable="true"]')) return
    event.preventDefault()
    if (event.shiftKey) void redoLibraryAction()
    else void undoLibraryAction()
  }

  return {
    canUndoLibraryAction,
    canRedoLibraryAction,
    snapshotLibraryState,
    restoreLibraryState,
    resetLibraryHistory,
    recordLibraryHistory,
    discardLibraryHistoryForNodes,
    undoLibraryAction,
    redoLibraryAction,
    handleLibraryHistoryShortcut,
  }
}
