function isContentItem(node) {
  return Boolean(node && ('source_provider' in node || 'content_type' in node || 'canonical_source_id' in node))
}

function recentTimestamp(item) {
  const value = item?.published_at || item?.created_at || item?.updated_at || ''
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : 0
}

export function displayLibraryContentName(item) {
  const title = String(item?.title || '').trim()
  if (title) return title
  const identity = String(item?.canonical_source_id || '').trim()
  if (identity) return identity
  return '未命名内容'
}

export function unreadFolderCounts({
  libraryFolders = [],
  libraryContentItems = [],
  isUnreadContent = () => false,
}) {
  const foldersById = new Map(libraryFolders.map((folder) => [String(folder.id), folder]))
  const counts = new Map(libraryFolders.map((folder) => [String(folder.id), 0]))
  for (const item of libraryContentItems) {
    if (!isUnreadContent(item)) continue
    let folderId = item?.library_folder_id ? String(item.library_folder_id) : ''
    const visited = new Set()
    while (folderId && foldersById.has(folderId) && !visited.has(folderId)) {
      visited.add(folderId)
      counts.set(folderId, (counts.get(folderId) || 0) + 1)
      folderId = foldersById.get(folderId)?.parent_folder_id
        ? String(foldersById.get(folderId).parent_folder_id)
        : ''
    }
  }
  return counts
}

export function libraryFolderPaths(libraryFolders = []) {
  const folders = new Map(libraryFolders.map((folder) => [folder.id, folder]))
  const paths = new Map()
  const resolve = (folderId, visiting = new Set()) => {
    if (!folderId || visiting.has(folderId)) return ''
    if (paths.has(folderId)) return paths.get(folderId)
    const folder = folders.get(folderId)
    if (!folder) return ''
    visiting.add(folderId)
    const parentPath = resolve(folder.parent_folder_id || null, visiting)
    visiting.delete(folderId)
    const path = parentPath ? `${parentPath} / ${folder.name}` : folder.name
    paths.set(folderId, path)
    return path
  }
  for (const folderId of folders.keys()) resolve(folderId)
  return paths
}

export function libraryTreeNodeTitle(node, folderPaths = new Map()) {
  if (!node) return ''
  if (node.type === 'unread-content') {
    const source = folderPaths.get(node.raw?.library_folder_id) || node.raw?.source_name || '资料库'
    return `${node.name}\n${source}`
  }
  const source = [node.raw?.source_name, node.raw?.source_section].filter(Boolean).join(' · ')
  return source ? `${node.name}\n${source}` : node.name || ''
}

export function sortLibraryNodes(nodes) {
  return [...nodes].sort((left, right) => {
    if (isContentItem(left) || isContentItem(right)) {
      return recentTimestamp(right) - recentTimestamp(left)
        || String(right.created_at || '').localeCompare(String(left.created_at || ''))
        || String(left.title || left.name || '').localeCompare(String(right.title || right.name || ''))
    }
    return Number(left.sort_order || 0) - Number(right.sort_order || 0)
      || String(right.created_at || '').localeCompare(String(left.created_at || ''))
      || String(left.title || left.name || '').localeCompare(String(right.title || right.name || ''))
  })
}

export function compareLibraryTreeNodes(left, right) {
  if (left.type === 'content' && right.type === 'content') {
    return recentTimestamp(right.raw) - recentTimestamp(left.raw)
      || left.name.localeCompare(right.name)
  }
  return left.sortOrder - right.sortOrder
    || (left.type === right.type ? 0 : left.type === 'folder' ? -1 : 1)
    || left.name.localeCompare(right.name)
}

