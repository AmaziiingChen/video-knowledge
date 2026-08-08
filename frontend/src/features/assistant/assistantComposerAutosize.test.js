import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./SecondarySidebar.vue', import.meta.url), 'utf8')

test('keeps the assistant composer to one line before its content expands', () => {
  assert.match(source, /class="assistant-question-textarea"[\s\S]*?rows="1"[\s\S]*?@input="handleQuestionInput"/)
  assert.match(source, /function resizeQuestionInput[\s\S]*?Math\.min\(input\.scrollHeight, maxHeight\)/)
  assert.match(source, /min-height:\s*21px;[\s\S]*?max-height:\s*121px;/)
  assert.match(source, /\.assistant-side-actions\s*\{\s*min-height:\s*30px;\s*display:\s*flex;/)
})
