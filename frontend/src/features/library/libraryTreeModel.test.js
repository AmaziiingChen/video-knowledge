import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildLibraryTreeNodes,
  libraryFolderPaths,
  libraryTreeNodeTitle,
  unreadFolderCounts,
} from './libraryTreeModel.js'

const item = (id, values = {}) => ({ id, title: `内容 ${id}`, content_type: 'article', created_at: '2026-01-01T00:00:00Z', ...values })
const folder = (id, values = {}) => ({ id, name: `文件夹 ${id}`, sort_order: 0, ...values })
const build = (overrides = {}) => buildLibraryTreeNodes({
  libraryFolders: [], sidebarTreeItems: [], unreadContentItems: [], isUnreadContent: () => false,
  isNodeOpen: () => false, isFolderOpen: () => false, ...overrides,
})

test('search mode stays flat while retaining unread state and raw items', () => {
  const content = item('a', { library_folder_id: 'f', title: '' , canonical_source_id: 'source-a' })
  const nodes = build({ searchActive: true, sidebarTreeItems: [content], isUnreadContent: (value) => value.id === 'a' })
  assert.deepEqual(nodes.map(({ type, id, name, depth, unread, raw }) => ({ type, id, name, depth, unread, raw })), [{ type: 'content', id: 'a', name: 'source-a', depth: 0, unread: true, raw: content }])
})

test('ordinary tree preserves unread, pinned, nested, history and source ordering', () => {
  const pinned = folder('p', { is_pinned: true, sort_order: 3 })
  const child = folder('c', { parent_folder_id: 'p', sort_order: 1 })
  const ordinary = folder('o', { sort_order: 2 })
  const older = item('old', { library_folder_id: 'o', published_at: '2026-01-01T00:00:00Z' })
  const newer = item('new', { library_folder_id: 'o', published_at: '2026-02-01T00:00:00Z' })
  const nodes = build({
    libraryFolders: [ordinary, child, pinned], sidebarTreeItems: [older, newer], unreadContentItems: [newer],
    isUnreadContent: (value) => value.id === 'new', isNodeOpen: (node) => node.type === 'unread-root' || node.type === 'pinned-root',
    isFolderOpen: (id) => id === 'p' || id === 'o', folderHistoryState: (id) => id === 'o' ? { hasMore: true } : null,
    folderContentCounts: new Map([['o', 2]]), folderUnreadCounts: new Map([['o', 1]]),
  })
  assert.deepEqual(nodes.map((node) => [node.type, node.id, node.depth]), [
    ['unread-root', '__unread__', 0], ['unread-content', 'new', 1], ['pinned-root', '__pinned__', 0], ['folder', 'p', 1], ['folder', 'c', 2], ['folder', 'o', 0], ['content', 'new', 1], ['content', 'old', 1], ['folder-history-more', 'o:history', 1],
  ])
  assert.equal(nodes.find((node) => node.id === 'o').meta, 2)
  assert.equal(nodes.find((node) => node.id === 'o').unreadCount, 1)
})

test('a pinned child is not duplicated as a pinned root', () => {
  const parent = folder('parent', { is_pinned: true })
  const child = folder('child', { parent_folder_id: 'parent', is_pinned: true })
  const nodes = build({ libraryFolders: [child, parent], isNodeOpen: (node) => node.type === 'pinned-root', isFolderOpen: () => false })
  assert.deepEqual(nodes.filter((node) => node.type === 'folder').map((node) => node.id), ['parent'])
})

test('derives unread ancestor counts and human-readable paths without looping on malformed folders', () => {
  const folders = [
    folder('root', { name: '根目录' }),
    folder('child', { name: '子目录', parent_folder_id: 'root' }),
    folder('cycle-a', { name: '循环 A', parent_folder_id: 'cycle-b' }),
    folder('cycle-b', { name: '循环 B', parent_folder_id: 'cycle-a' }),
  ]
  const counts = unreadFolderCounts({
    libraryFolders: folders,
    libraryContentItems: [item('read', { library_folder_id: 'child' }), item('new', { library_folder_id: 'child' })],
    isUnreadContent: (value) => value.id === 'new',
  })
  assert.equal(counts.get('child'), 1)
  assert.equal(counts.get('root'), 1)
  assert.equal(counts.get('cycle-a'), 0)

  const paths = libraryFolderPaths(folders)
  assert.equal(paths.get('child'), '根目录 / 子目录')
  assert.equal(paths.get('cycle-a'), '循环 B / 循环 A')
  assert.equal(libraryTreeNodeTitle({ type: 'unread-content', name: '新资料', raw: { library_folder_id: 'child' } }, paths), '新资料\n根目录 / 子目录')
  assert.equal(libraryTreeNodeTitle({ type: 'content', name: '普通资料', raw: { source_name: '来源', source_section: '栏目' } }), '普通资料\n来源 · 栏目')
})
