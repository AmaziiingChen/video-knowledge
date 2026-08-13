import test from 'node:test'
import assert from 'node:assert/strict'

import { useConversationMarkdownExportController } from './useConversationMarkdownExportController.js'

function notificationRecorder() {
  const messages = { warning: [], success: [], error: [] }
  return {
    messages,
    notify: {
      warning: (message) => messages.warning.push(message),
      success: (message) => messages.success.push(message),
      error: (message) => messages.error.push(message),
    },
  }
}

test('does not export an empty conversation', async () => {
  const { messages, notify } = notificationRecorder()
  let requestCount = 0
  const controller = useConversationMarkdownExportController({
    getConversation: () => ({ history: [] }),
    getDesktopExport: () => null,
    notify,
    request: {
      async post() {
        requestCount += 1
      }
    }
  })

  await controller.exportConversationMarkdown()

  assert.equal(requestCount, 0)
  assert.equal(controller.exportingConversationMarkdown.value, false)
  assert.deepEqual(messages.warning, ['当前没有可导出的 AI 总结或对话'])
})

test('prefers the desktop bridge and builds the established Markdown document', async () => {
  const calls = []
  const telemetry = []
  const { messages, notify } = notificationRecorder()
  const controller = useConversationMarkdownExportController({
    getConversation: () => ({
      content: { title: '示例\n标题', source_url: 'https://example.com/article' },
      summary: ' 核心总结 ',
      history: [
        { question: '问题一', answer: '回答一' },
        { question: '问题二', answer: '' },
        { question: ' ', answer: ' ' },
      ],
    }),
    getDesktopExport: () => async (title, markdown) => {
      calls.push({ title, markdown })
      return { path: '/exports/example.md' }
    },
    recordTelemetry: (...args) => telemetry.push(args),
    notify,
    request: {
      post() {
        throw new Error('unexpected backend request')
      }
    },
  })

  await controller.exportConversationMarkdown()

  assert.deepEqual(calls, [{
    title: '示例 标题-AI对话',
    markdown: [
      '# 示例 标题',
      '来源：https://example.com/article',
      '## AI 总结\n\n核心总结',
      '## 对话\n\n### 我\n\n问题一\n\n### AI\n\n回答一\n\n---\n\n### 我\n\n问题二\n\n### AI\n\n（尚未生成回答）',
    ].join('\n\n') + '\n',
  }])
  assert.deepEqual(messages.success, ['Markdown 已导出到 /exports/example.md'])
  assert.deepEqual(telemetry, [[
    'export_completed',
    { export_kind: 'markdown', result: 'succeeded' },
  ]])
  assert.equal(controller.exportingConversationMarkdown.value, false)
})

test('falls back to the local API with the same title and Markdown', async () => {
  const calls = []
  const { notify } = notificationRecorder()
  const controller = useConversationMarkdownExportController({
    apiBase: '/api',
    getConversation: () => ({
      fallbackTitle: '备用标题',
      fallbackSourceUrl: 'https://example.com/fallback',
      history: [{ question: '问题', answer: '回答' }],
    }),
    getDesktopExport: () => null,
    notify,
    request: {
      async post(url, body, options) {
        calls.push({ url, body, options })
        return { data: { path: '/vault/fallback.md' } }
      }
    },
  })

  await controller.exportConversationMarkdown()

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/markdown/export')
  assert.equal(calls[0].body.title, '备用标题-AI对话')
  assert.match(calls[0].body.markdown, /^# 备用标题\n\n来源：https:\/\/example\.com\/fallback/u)
  assert.deepEqual(calls[0].options, { timeout: 15000 })
})

test('reports a backend failure, records telemetry and always releases the export lock', async () => {
  const telemetry = []
  const { messages, notify } = notificationRecorder()
  const controller = useConversationMarkdownExportController({
    getConversation: () => ({ summary: '可导出的总结' }),
    getDesktopExport: () => null,
    recordTelemetry: (...args) => telemetry.push(args),
    notify,
    request: {
      async post() {
        throw { response: { data: { detail: '导出目录不可写' } } }
      }
    },
  })

  await controller.exportConversationMarkdown()

  assert.deepEqual(messages.error, ['导出目录不可写'])
  assert.deepEqual(telemetry, [[
    'export_completed',
    { export_kind: 'markdown', result: 'failed' },
  ]])
  assert.equal(controller.exportingConversationMarkdown.value, false)
})
