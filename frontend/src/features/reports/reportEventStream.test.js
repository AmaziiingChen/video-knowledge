import assert from 'node:assert/strict'
import test from 'node:test'

import { consumeReportEventStream } from './reportEventStream.js'

function streamedResponse(chunks) {
  let index = 0
  const encoder = new TextEncoder()
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => {
          if (index >= chunks.length) return { done: true }
          return { done: false, value: encoder.encode(chunks[index++]) }
        },
      }),
    },
  }
}

test('posts the existing report payload and reconstructs split progress and completion events', async () => {
  const calls = []
  const progress = []
  const result = await consumeReportEventStream('/api/reports/generate-stream', { report_type: 'weekly' }, (event) => progress.push(event), {
    requestUrl: (url) => `local:${url}`,
    authHeaders: async (headers) => ({ ...headers, 'X-KnowledgeHub-Token': 'capability' }),
    request: async (...args) => {
      calls.push(args)
      return streamedResponse([
        'data: {"event":"progress","progress":25,"message":"准备中"}\n\n',
        'data: {"event":"complete","result":{"source_count":',
        '3}}\n\n',
      ])
    },
  })

  assert.deepEqual(calls, [[
    'local:/api/reports/generate-stream',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-KnowledgeHub-Token': 'capability' },
      body: '{"report_type":"weekly"}',
    },
  ]])
  assert.deepEqual(progress, [{ event: 'progress', progress: 25, message: '准备中' }])
  assert.deepEqual(result, { source_count: 3 })
})

test('preserves backend errors and rejects streams without a completion result', async () => {
  await assert.rejects(
    consumeReportEventStream('/api/reports/generate-stream', {}, undefined, {
      request: async () => ({ ok: false, status: 422, json: async () => ({ detail: '缺少报告范围' }) }),
      requestUrl: (url) => url,
      authHeaders: async () => ({}),
    }),
    /缺少报告范围/u,
  )
  await assert.rejects(
    consumeReportEventStream('/api/reports/generate-stream', {}, undefined, {
      request: async () => streamedResponse(['data: {"event":"progress","progress":90}\n\n']),
      requestUrl: (url) => url,
      authHeaders: async () => ({}),
    }),
    /没有收到完成结果/u,
  )
})

test('turns an explicit stream error into the existing error contract', async () => {
  await assert.rejects(
    consumeReportEventStream('/api/reports/generate-stream', {}, undefined, {
      request: async () => streamedResponse(['data: {"event":"error","message":"模型不可用"}\n\n']),
      requestUrl: (url) => url,
      authHeaders: async () => ({}),
    }),
    /模型不可用/u,
  )
})
