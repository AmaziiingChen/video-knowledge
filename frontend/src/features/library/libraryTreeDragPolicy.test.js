import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canDropOnUserSeparator,
  externalImportTargetFolderId,
  hasExternalFiles,
  libraryTreeDropPosition,
  separatorDropPosition,
} from './libraryTreeDragPolicy.js'

test('accepts only file drags and resolves the nearest external-import folder without looping', () => {
  assert.equal(hasExternalFiles({ types: ['text/plain', 'Files'] }), true)
  assert.equal(hasExternalFiles({ types: ['text/plain'] }), false)
  const folders = [
    { id: 'imports', name: '外部导入' },
    { id: 'child', name: '子目录', parent_folder_id: 'imports' },
    { id: 'cycle-a', name: '循环 A', parent_folder_id: 'cycle-b' },
    { id: 'cycle-b', name: '循环 B', parent_folder_id: 'cycle-a' },
  ]
  assert.equal(externalImportTargetFolderId({ type: 'folder', id: 'child' }, folders), 'child')
  assert.equal(externalImportTargetFolderId({ type: 'content', parentId: 'cycle-a' }, folders), null)
})

test('limits separator drops to root folders and separators', () => {
  assert.equal(canDropOnUserSeparator({ type: 'user-group-separator' }), true)
  assert.equal(canDropOnUserSeparator({ type: 'folder', parentId: null }), true)
  assert.equal(canDropOnUserSeparator({ type: 'folder', parentId: 'parent' }), false)
  assert.equal(canDropOnUserSeparator({ type: 'folder' }, [{ type: 'folder' }, { type: 'content' }]), false)
})

test('maps tree and separator pointer positions to the stable drop regions', () => {
  const rect = { top: 100, height: 100 }
  assert.equal(separatorDropPosition({ clientY: 149, rect }), 'before')
  assert.equal(separatorDropPosition({ clientY: 150, rect }), 'after')
  assert.equal(libraryTreeDropPosition({ clientY: 120, rect, node: { type: 'folder' }, dragNode: { type: 'folder' } }), 'before')
  assert.equal(libraryTreeDropPosition({ clientY: 150, rect, node: { type: 'folder' }, dragNode: { type: 'folder' } }), 'inside')
  assert.equal(libraryTreeDropPosition({ clientY: 150, rect, node: { type: 'content' }, dragNode: { type: 'folder' } }), 'after')
  assert.equal(libraryTreeDropPosition({ clientY: 150, rect, node: { type: 'folder' }, dragNode: { type: 'user-group-separator' } }), 'after')
  assert.equal(libraryTreeDropPosition({ clientY: 190, rect, node: { type: 'folder' }, dragNode: { type: 'folder' } }), 'after')
})
