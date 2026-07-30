import assert from 'node:assert/strict'
import test from 'node:test'

import {
  compactFootnoteDefinition,
  footnotePreviewMetadata,
  moveMarkdownCitationsBeforePunctuation,
} from './markdownFootnotes.js'
import { extractReportSourceStats } from './reportSourceStats.js'
import { sourceProviderFromUrl } from './taskSource.js'

test('makes the complete source description one link', () => {
  assert.equal(
    compactFootnoteDefinition(
      '[测试文章](<https://mp.weixin.qq.com/s/example>) · 测试公众号 · 2026-07-15'
    ),
    '[测试文章 · 微信公众号 · 测试公众号 · 2026-07-15](<https://mp.weixin.qq.com/s/example>)'
  )
})

test('keeps only the first line of a malformed source title', () => {
  assert.equal(
    compactFootnoteDefinition(
      '[正常标题\n正文不应进入脚注](<https://mp.weixin.qq.com/s/example>) — 测试公众号，2026-07-15'
    ),
    '[正常标题 · 微信公众号 · 测试公众号 · 2026-07-15](<https://mp.weixin.qq.com/s/example>)'
  )
})

test('moves citations before their punctuation without merging clause-level sources', () => {
  assert.equal(
    moveMarkdownCitationsBeforePunctuation('第一批已开放。 [^S01] 第二批8月公布，[^S02][^S03]'),
    '第一批已开放[^S01]。 第二批8月公布[^S02][^S03]，'
  )
  assert.equal(
    moveMarkdownCitationsBeforePunctuation('第一批已开放[^S01]，第二批8月公布[^S02][^S03]。'),
    '第一批已开放[^S01]，第二批8月公布[^S02][^S03]。'
  )
})

test('extracts title and source hierarchy for an inline citation preview', () => {
  assert.deepEqual(
    footnotePreviewMetadata(
      '[2026年深技大暑假安排](<https://mp.weixin.qq.com/s/example>) · 技大校园e栈 · 2026-07-14'
    ),
    { title: '2026年深技大暑假安排', metadata: '微信公众号 · 技大校园e栈 · 2026-07-14' }
  )
})

test('keeps a pipe inside an article title out of citation provenance', () => {
  assert.deepEqual(
    footnotePreviewMetadata(
      '[药香润廉 顺时养生| 廉洁、节气主题展亮相图书馆！](<https://mp.weixin.qq.com/s/example>) · 微信公众号 · 深圳技术大学图书馆 · 2026-07-17'
    ),
    {
      title: '药香润廉 顺时养生| 廉洁、节气主题展亮相图书馆！',
      metadata: '微信公众号 · 深圳技术大学图书馆 · 2026-07-17',
    }
  )
})

test('keeps a pipe inside a compact footnote title out of citation provenance', () => {
  assert.deepEqual(
    footnotePreviewMetadata(
      '[药香润廉 顺时养生| 廉洁、节气主题展亮相图书馆！ · 微信公众号 · 深圳技术大学图书馆 · 2026-07-17](<https://mp.weixin.qq.com/s/example>)'
    ),
    {
      title: '药香润廉 顺时养生| 廉洁、节气主题展亮相图书馆！',
      metadata: '微信公众号 · 深圳技术大学图书馆 · 2026-07-17',
    }
  )
})

test('puts a GWT publisher after its source type in an inline citation preview', () => {
  assert.deepEqual(
    footnotePreviewMetadata(
      '[暑假开馆安排](<https://nbw.sztu.edu.cn/info/1029/1001.htm>) · 深圳技术大学图书馆 · 公文通 · 2026-07-14'
    ),
    { title: '暑假开馆安排', metadata: '公文通 · 深圳技术大学图书馆 · 2026-07-14' }
  )
})

test('reads the title from legacy publisher-first report footnotes', () => {
  assert.deepEqual(
    footnotePreviewMetadata(
      '深圳技术大学图书馆｜[2026 暑假开馆安排](<https://nbw.sztu.edu.cn/info/1029/1001.htm>)'
    ),
    { title: '2026 暑假开馆安排', metadata: '深圳技术大学图书馆' }
  )
})

test('reads explicit analyzed and inline-cited article counts from a new report', () => {
  assert.deepEqual(
    extractReportSourceStats(
      '# 校园生活周报\n\n> 分组：校园生活 · 分析文章：38 篇 · 正文引用：17 篇'
    ),
    { analyzed: 38, referenced: 17 }
  )
})

test('derives referenced article count from legacy report footnotes', () => {
  assert.deepEqual(
    extractReportSourceStats(
      '> 分组：校园生活 · 来源文章：38 篇\n\n正文[^S01][^S03]\n\n[^S01]: 来源一\n[^S03]: 来源三'
    ),
    { analyzed: 38, referenced: 2 }
  )
})
