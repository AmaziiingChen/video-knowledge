import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./PreviewFindBar.vue', import.meta.url), 'utf8')

test('uses its supplied search context for accessible labels and placeholder text', () => {
  assert.match(source, /searchLabel: \{ type: String, default: '在预览中查找' \}/)
  assert.match(source, /:placeholder="searchLabel"/)
  assert.match(source, /:aria-label="searchLabel"/)
  assert.match(source, /:title="searchLabel"/)
})