export function buildLibraryTreeNodes({
  searchActive,
  libraryFolders = [],
  sidebarTreeItems = [],
  unreadContentItems = [],
  isUnreadContent,
  isNodeOpen,
  isFolderOpen,
  folderHistoryState = () => null,
  folderContentCounts = new Map(),
  folderUnreadCounts = new Map(),
}) {
  if (searchActive) {
    return sidebarTreeItems.map((item) => ({
      type: 'content',
      id: item.id,
      name: displayLibraryContentName(item),
      parentId: item.library_folder_id || null,
      sortOrder: Number(item.sort_order || 0),
      depth: 0,
      ancestorIds: [],
      unread: isUnreadContent(item),
      raw: item,
    }))
  }

  const foldersByParent = new Map()
  const itemsByParent = new Map()
  const foldersById = new Map(libraryFolders.map((folder) => [String(folder.id), folder]))
  for (const folder of libraryFolders) {
    const parentId = folder.parent_folder_id || null
    if (!foldersByParent.has(parentId)) foldersByParent.set(parentId, [])
    foldersByParent.get(parentId).push(folder)
  }
  for (const item of sidebarTreeItems) {
    const parentId = item.library_folder_id || null
    if (!itemsByParent.has(parentId)) itemsByParent.set(parentId, [])
    itemsByParent.get(parentId).push(item)
  }

  const result = []
  const unreadRoot = {
    type: 'unread-root',
    id: '__unread__',
    name: '未读',
    depth: 0,
    hasNewDescendants: true,
    unreadCount: unreadContentItems.length,
    raw: null,
  }
  if (unreadContentItems.length) {
    result.push(unreadRoot)
    if (isNodeOpen(unreadRoot)) {
      for (const item of unreadContentItems) {
        result.push({
          type: 'unread-content',
          id: item.id,
          name: displayLibraryContentName(item),
          depth: 1,
          unread: true,
          raw: item,
        })
      }
    }
  }

  const pinnedFolderIds = new Set(
    libraryFolders.filter((folder) => Boolean(folder.is_pinned)).map((folder) => String(folder.id)),
  )
  const pinnedRootFolders = libraryFolders.filter((folder) => {
    if (!folder.is_pinned) return false
    let parentId = folder.parent_folder_id ? String(folder.parent_folder_id) : ''
    const visited = new Set([String(folder.id)])
    while (parentId && !visited.has(parentId)) {
      visited.add(parentId)
      if (pinnedFolderIds.has(parentId)) return false
      parentId = foldersById.get(parentId)?.parent_folder_id
        ? String(foldersById.get(parentId).parent_folder_id)
        : ''
    }
    return true
  })
  if (pinnedRootFolders.length) {
    result.push({
      type: 'pinned-root',
      id: '__pinned__',
      name: '置顶',
      depth: 0,
      meta: pinnedRootFolders.length,
      raw: null,
    })
  }

  const appendHistory = (folderId, depth) => {
    const history = folderHistoryState(folderId)
    if (history?.loading || history?.hasMore) {
      result.push({
        type: 'folder-history-more',
        id: `${folderId}:history`,
        parentId: folderId,
        name: history.loading ? '正在加载资料…' : '加载更多资料',
        depth,
        loading: Boolean(history.loading),
      })
    }
  }
  const appendChildren = (parentId, depth, ancestorIds = [], withinPinnedTree = false) => {
    const folderNodes = sortLibraryNodes(
      (foldersByParent.get(parentId) || []).filter((folder) => withinPinnedTree || !folder.is_pinned),
    ).map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      parentId: folder.parent_folder_id || null,
      sortOrder: Number(folder.sort_order || 0),
      depth,
      ancestorIds,
      meta: folderContentCounts.get(String(folder.id)) ?? 0,
      hasNewDescendants: Boolean(folderUnreadCounts.get(String(folder.id))),
      unreadCount: folderUnreadCounts.get(String(folder.id)) || 0,
      raw: folder,
    }))
    const contentNodes = sortLibraryNodes(itemsByParent.get(parentId) || []).map((item) => ({
      type: 'content',
      id: item.id,
      name: displayLibraryContentName(item),
      parentId: item.library_folder_id || null,
      sortOrder: Number(item.sort_order || 0),
      depth,
      ancestorIds,
      unread: isUnreadContent(item),
      raw: item,
    }))
    for (const node of [...folderNodes, ...contentNodes].sort(compareLibraryTreeNodes)) {
      result.push(node)
      if (node.type === 'folder' && isFolderOpen(node.id)) {
        appendChildren(node.id, depth + 1, [...ancestorIds, node.id], withinPinnedTree || Boolean(node.raw?.is_pinned))
        appendHistory(node.id, depth + 1)
      }
    }
  }

  if (pinnedRootFolders.length && isNodeOpen({ type: 'pinned-root' })) {
    const pinnedNodes = sortLibraryNodes(pinnedRootFolders).map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      parentId: folder.parent_folder_id || null,
      sortOrder: Number(folder.sort_order || 0),
      depth: 1,
      ancestorIds: [],
      meta: folderContentCounts.get(String(folder.id)) ?? 0,
      hasNewDescendants: Boolean(folderUnreadCounts.get(String(folder.id))),
      unreadCount: folderUnreadCounts.get(String(folder.id)) || 0,
      raw: folder,
    }))
    for (const node of pinnedNodes) {
      result.push(node)
      if (isFolderOpen(node.id)) {
        appendChildren(node.id, 2, [node.id], true)
        appendHistory(node.id, 2)
      }
    }
  }
  appendChildren(null, 0)
  return result
}
