import assert from 'node:assert/strict'
import test from 'node:test'

import { makeContentTab } from './workspaceModel.js'

test('content tabs retain one stable content identity for every source', () => {
  for (const item of [
    { id: 'video', title: '视频', source_provider: 'bilibili', content_type: 'video' },
    { id: 'article', title: '文章', source_provider: 'wechat', content_type: 'article' },
    { id: 'web', title: '网页', source_provider: 'rss', content_type: 'article' },
    { id: 'report', title: '周报', source_provider: 'wechat_report', content_type: 'report' },
  ]) {
    assert.equal(makeContentTab(item).content_item_id, item.id)
  }
})
