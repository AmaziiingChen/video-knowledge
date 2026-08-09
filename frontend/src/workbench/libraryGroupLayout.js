import { compareLibraryTreeNodes } from '../features/library/libraryTreeModel.js'

const ROOT_LIBRARY_GROUPS = {
  inbox: new Set(['待整理收藏']),
  video: new Set(['抖音', 'B站']),
  sources: new Set(['微信公众号', '微信小程序', '校园官网', 'RSS订阅', '外部导入']),
  reports: new Set(['日报', '周报', '月报', '区间汇总', '报告']),
}
const ROOT_LIBRARY_GROUP_ORDER = ['inbox', 'video', 'sources', 'reports', 'other']

export function isRootLayoutNode(node) {
  return node?.type === 'user-group-separator' || (node?.type === 'folder' && node.depth === 0)
}

export function layoutSortOrder(node) {
  return Number(node?.sortOrder ?? node?.raw?.sortOrder ?? 0)
}

export function sortOrderBetween(previous, next) {
  const before = previous ? layoutSortOrder(previous) : null
  const after = next ? layoutSortOrder(next) : null
  if (before !== null && after !== null && after > before) return (before + after) / 2
  if (before !== null) return before + 1
  if (after !== null) return after - 1
  return 0
}

export function rootLibraryGroup(node) {
  if (node?.type !== 'folder') return 'other'
  const presentationGroup = String(node.raw?.presentation_group || '')
  if (presentationGroup === 'manual:default') return 'inbox'
  if (presentationGroup.startsWith('provider:')) {
    const provider = presentationGroup.slice('provider:'.length)
    if (provider === 'douyin' || provider === 'bilibili') return 'video'
    if (['wechat', 'campus', 'wechat_miniprogram', 'rss', 'xiaohongshu'].includes(provider)) return 'sources'
  }
  if (presentationGroup === 'external') return 'sources'
  const name = String(node.name || '').trim()
  if (ROOT_LIBRARY_GROUPS.inbox.has(name)) return 'inbox'
  if (ROOT_LIBRARY_GROUPS.video.has(name)) return 'video'
  if (ROOT_LIBRARY_GROUPS.sources.has(name)) return 'sources'
  if (ROOT_LIBRARY_GROUPS.reports.has(name)) return 'reports'
  return 'other'
}

export function compareRootTreeNodes(left, right) {
  const groupOrder = ROOT_LIBRARY_GROUP_ORDER.indexOf(rootLibraryGroup(left))
  const otherGroupOrder = ROOT_LIBRARY_GROUP_ORDER.indexOf(rootLibraryGroup(right))
  if (groupOrder !== otherGroupOrder) return groupOrder - otherGroupOrder
  return compareLibraryTreeNodes(left, right)
}

export function rootFolderNodes(libraryFolders) {
  return libraryFolders
    .filter((folder) => !folder.parent_folder_id && !folder.is_pinned)
    .map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      sortOrder: Number(folder.sort_order || 0),
      raw: folder,
    }))
}

export function separatorSortOrder(separator, roots) {
  const saved = Number(separator?.sortOrder)
  if (Number.isFinite(saved)) return saved
  const rootsById = new Map(roots.map((node) => [String(node.id), node]))
  const anchor = rootsById.get(String(separator?.beforeFolderId || ''))
  if (anchor) return Number(anchor.sortOrder || 0) - 0.5
  const last = [...roots].sort(compareLibraryTreeNodes).at(-1)
  return last ? Number(last.sortOrder || 0) + 1 : 0
}

export function createDefaultSeparators(libraryFolders, createId = defaultSeparatorId) {
  const roots = rootFolderNodes(libraryFolders).sort(compareRootTreeNodes)
  const separators = []
  let previous = null
  for (const node of roots) {
    if (previous && rootLibraryGroup(node) !== rootLibraryGroup(previous)) {
      const before = Number(previous.sortOrder || 0)
      const after = Number(node.sortOrder || 0)
      separators.push({
        id: createId(separators.length),
        sortOrder: after > before ? (before + after) / 2 : after - 0.5,
      })
    }
    previous = node
  }
  return separators
}

export function presentLibraryNodesWithSeparators(nodes, separators) {
  if (!separators.length) return nodes
  const rootsById = new Map(
    nodes
      .filter((node) => node.type === 'folder' && node.depth === 0)
      .map((node) => [String(node.id), node]),
  )
  const orderedSeparators = separators
    .map((separator) => ({ ...separator, sortOrder: separatorSortOrder(separator, [...rootsById.values()]) }))
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id))
  const result = []
  let separatorIndex = 0
  const appendBefore = (sortOrder) => {
    while (separatorIndex < orderedSeparators.length && orderedSeparators[separatorIndex].sortOrder <= sortOrder) {
      const separator = orderedSeparators[separatorIndex]
      result.push({ type: 'user-group-separator', id: separator.id, name: '', depth: 0, sortOrder: separator.sortOrder, raw: separator })
      separatorIndex += 1
    }
  }
  for (const node of nodes) {
    if (node.type === 'folder' && node.depth === 0) appendBefore(Number(node.sortOrder || 0))
    result.push(node)
  }
  appendBefore(Number.POSITIVE_INFINITY)
  return result
}

export function migrateUserGroupSeparators(separators, libraryFolders) {
  const roots = rootFolderNodes(libraryFolders)
  return separators.map((separator) => ({
    ...separator,
    sortOrder: separatorSortOrder(separator, roots),
    beforeFolderId: undefined,
  }))
}

function defaultSeparatorId(index) {
  return globalThis.crypto?.randomUUID?.() || `separator-${Date.now()}-${index}`
}
