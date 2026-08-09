import assert from 'node:assert/strict'
import test from 'node:test'
import { loadLibraryTreePreferences, loadOpenFolderIds, saveLibraryTreePreferences } from './libraryTreePreferences.js'

function storage(values = {}) { return { getItem: (key) => values[key] ?? null, setItem: (key, value) => { values[key] = value } } }
test('preferences tolerate malformed state and migrate legacy separators', () => {
  assert.deepEqual(loadLibraryTreePreferences(storage()), { initialized: true, separators: [] })
  assert.deepEqual(loadLibraryTreePreferences(storage({ 'knowledgehub:file-tree-separators:v2': '{' })), { initialized: false, separators: [] })
  assert.deepEqual(loadLibraryTreePreferences(storage({ 'knowledgehub:file-tree-user-separators:v1': '[{"id":1}]' })), { initialized: true, separators: [{ id: '1', sortOrder: null, beforeFolderId: null }] })
})
test('open folders stringify ids and preferences persist v2 state', () => {
  const value = {}; const store = storage(value)
  assert.deepEqual([...loadOpenFolderIds(storage({ 'knowledgehub:file-tree-open-folders:v2': '[1,"2"]' }))], ['1', '2'])
  saveLibraryTreePreferences([{ id: 'group' }], store)
  assert.equal(JSON.parse(value['knowledgehub:file-tree-separators:v2']).initialized, true)
})
