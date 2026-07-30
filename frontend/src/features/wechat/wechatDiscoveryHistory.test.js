import assert from 'node:assert/strict'
import test from 'node:test'

import {
  discoveryRecommendations,
  normalizeDiscoveryHistory,
  recordDiscovery
} from './wechatDiscoveryHistory.js'

test('records recent searches once and keeps compact valid results', () => {
  const original = [{ query: '电力', searched_at: 'old', results: [{ fakeid: 'old', name: '旧结果' }] }]
  const updated = recordDiscovery(original, ' 电力 ', [
    { fakeid: 'new', name: '新结果', description: '简介' },
    { fakeid: '', name: '无效结果' }
  ], 'new')

  assert.equal(updated.length, 1)
  assert.equal(updated[0].searched_at, 'new')
  assert.deepEqual(updated[0].results.map((item) => item.fakeid), ['new'])
})

test('recommendations exclude subscribed and duplicate public accounts', () => {
  const history = normalizeDiscoveryHistory([
    { query: '高校', results: [{ fakeid: 'a', name: 'A' }, { fakeid: 'b', name: 'B' }] },
    { query: '教育', results: [{ fakeid: 'b', name: 'B' }, { fakeid: 'c', name: 'C' }] }
  ])
  const recommendations = discoveryRecommendations(history, [{ fakeid: 'a' }])

  assert.deepEqual(recommendations.map((item) => item.fakeid), ['b', 'c'])
})
