export function hasExternalFiles(dataTransfer) {
  return Array.from(dataTransfer?.types || []).includes('Files')
}

export function externalImportTargetFolderId(node, libraryFolders = []) {
  let folderId = node?.type === 'folder' ? node.id : node?.parentId
  const folders = new Map(libraryFolders.map((folder) => [String(folder.id), folder]))
  const visited = new Set()
  while (folderId && !visited.has(String(folderId))) {
    const folder = folders.get(String(folderId))
    if (!folder) return null
    if (folder.name === '外部导入') return String(node.type === 'folder' ? node.id : node.parentId)
    visited.add(String(folderId))
    folderId = folder.parent_folder_id ? String(folder.parent_folder_id) : null
  }
  return null
}

export function canDropOnUserSeparator(dragNode, dragNodes = []) {
  if (dragNode?.type === 'user-group-separator') return true
  const candidates = dragNodes.length ? dragNodes : [dragNode]
  return candidates.length > 0 && candidates.every((node) => (
    node?.type === 'folder' && !node.parentId
  ))
}

export function separatorDropPosition({ clientY, rect }) {
  return clientY - rect.top < rect.height / 2 ? 'before' : 'after'
}

export function libraryTreeDropPosition({ clientY, rect, node, dragNode }) {
  const y = clientY - rect.top
  const ratio = rect.height ? y / rect.height : 0.5
  if (ratio < 0.28) return 'before'
  if (ratio > 0.72) return 'after'
  return node?.type === 'folder' && dragNode?.type !== 'user-group-separator'
    ? 'inside'
    : 'after'
}
