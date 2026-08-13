import assert from 'node:assert/strict'
import test from 'node:test'
import { useWechatFeedExportController } from './useWechatFeedExportController.js'

test('copies aggregate and single-subscription RSS URLs without sharing credentials', async () => {
  const copied = []; const messages = []
  const { copyWeChatRss } = useWechatFeedExportController({
    feedApi: '/api/wechat-feed', clipboard: { writeText: async (value) => copied.push(value) },
    notify: { success: (value) => messages.push(['success', value]), error: (value) => messages.push(['error', value]) },
  })
  await copyWeChatRss(); await copyWeChatRss('sub-1')
  assert.deepEqual(copied, ['/api/wechat-feed/rss.xml', '/api/wechat-feed/rss/sub-1.xml'])
  assert.deepEqual(messages, [['success', '聚合 RSS 地址已复制'], ['success', '单公众号 RSS 地址已复制']])
})

test('exports the subscription document with a stable name and no credential-specific path', async () => {
  const events = []; const messages = []
  const { exportWeChatSubscriptions } = useWechatFeedExportController({
    feedApi: '/api/wechat-feed', request: { get: async (...args) => { events.push(['get', ...args]); return { data: { subscriptions: [] } } } },
    BlobClass: class { constructor(parts, options) { events.push(['blob', parts, options]) } },
    urlObject: { createObjectURL: () => 'blob:subscriptions', revokeObjectURL: (value) => events.push(['revoke', value]) },
    documentObject: { createElement: () => ({ click: () => events.push(['click']), set href(value) { events.push(['href', value]) }, set download(value) { events.push(['download', value]) } }) },
    notify: { success: (value) => messages.push(['success', value]), error: (value) => messages.push(['error', value]) },
  })
  await exportWeChatSubscriptions()
  assert.deepEqual(events, [
    ['get', '/api/wechat-feed/subscriptions.json', { timeout: 10000 }], ['blob', ['{\n  "subscriptions": []\n}'], { type: 'application/json;charset=utf-8' }],
    ['href', 'blob:subscriptions'], ['download', 'knowledgehub-wechat-subscriptions.json'], ['click'], ['revoke', 'blob:subscriptions'],
  ])
  assert.deepEqual(messages, [['success', '订阅配置已导出，不包含登录凭据']])
})
