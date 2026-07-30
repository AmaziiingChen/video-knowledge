import assert from 'node:assert/strict'
import test from 'node:test'

import {
  readableCharacterCount,
  reportBodyHtmlForCharacterCount,
} from './reportReadingStats.js'

test('removes inline references and the source index from report reading stats', () => {
  const html = [
    '<h2>教学安排</h2>',
    '<p>新学期课程已经公布',
    '<sup class="markdown-footnote-ref">',
    '<a href="#fn-one">1<span class="markdown-footnote-preview">隐藏预览</span></a>',
    '<span class="markdown-footnote-separator">, </span>',
    '<a href="#fn-two">2</a>',
    '</sup>。</p>',
    '<section class="markdown-footnotes" aria-label="参考来源">',
    '<ol><li id="fn-one">来源文章一</li><li id="fn-two">来源文章二</li></ol>',
    '</section>',
  ].join('')

  assert.equal(
    reportBodyHtmlForCharacterCount(html),
    '<h2>教学安排</h2><p>新学期课程已经公布。</p>'
  )
})

test('keeps ordinary superscripts and sections in the report body', () => {
  const html = '<section class="notice"><p>面积为10m<sup>2</sup>。</p></section>'
  assert.equal(reportBodyHtmlForCharacterCount(html), html)
})

test('counts readable Unicode characters without whitespace', () => {
  assert.equal(readableCharacterCount('校园 报告\nA😀'), 6)
})
