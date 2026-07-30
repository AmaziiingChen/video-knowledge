import assert from 'node:assert/strict'
import test from 'node:test'

import { sourceProviderFromUrl } from './taskSource.js'

test('identifies a queued task source without relying on a previous task', () => {
  assert.equal(sourceProviderFromUrl('https://v.douyin.com/example/'), 'douyin')
  assert.equal(sourceProviderFromUrl('https://www.bilibili.com/video/BV1example'), 'bilibili')
  assert.equal(sourceProviderFromUrl('https://mp.weixin.qq.com/s/example'), 'wechat')
  assert.equal(sourceProviderFromUrl('https://example.test/article'), '')
})
