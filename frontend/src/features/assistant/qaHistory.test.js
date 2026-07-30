import assert from 'node:assert/strict'
import test from 'node:test'

import { qaHistoryForPrompt, savedQaHistoryItems } from './qaHistory.js'

test('uses the exact model-facing question while keeping the display wording separate', () => {
  const history = qaHistoryForPrompt([{
    question: '帮我总结一下',
    modelQuestion: '已选择的追问方式：\n@总结\n总结模板\n\n用户补充：\n帮我总结一下',
    answer: '这是总结',
    pending: false,
    error: false
  }])

  assert.equal(history[0].question.includes('@总结'), true)
  assert.equal(history[0].answer, '这是总结')
})

test('preserves the persisted answer id required for regeneration', () => {
  const [item] = savedQaHistoryItems([{
    id: 'answer-1',
    question: '问题',
    answer: '回答',
    created_at: '2026-07-25T10:00:00'
  }])

  assert.equal(item.id, 'answer-1')
})
