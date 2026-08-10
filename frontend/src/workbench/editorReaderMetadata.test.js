import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatReadableCharacterCount,
  formatReaderDocumentSize,
  readerMetadataText,
  sourceBodyForCharacterCount,
} from './editorReaderMetadata.js'

const htmlToText = (html) => String(html || '').replace(/<[^>]+>/gu, '')

function readerText(overrides = {}) {
  return readerMetadataText({
    content: { id: 'content-1' },
    kind: 'source',
    htmlToText,
    ...overrides,
  })
}

test('extracts wrapped source sections without frontmatter or import affordances', () => {
  const markdown = [
    '---',
    'title: imported',
    '---',
    '## 原文内容',
    '> 外部导入 · 本地文档',
    '[打开原始文件](/api/media?path=file)',
    '可阅读正文。',
    '## AI 摘要',
    '摘要。',
  ].join('\n')
  assert.equal(sourceBodyForCharacterCount(markdown, ['原文内容']), '可阅读正文。')
})

test('uses timeline text for media and falls back to the stored transcript', () => {
  assert.equal(readerText({
    kind: 'timed-media',
    timelineSegments: [{ text: '第一段' }, { text: '第二段' }],
    transcript: '旧转写',
  }), '第一段\n第二段')
  assert.equal(readerText({
    kind: 'timed-media',
    transcript: '## 字幕\n最新转写',
  }), '最新转写')
})

test('uses parsed image and article text before rendered fallbacks', () => {
  assert.equal(readerText({
    kind: 'external-image',
    transcript: '## OCR 正文\n图片正文',
  }), '图片正文')
  assert.equal(readerText({
    kind: 'article',
    transcript: '## 文章正文\n文章正文',
    articlePreviewText: '网页正文',
  }), '文章正文')
  assert.equal(readerText({
    kind: 'article',
    transcript: '',
    articlePreviewText: '网页正文',
  }), '网页正文')
})

test('normalizes long-form HTML and prefers mounted capture text', () => {
  const html = '<p>正文<sup class="markdown-footnote-ref">[1]</sup></p><section class="markdown-footnotes">来源</section>'
  assert.equal(readerText({
    kind: 'report',
    selectedMarkdownPreview: html,
  }), '正文')
  assert.equal(readerText({
    kind: 'mini-program-capture',
    selectedMarkdownPreview: '<p>预览正文</p>',
    captureText: '已挂载正文',
  }), '已挂载正文')
})

test('formats readable characters and selected document size without stale live bytes', () => {
  assert.equal(formatReadableCharacterCount('中 A\n🙂'), '3 字')
  assert.equal(formatReadableCharacterCount(' \n'), '—')
  const formatBytes = (value) => `${value} B`
  assert.equal(formatReaderDocumentSize(
    { id: 'current', markdown_size_bytes: 10 },
    { selectedContentId: 'current', selectedMarkdownSizeBytes: 42, formatBytes },
  ), '42 B')
  assert.equal(formatReaderDocumentSize(
    { id: 'other', markdown_size_bytes: 10 },
    { selectedContentId: 'current', selectedMarkdownSizeBytes: 42, formatBytes },
  ), '10 B')
  assert.equal(formatReaderDocumentSize(
    { id: 'empty', markdown_size_bytes: 0 },
    { selectedContentId: 'current', selectedMarkdownSizeBytes: 0, formatBytes },
  ), '—')
})
