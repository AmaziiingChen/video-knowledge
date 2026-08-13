import assert from 'node:assert/strict'
import test from 'node:test'

import { useAiUsageController } from './useAiUsageController.js'

function usageRequest(responses) {
  const calls = []
  return {
    calls,
    get(url) {
      calls.push(url)
      const response = responses[url]
      if (response instanceof Error) return Promise.reject(response)
      return Promise.resolve({ data: response })
    },
  }
}

test('loads content calls without turning a failed read into an empty audit trail', async () => {
  const request = usageRequest({
    '/api/content/item-1/ai-calls': [{ id: 'call-1', type: 'summary' }],
    '/api/content/item-2/ai-calls': new Error('offline'),
  })
  const controller = useAiUsageController({ request, apiBase: '/api' })

  await controller.loadContentAiCalls('item-1')
  await controller.loadContentAiCalls('item-2')

  assert.deepEqual(controller.aiCallsByContentId['item-1'], [{ id: 'call-1', type: 'summary' }])
  assert.equal(controller.aiCallsByContentId['item-2'], undefined)
  assert.deepEqual(request.calls, ['/api/content/item-1/ai-calls', '/api/content/item-2/ai-calls'])
})

test('updates each usage source independently and normalizes malformed optional fields', async () => {
  const request = usageRequest({
    '/api/ai-calls/summary': {
      period_start: 123,
      call_count: '2',
      total_tokens: '14',
      by_type: 'not-an-array',
      image_count: '3',
    },
    '/api/openclaw/usage': new Error('unavailable'),
  })
  const controller = useAiUsageController({ request, apiBase: '/api' })

  await controller.loadAiTokenUsageSummary()

  assert.equal(controller.dailyAiTokenUsage.value.period_start, '123')
  assert.equal(controller.dailyAiTokenUsage.value.call_count, 2)
  assert.equal(controller.dailyAiTokenUsage.value.total_tokens, 14)
  assert.deepEqual(controller.dailyAiTokenUsage.value.by_type, [])
  assert.equal(controller.dailyAiTokenUsage.value.image_count, 3)
  assert.equal(controller.openClawTokenUsage.value.available, false)
})

test('coalesces summary refreshes and owns the polling timer lifecycle', async () => {
  let resolveKnowledge
  let resolveOpenClaw
  const calls = []
  const request = {
    get(url) {
      calls.push(url)
      return new Promise((resolve) => {
        if (url.endsWith('/ai-calls/summary')) resolveKnowledge = resolve
        else resolveOpenClaw = resolve
      })
    },
  }
  const scheduled = []
  const cancelled = []
  const controller = useAiUsageController({
    request,
    apiBase: '/api',
    schedule(callback, delay) {
      scheduled.push({ callback, delay })
      return `timer-${scheduled.length}`
    },
    cancel(timer) {
      cancelled.push(timer)
    },
  })

  controller.startAiTokenUsagePolling()
  controller.startAiTokenUsagePolling()
  await controller.loadAiTokenUsageSummary()

  assert.deepEqual(calls, ['/api/ai-calls/summary', '/api/openclaw/usage'])
  assert.equal(scheduled.length, 1)
  assert.equal(scheduled[0].delay, 15000)
  resolveKnowledge({ data: { call_count: 4 } })
  resolveOpenClaw({ data: { available: true, total_tokens: 8 } })
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(controller.dailyAiTokenUsage.value.call_count, 4)
  assert.equal(controller.openClawTokenUsage.value.total_tokens, 8)
  controller.stopAiTokenUsagePolling()
  controller.stopAiTokenUsagePolling()
  assert.deepEqual(cancelled, ['timer-1'])
})
