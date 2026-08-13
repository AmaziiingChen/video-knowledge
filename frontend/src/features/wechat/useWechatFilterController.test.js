import assert from 'node:assert/strict'
import test from 'node:test'

import { useWechatFilterController } from './useWechatFilterController.js'

function createController({ request = {} } = {}) {
  const messages = []
  let refreshed = 0
  const controller = useWechatFilterController({
    filterApi: 'http://api.test/wechat-content-filters',
    loadSubscriptions: async () => { refreshed += 1 },
    request: {
      post: async () => {},
      delete: async () => {},
      ...request,
    },
    notify: {
      success: (message) => messages.push(['success', message]),
      error: (message) => messages.push(['error', message]),
    },
    errorMessage: (_error, fallback) => fallback,
  })
  return { controller, messages, refreshed: () => refreshed }
}

test('creating a filter retains the request, completion callback and subscription refresh contract', async () => {
  const calls = []
  let completed = 0
  const { controller, messages, refreshed } = createController({
    request: { post: async (...args) => { calls.push(args) } },
  })
  await controller.createWeChatFilter({ pattern: '推广', action: 'remove' }, () => { completed += 1 })
  assert.deepEqual(calls, [[
    'http://api.test/wechat-content-filters',
    { pattern: '推广', action: 'remove' },
    { timeout: 10000 },
  ]])
  assert.equal(completed, 1)
  assert.equal(refreshed(), 1)
  assert.deepEqual(messages, [['success', '正文清洗规则已添加']])
  assert.equal(controller.savingWeChatFilter.value, false)
})

test('failed filter creation clears its busy state and reports the existing fallback', async () => {
  const { controller, messages, refreshed } = createController({
    request: { post: async () => { throw new Error('offline') } },
  })
  await controller.createWeChatFilter({ pattern: '推广' })
  assert.equal(controller.savingWeChatFilter.value, false)
  assert.equal(refreshed(), 0)
  assert.deepEqual(messages, [['error', '添加正文清洗规则失败']])
})

test('deleting a filter uses its stable item endpoint and reloads the manager data', async () => {
  const calls = []
  const { controller, messages, refreshed } = createController({
    request: { delete: async (...args) => { calls.push(args) } },
  })
  await controller.deleteWeChatFilter('rule-1')
  assert.deepEqual(calls, [['http://api.test/wechat-content-filters/rule-1', { timeout: 10000 }]])
  assert.equal(refreshed(), 1)
  assert.deepEqual(messages, [['success', '正文清洗规则已删除']])
})
