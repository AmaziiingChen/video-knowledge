import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('./App.vue', import.meta.url), 'utf8')

test('keeps the default editor host behind an asynchronous workspace boundary', () => {
  assert.match(source, /const EditorHost = defineAsyncComponent\(\(\) => import\('\.\/workbench\/EditorHost\.vue'\)\)/)
  assert.doesNotMatch(source, /import EditorHost from '\.\/workbench\/EditorHost\.vue'/)
})
