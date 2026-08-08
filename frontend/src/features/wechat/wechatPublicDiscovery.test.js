import assert from 'node:assert/strict'
import test from 'node:test'

import {
  albumSourceScheduleText,
  discoveryInputHint,
  discoveryRunDisplayStatus,
  discoveryRunStatusLabel,
  discoveryRunSummary,
  isWechatAlbumInput
} from './wechatPublicDiscovery.js'


test('discoveryInputHint distinguishes albums from article batches', () => {
  assert.equal(
    isWechatAlbumInput('https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzA&album_id=1'),
    true
  )
  assert.match(
    discoveryInputHint('https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzA&album_id=1'),
    /公众号合集/
  )
  assert.match(
    discoveryInputHint(
      'https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1\n'
      + 'https://mp.weixin.qq.com/s?__biz=MzA&mid=2&idx=1'
    ),
    /2 个微信链接/
  )
  assert.match(
    discoveryInputHint('https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1', 'seed'),
    /严格校验/
  )
  assert.match(discoveryInputHint('', 'seed'), /种子文章/)
})


test('albumSourceScheduleText explains paused and scheduled sources', () => {
  assert.equal(albumSourceScheduleText({ enabled: false }), '自动检测已暂停')
  assert.match(
    albumSourceScheduleText({ enabled: true, next_sync_at: '2026-08-02T00:00:00+08:00' }),
    /下次检查/
  )
})


test('discovery run helpers expose durable counts', () => {
  assert.equal(discoveryRunStatusLabel('running'), '正在处理')
  assert.equal(discoveryRunDisplayStatus({ status: 'succeeded', review_required: 1 }), '等待确认')
  assert.equal(
    discoveryRunDisplayStatus({ status: 'succeeded', review_import_status: 'running' }),
    '正在导入选中项'
  )
  assert.equal(
    discoveryRunSummary({
      candidate_count: 8,
      verified_count: 7,
      imported_count: 5,
      duplicate_count: 2,
      failed_count: 1
    }),
    '发现 8 · 校验 7 · 新增 5 · 重复 2 · 失败 1'
  )
})
