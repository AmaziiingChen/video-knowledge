import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createDefaultSeparators,
  migrateUserGroupSeparators,
  presentLibraryNodesWithSeparators,
  sortOrderBetween,
} from './libraryGroupLayout.js'

const folder = (id, name, sortOrder, presentationGroup = '') => ({
  id,
  name,
  sort_order: sortOrder,
  presentation_group: presentationGroup,
})

test('creates stable default separators between root presentation groups', () => {
  const folders = [
    folder('wechat', '微信公众号', 30, 'provider:wechat'),
    folder('video', '抖音', 20, 'provider:douyin'),
    folder('inbox', '待整理收藏', 10, 'manual:default'),
  ]

  const separators = createDefaultSeparators(folders, (index) => `separator-${index}`)

  assert.deepEqual(separators, [
    { id: 'separator-0', sortOrder: 15 },
    { id: 'separator-1', sortOrder: 25 },
  ])
})

test('migrates legacy separators with the current numeric fallback', () => {
  const folders = [folder('one', '资料一', 10), folder('two', '资料二', 20)]

  assert.deepEqual(
    migrateUserGroupSeparators([{ id: 'legacy', sortOrder: null, beforeFolderId: 'two' }], folders),
    [{ id: 'legacy', sortOrder: 0, beforeFolderId: undefined }],
  )
})

test('inserts separators without disturbing visible tree-node order', () => {
  const nodes = [
    { type: 'folder', id: 'one', name: '资料一', depth: 0, sortOrder: 10 },
    { type: 'content', id: 'content', name: '内容', depth: 1 },
    { type: 'folder', id: 'two', name: '资料二', depth: 0, sortOrder: 20 },
  ]

  const presented = presentLibraryNodesWithSeparators(nodes, [
    { id: 'middle', sortOrder: 15 },
    { id: 'end', sortOrder: 30 },
  ])

  assert.deepEqual(presented.map((node) => [node.type, node.id]), [
    ['folder', 'one'],
    ['content', 'content'],
    ['user-group-separator', 'middle'],
    ['folder', 'two'],
    ['user-group-separator', 'end'],
  ])
  assert.equal(sortOrderBetween({ sortOrder: 10 }, { sortOrder: 20 }), 15)
})
