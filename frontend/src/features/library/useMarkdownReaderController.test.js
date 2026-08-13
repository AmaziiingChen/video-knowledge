import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'
import {
  documentMarkdownWithoutConversation,
  reportMarkdownForCenter,
  sourceMarkdownForCenter,
} from '../assistant/assistantMarkdown.js'

import {
  isExternalMarkdownDocument,
  isForumCaptureDocument,
  isGeneratedReportDocument,
  useMarkdownReaderController,
} from './useMarkdownReaderController.js'

function createController(item, markdown, markdownSize = 0) {
  const selectedContentItem = ref(item)
  const markdownState = reactive({
    markdown,
    markdown_size_bytes: markdownSize,
  })
  return {
    selectedContentItem,
    markdownState,
    controller: useMarkdownReaderController({
      selectedContentItem,
      markdownState,
      render: (value) => value,
      stripReportHeader: (value) => String(value)
        .replace(/^\s*#\s+[^\n]+\n+/u, '')
        .replace(/^\s*>\s*分组：[^\n]+\n+/u, '')
        .trimStart(),
      documentWithoutConversation: documentMarkdownWithoutConversation,
      reportForCenter: reportMarkdownForCenter,
      sourceForCenter: sourceMarkdownForCenter,
    }),
  }
}

test('classifies reports, forum captures, and durable external Markdown without overlap', () => {
  assert.equal(isGeneratedReportDocument({ content_type: 'report', source_provider: 'wechat_report' }), true)
  assert.equal(isGeneratedReportDocument({ content_type: 'report', source_provider: 'wechat_miniprogram' }), false)
  assert.equal(isForumCaptureDocument({ content_type: 'forum_capture', source_provider: 'wechat_miniprogram' }), true)
  assert.equal(isExternalMarkdownDocument({ content_type: 'document', source_provider: 'local_markdown' }), true)
  assert.equal(isExternalMarkdownDocument({ content_type: 'audio', source_provider: 'local_file' }), true)
  assert.equal(isExternalMarkdownDocument({ content_type: 'article', source_provider: 'rss' }), false)
})

test('keeps ordinary source text available to QA while removing it and assistant sections from the reader', () => {
  const markdown = [
    '# 视频标题',
    '',
    '<details>',
    '<summary>原始转写文本</summary>',
    '',
    '逐字稿正文。',
    '',
    '</details>',
    '',
    '## AI 摘要',
    '',
    '摘要。',
    '',
    '## 追问记录',
    '',
    '问答。',
  ].join('\n')
  const { controller } = createController(
    { content_type: 'video', source_provider: 'bilibili' },
    markdown,
  )
  assert.equal(controller.selectedMarkdownPreview.value, '# 视频标题')
  assert.equal(controller.selectedMarkdownSourceText.value, '逐字稿正文。')
})

test('renders imported documents from canonical source Markdown and strips assistant history', () => {
  const markdown = [
    '# 本地文档',
    '',
    '正文内容。',
    '',
    '## AI 摘要',
    '',
    '摘要。',
    '',
    '## 追问记录',
    '',
    '问答。',
  ].join('\n')
  const { controller } = createController(
    { content_type: 'document', source_provider: 'local_file' },
    markdown,
  )
  assert.equal(controller.selectedMarkdownPreview.value, '# 本地文档\n\n正文内容。')
  assert.equal(controller.selectedMarkdownSourceText.value, '# 本地文档\n\n正文内容。')
})

test('keeps forum captures out of report mode and removes only their duplicate title', () => {
  const markdown = '# 论坛标题\n\n论坛正文。\n\n## AI 摘要\n\n摘要。'
  const { controller } = createController(
    { content_type: 'report', source_provider: 'wechat_miniprogram' },
    markdown,
  )
  assert.equal(controller.selectedMarkdownPreview.value, '论坛正文。')
  assert.equal(controller.selectedReportSourceStats.value.analyzed, 0)
})

test('normalizes report bodies, source statistics, and UTF-8 size fallback', () => {
  const markdown = [
    '# 周报',
    '',
    '> 分组：测试',
    '',
    '> 分析文章：12 篇 · 正文引用：3 篇',
    '',
    '## 报告正文',
    '',
    '报告正文。',
    '',
    '## 追问记录',
    '',
    '问答。',
  ].join('\n')
  const state = createController(
    { content_type: 'report', source_provider: 'wechat_report' },
    markdown,
  )
  assert.equal(
    state.controller.selectedMarkdownPreview.value,
    '> 分析文章：12 篇 · 正文引用：3 篇\n\n报告正文。',
  )
  assert.deepEqual(state.controller.selectedReportSourceStats.value, { analyzed: 12, referenced: 3 })
  assert.equal(state.controller.selectedMarkdownSizeBytes.value, new TextEncoder().encode(markdown).length)

  state.markdownState.markdown_size_bytes = 4096
  assert.equal(state.controller.selectedMarkdownSizeBytes.value, 4096)
})
