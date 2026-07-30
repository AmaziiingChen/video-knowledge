import test from 'node:test'
import assert from 'node:assert/strict'
import { commandItemSearchText, filterCommandItems } from './commandPaletteState.js'

const items = [
  { id: 'view:rss', group: '工作区', title: 'RSS 订阅', subtitle: '切换到 RSS 管理', keywords: ['订阅源'] },
  { id: 'content:1', group: '资料', title: 'AI 论文简报', subtitle: 'RSS · 每日新闻' },
  { id: 'settings', group: '操作', title: '打开设置', keywords: ['preferences'] },
]

test('command palette searches title, subtitle, group and aliases', () => {
  assert.equal(commandItemSearchText(items[0]).includes('订阅源'), true)
  assert.deepEqual(filterCommandItems(items, 'rss').map((item) => item.id), ['view:rss', 'content:1'])
  assert.deepEqual(filterCommandItems(items, 'preferences').map((item) => item.id), ['settings'])
})

test('command palette requires every query term', () => {
  assert.deepEqual(filterCommandItems(items, 'ai 新闻').map((item) => item.id), ['content:1'])
  assert.deepEqual(filterCommandItems(items, '不存在').map((item) => item.id), [])
})
