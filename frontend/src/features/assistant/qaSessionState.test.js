import test from 'node:test'
import assert from 'node:assert/strict'
import {
  TRANSIENT_QA_SESSION_ID,
  clearQaSessionState,
  createQaSession,
  qaSessionKey
} from './qaSessionState.js'

test('sessions use stable independent keys for each content item', () => {
  assert.equal(qaSessionKey(42), '42')
  assert.equal(qaSessionKey('article-a'), 'article-a')
  assert.equal(qaSessionKey(null), TRANSIENT_QA_SESSION_ID)
})

test('clearing one session does not alter another article session', () => {
  const articleA = createQaSession()
  const articleB = createQaSession()
  articleA.draft = 'A 的草稿'
  articleA.history = [{ question: 'A 的问题' }]
  articleA.asking = true
  articleA.historyRequestId = 3
  articleB.history = [{ question: 'B 的问题', answer: 'B 的回答' }]
  articleB.generatingSummary = true

  clearQaSessionState(articleA)

  assert.deepEqual(articleA.history, [])
  assert.equal(articleA.draft, '')
  assert.equal(articleA.asking, false)
  assert.equal(articleA.historyRequestId, 4)
  assert.equal(articleA.historyLoaded, true)
  assert.deepEqual(articleB.history, [{ question: 'B 的问题', answer: 'B 的回答' }])
  assert.equal(articleB.generatingSummary, true)
})
