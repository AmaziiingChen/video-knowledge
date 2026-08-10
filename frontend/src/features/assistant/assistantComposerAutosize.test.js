import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./AssistantComposer.vue', import.meta.url), 'utf8')
const styles = await readFile(new URL('./assistantComposer.css', import.meta.url), 'utf8')

test('keeps the assistant composer to one line before its content expands', () => {
  assert.match(source, /class="assistant-question-textarea"[\s\S]*?rows="1"[\s\S]*?@input="handleQuestionInput"/)
  assert.match(styles, /min-height:\s*21px;[\s\S]*?max-height:\s*121px;/)
  assert.match(styles, /\.assistant-side-actions\s*\{\s*min-height:\s*30px;\s*display:\s*flex;/)
})
