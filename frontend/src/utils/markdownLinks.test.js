import assert from 'node:assert/strict'
import test from 'node:test'

import { isExternalLinkHref, normalizeBareExternalLinks } from './markdownLinks.js'

test('separates Chinese prose appended directly after a bare URL', () => {
  assert.equal(
    normalizeBareExternalLinks('查询 https://example.com/results查看录取结果'),
    '查询 <https://example.com/results>查看录取结果'
  )
})

test('separates Chinese punctuation from a bare URL', () => {
  assert.equal(
    normalizeBareExternalLinks('官网：https://example.com/path。请及时查看'),
    '官网：<https://example.com/path>。请及时查看'
  )
})

test('keeps explicit Markdown links and autolinks unchanged', () => {
  assert.equal(
    normalizeBareExternalLinks('[查询结果](https://example.com/中文路径) <https://example.com/中文路径>'),
    '[查询结果](https://example.com/中文路径) <https://example.com/中文路径>'
  )
})

test('accepts only external protocols handled by the desktop shell', () => {
  assert.equal(isExternalLinkHref('https://example.com'), true)
  assert.equal(isExternalLinkHref('mailto:user@example.com'), true)
  assert.equal(isExternalLinkHref('#section'), false)
  assert.equal(isExternalLinkHref('javascript:alert(1)'), false)
})
