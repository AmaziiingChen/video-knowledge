import assert from 'node:assert/strict'
import test from 'node:test'

import { useOpenClawController } from './useOpenClawController.js'

function createController() {
  const intervals = []
  const cancelled = []
  const requests = []
  const controller = useOpenClawController({
    apiBase: 'http://api.test',
    notify: { success() {}, warning() {}, error() {} },
    request: {
      get: async (...args) => {
        requests.push(args)
        return { data: { state: 'offline', detail: 'Gateway 未响应', gateway_running: false } }
      },
      post: async () => ({ data: {} }),
    },
    scheduleInterval: (callback, delay) => {
      const timer = { callback, delay }
      intervals.push(timer)
      return timer
    },
    cancelInterval: (timer) => cancelled.push(timer),
  })
  return { controller, intervals, cancelled, requests }
}

test('polls expensive OpenClaw status at a low frequency and remains cancellable', () => {
  const { controller, intervals, cancelled } = createController()

  controller.startOpenClawStatusPolling()
  controller.startOpenClawStatusPolling()

  assert.deepEqual(intervals.map((timer) => timer.delay), [5 * 60 * 1000])
  controller.stopOpenClawStatusPolling()
  assert.deepEqual(cancelled, intervals)
})

test('initial and forced status reads keep the existing API contract', async () => {
  const { controller, requests } = createController()

  await controller.loadOpenClawStatus()
  await controller.loadOpenClawStatus(true)

  assert.deepEqual(requests, [
    ['http://api.test/openclaw-gateway', { params: undefined, timeout: 30000 }],
    ['http://api.test/openclaw-gateway', { params: { refresh: true }, timeout: 30000 }],
  ])
  assert.equal(controller.openclawRunning.value, false)
  assert.equal(controller.openclawStatusText.value, 'Gateway 未响应')
})

test('repairs only the KnowledgeHub MCP entry through the local API and refreshes its status', async () => {
  const notifications = []
  const calls = []
  const controller = useOpenClawController({
    apiBase: 'http://api.test',
    notify: {
      success: (message) => notifications.push(['success', message]),
      error: (message) => notifications.push(['error', message]),
      warning() {},
    },
    request: {
      get: async () => ({ data: {} }),
      post: async (...args) => {
        calls.push(args)
        return {
          data: {
            state: 'running',
            detail: 'Gateway 与本地 RPC 已连接',
            installed: true,
            gateway_running: true,
            mcp: { configured: true, detail: 'KnowledgeHub MCP 已就绪' },
          }
        }
      },
    },
  })

  await controller.repairOpenClawMcp()

  assert.deepEqual(calls, [['http://api.test/openclaw-gateway/repair-mcp', {}, { timeout: 45000 }]])
  assert.equal(controller.openclawMcpRepairAvailable.value, false)
  assert.deepEqual(notifications, [['success', 'KnowledgeHub MCP 已修复并完成自检']])
})
