import { computed, ref, watch } from 'vue'
import {
  loadLibraryTreePreferences,
  saveLibraryTreePreferences,
} from '../features/library/libraryTreePreferences.js'
import {
  createDefaultSeparators,
  isRootLayoutNode,
  layoutSortOrder,
  migrateUserGroupSeparators,
  presentLibraryNodesWithSeparators,
  rootFolderNodes,
  separatorSortOrder,
  sortOrderBetween,
} from './libraryGroupLayout.js'

export function useLibraryGroupLayoutController({
  libraryFolders,
  visibleLibraryNodes,
  searchActive,
  loadPreferences = loadLibraryTreePreferences,
  savePreferences = saveLibraryTreePreferences,
  createDefaultSeparatorId = (index) => globalThis.crypto?.randomUUID?.() || `separator-${Date.now()}-${index}`,
  createUserSeparatorId = () => globalThis.crypto?.randomUUID?.() || `user-group-${Date.now()}`,
}) {
  const initialState = loadPreferences()
  const separators = ref(initialState.separators)
  const initialized = ref(initialState.initialized)

  const presentationLibraryNodes = computed(() => {
    if (searchActive.value || !separators.value.length) return visibleLibraryNodes.value
    return presentLibraryNodesWithSeparators(visibleLibraryNodes.value, separators.value)
  })

  function persist(nextSeparators) {
    separators.value = nextSeparators
    savePreferences(nextSeparators)
  }

  function rootLayoutEntries({ excludeFolderIds = new Set(), excludeSeparatorIds = new Set() } = {}) {
    const folders = visibleLibraryNodes.value.filter((node) => (
      node.type === 'folder' && node.depth === 0 && !excludeFolderIds.has(String(node.id))
    ))
    const separatorNodes = separators.value
      .filter((separator) => !excludeSeparatorIds.has(String(separator.id)))
      .map((separator) => ({
        type: 'user-group-separator',
        id: separator.id,
        sortOrder: separatorSortOrder(separator, rootFolderNodes(libraryFolders.value)),
        raw: separator,
      }))
    return [...folders, ...separatorNodes].sort((left, right) => (
      layoutSortOrder(left) - layoutSortOrder(right)
      || (left.type === right.type
        ? String(left.id).localeCompare(String(right.id))
        : left.type === 'user-group-separator' ? -1 : 1)
    ))
  }

  function separatorSortOrderAt(startIndex, renderedNodes) {
    const previous = [...renderedNodes.slice(0, startIndex)].reverse().find(isRootLayoutNode)
    const next = renderedNodes.slice(startIndex).find(isRootLayoutNode)
    return sortOrderBetween(previous, next)
  }

  function nextSeparatorSortOrder() {
    return sortOrderBetween(rootLayoutEntries().at(-1), null)
  }

  function sortOrderNearSeparator(separator, position, drags = []) {
    const excludedFolderIds = new Set(
      drags.filter((node) => node?.type === 'folder').map((node) => String(node.id)),
    )
    const entries = rootLayoutEntries({ excludeFolderIds: excludedFolderIds })
    const index = entries.findIndex((entry) => (
      entry.type === 'user-group-separator' && entry.id === separator.id
    ))
    if (index === -1) return nextSeparatorSortOrder()
    return position === 'before'
      ? sortOrderBetween(entries[index - 1], entries[index])
      : sortOrderBetween(entries[index], entries[index + 1])
  }

  function moveUserSeparator(separatorId, target, position) {
    const entries = rootLayoutEntries({ excludeSeparatorIds: new Set([String(separatorId)]) })
    const index = entries.findIndex((entry) => entry.type === target.type && entry.id === target.id)
    if (index === -1) return
    const sortOrder = position === 'before'
      ? sortOrderBetween(entries[index - 1], entries[index])
      : sortOrderBetween(entries[index], entries[index + 1])
    persist(separators.value.map((separator) => (
      String(separator.id) === String(separatorId)
        ? { ...separator, sortOrder, beforeFolderId: undefined }
        : separator
    )))
  }

  function addUserGroupSeparator(sortOrder) {
    const numericSortOrder = Number(sortOrder)
    persist([...separators.value, {
      id: createUserSeparatorId(),
      sortOrder: Number.isFinite(numericSortOrder) ? numericSortOrder : nextSeparatorSortOrder(),
    }])
  }

  function removeUserGroupSeparator(groupId) {
    if (!groupId) return
    persist(separators.value.filter((group) => group.id !== groupId))
  }

  watch(
    () => libraryFolders.value.map((folder) => (
      `${folder.id}:${folder.parent_folder_id || ''}:${folder.sort_order}:${folder.is_pinned ? 1 : 0}`
    )).join('|'),
    () => {
      const roots = rootFolderNodes(libraryFolders.value)
      if (!roots.length) return
      if (!initialized.value) {
        initialized.value = true
        persist(createDefaultSeparators(libraryFolders.value, createDefaultSeparatorId))
        return
      }
      const migrated = migrateUserGroupSeparators(separators.value, libraryFolders.value)
      if (migrated.some((separator, index) => (
        separator.sortOrder !== separators.value[index]?.sortOrder
        || separators.value[index]?.beforeFolderId
      ))) {
        persist(migrated)
      }
    },
    { immediate: true },
  )

  return {
    presentationLibraryNodes,
    separatorSortOrderAt,
    sortOrderNearSeparator,
    moveUserSeparator,
    addUserGroupSeparator,
    removeUserGroupSeparator,
  }
}
