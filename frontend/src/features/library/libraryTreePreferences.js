export const FOLDER_TREE_STATE_KEY = 'knowledgehub:file-tree-open-folders:v2'
export const USER_GROUP_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-separators:v2'
export const LEGACY_USER_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-user-separators:v1'
export const LEGACY_USER_GROUP_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-user-groups:v1'

export function loadLibraryTreePreferences(storage = window.localStorage) {
  try {
    const saved = storage.getItem(USER_GROUP_SEPARATOR_STATE_KEY)
    const legacy = storage.getItem(LEGACY_USER_SEPARATOR_STATE_KEY) || storage.getItem(LEGACY_USER_GROUP_SEPARATOR_STATE_KEY)
    const stored = JSON.parse(saved || legacy || '[]')
    const groups = Array.isArray(stored) ? stored : stored?.separators
    return { initialized: Array.isArray(groups) ? (saved ? Boolean(stored?.initialized) : true) : Boolean(stored?.initialized), separators: Array.isArray(groups) ? groups.filter((group) => group && typeof group === 'object' && String(group.id || '').trim()).map((group) => ({ id: String(group.id), sortOrder: Number.isFinite(Number(group.sortOrder)) ? Number(group.sortOrder) : null, beforeFolderId: group.beforeFolderId ? String(group.beforeFolderId) : null })) : [] }
  } catch { return { initialized: false, separators: [] } }
}
export function saveLibraryTreePreferences(groups, storage = window.localStorage) { try { storage.setItem(USER_GROUP_SEPARATOR_STATE_KEY, JSON.stringify({ version: 2, initialized: true, separators: groups })) } catch {} }
export function loadOpenFolderIds(storage = window.localStorage) { try { const stored = JSON.parse(storage.getItem(FOLDER_TREE_STATE_KEY) || '[]'); return new Set(Array.isArray(stored) ? stored.map(String) : []) } catch { return new Set() } }
export function saveOpenFolderIds(folderIds, storage = window.localStorage) { try { storage.setItem(FOLDER_TREE_STATE_KEY, JSON.stringify([...folderIds])) } catch {} }
