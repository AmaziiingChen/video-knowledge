import assert from 'node:assert/strict'
import test from 'node:test'

import { createQaResponseStreamController } from './createQaResponseStreamController.js'

function immediateRenderer({ onCommit }) {
  return {
    enqueue: (text) => onCommit(text),
    drain: () => Promise.resolve(),
    flush: () => {},
  }
}

function streamResponse(blocks) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({
    start(controller) {
      blocks.forEach((block) => controller.enqueue(encoder.encode(block)))
      controller.close()
    }
  }))
}

test('applies deltas, usage, and matching markdown state from a completed QA stream', async () => {
  const aiCalls = []
  const markdownStates = []
  const histories = []
  const session = { lastSaved: false }
  const pendingItem = { answer: '', pending: true }
  const controller = createQaResponseStreamController({
    appendContentAiCall: (...args) => aiCalls.push(args),
    getSelectedContentItem: () => ({ id: 'content-1' }),
    applyMarkdownState: (state) => markdownStates.push(state),
    refreshQaSessionHistory: (...args) => histories.push(args),
    refreshFallbackHistory: () => assert.fail('session stream must not refresh fallback history'),
    setLastQaSaved: () => assert.fail('session stream must not use fallback saved state'),
    createStreamRenderer: immediateRenderer,
  })

  await controller.readQaStream(streamResponse([
    'event: delta\ndata: {"text":"第一段"}\n\n',
    'event: usage\ndata: {"total_tokens":12}\n\n',
    'event: done\ndata: {"answer":"最终回答","assistant_message_id":"assistant-1","saved_to_markdown":true,"saved_to_content":true,"markdown_state":{"markdown":"# 已保存"}}\n\n',
  ]), pendingItem, 'content-1', { session })

  assert.equal(pendingItem.answer, '最终回答')
  assert.equal(pendingItem.id, 'assistant-1')
  assert.equal(pendingItem.pending, false)
  assert.equal(pendingItem.saved, true)
  assert.equal(pendingItem.savedToContent, true)
  assert.equal(session.lastSaved, true)
  assert.deepEqual(aiCalls, [['content-1', { total_tokens: 12 }]])
  assert.deepEqual(markdownStates, [{ markdown: '# 已保存' }])
  assert.ok(histories.length >= 2)
})

test('fails closed when the QA stream reports an error event', async () => {
  const controller = createQaResponseStreamController({
    appendContentAiCall: () => {},
    getSelectedContentItem: () => null,
    applyMarkdownState: () => {},
    refreshQaSessionHistory: () => {},
    refreshFallbackHistory: () => {},
    setLastQaSaved: () => {},
    createStreamRenderer: immediateRenderer,
  })

  await assert.rejects(
    controller.readQaStream(
      streamResponse(['event: error\ndata: {"error":"模型拒绝请求"}\n\n']),
      { answer: '', pending: true },
      'content-1',
    ),
    /模型拒绝请求/,
  )
})

test('does not replace a newly selected document markdown after an older QA stream finishes', async () => {
  const markdownStates = []
  const controller = createQaResponseStreamController({
    appendContentAiCall: () => {},
    getSelectedContentItem: () => ({ id: 'content-newer' }),
    applyMarkdownState: (state) => markdownStates.push(state),
    refreshQaSessionHistory: () => {},
    refreshFallbackHistory: () => {},
    setLastQaSaved: () => {},
    createStreamRenderer: immediateRenderer,
  })

  await controller.readQaStream(
    streamResponse(['event: done\ndata: {"answer":"旧回答","markdown_state":{"markdown":"# 旧内容"}}\n\n']),
    { answer: '', pending: true },
    'content-older',
  )

  assert.deepEqual(markdownStates, [])
})

test('keeps reasoning separate, collapses on answer, and accepts authoritative suggestions', async () => {
  const pendingItem = { answer: '', reasoning: '', reasoningExpanded: false, pending: true }
  const session = { lastSaved: false, suggestedQuestions: [] }
  const controller = createQaResponseStreamController({
    appendContentAiCall: () => {},
    getSelectedContentItem: () => ({ id: 'content-1' }),
    applyMarkdownState: () => {},
    refreshQaSessionHistory: () => {},
    refreshFallbackHistory: () => {},
    setLastQaSaved: () => {},
    createStreamRenderer: immediateRenderer,
  })

  await controller.readQaStream(streamResponse([
    'event: reasoning_delta\ndata: {"text":"先核对"}\n\n',
    'event: delta\ndata: {"text":"正文"}\n\n',
    'event: done\ndata: {"answer":"正文","reasoning_content":"先核对","suggested_questions":["继续问？"]}\n\n',
  ]), pendingItem, 'content-1', { session })

  assert.equal(pendingItem.answer, '正文')
  assert.equal(pendingItem.reasoning, '先核对')
  assert.equal(pendingItem.reasoningExpanded, false)
  assert.deepEqual(pendingItem.suggestedQuestions, ['继续问？'])
  assert.deepEqual(session.suggestedQuestions, ['继续问？'])
})

test('reasoning-only interrupted stream fails without inventing an answer', async () => {
  const pendingItem = { answer: '', reasoning: '', pending: true }
  const controller = createQaResponseStreamController({
    appendContentAiCall: () => {}, getSelectedContentItem: () => null,
    applyMarkdownState: () => {}, refreshQaSessionHistory: () => {},
    refreshFallbackHistory: () => {}, setLastQaSaved: () => {},
    createStreamRenderer: immediateRenderer,
  })
  await assert.rejects(
    controller.readQaStream(streamResponse([
      'event: reasoning_delta\ndata: {"text":"未完成思考"}',
    ]), pendingItem, 'content-1'),
    /提前结束/,
  )
  assert.equal(pendingItem.answer, '')
})
