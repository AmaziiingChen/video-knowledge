import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./useAppController.js', import.meta.url), 'utf8')

test('hydrates global search matches instead of filtering the loaded sidebar window', () => {
  assert.match(source, /searchResultContentItems/)
  assert.match(source, /\/content\/items\/resolve/)
  assert.match(source, /return searchQuery\.value\.trim\(\) \? searchResultContentItems\.value : sidebarContentItems\.value/)
  assert.match(source, /scope: librarySearchScope\.value, limit: 200/)
})
