import assert from 'node:assert/strict'
import test from 'node:test'

import { matchQaShortcut } from './qaShortcutMatcher.js'

const shortcuts = [
  { name: '总结', template: '总结模板' },
  { name: '质疑', template: '质疑模板' },
  { name: '术语', template: '术语模板' }
]

test('matches a local shortcut intent without calling a model', () => {
  assert.equal(matchQaShortcut('这段内容到底靠谱吗？', shortcuts)?.name, '质疑')
  assert.equal(matchQaShortcut('帮我总结一下这篇文章', shortcuts)?.name, '总结')
  assert.equal(matchQaShortcut('这个术语是什么意思？', shortcuts)?.name, '术语')
})

test('does not replace explicit commands or unavailable shortcuts', () => {
  assert.equal(matchQaShortcut('@总结 帮我看看', shortcuts), null)
  assert.equal(matchQaShortcut('给我几个反例', shortcuts), null)
})
