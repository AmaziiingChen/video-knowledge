import assert from 'node:assert/strict'
import test from 'node:test'

import { useCookieStatusController } from './useCookieStatusController.js'

function createController({ request = {}, requestIdle = () => null } = {}) {
  const warnings = []
  const timeouts = []
  const cancelledTimeouts = []
  const intervals = []
  const cancelledIntervals = []
  const controller = useCookieStatusController({
    notify: { warning: (options) => warnings.push(options) },
    request: { get: async () => ({ data: {} }), ...request },
    apiBase: 'http://api.test',
    requestIdle,
    cancelIdle: () => {},
    scheduleTimeout: (callback, delay) => {
      const timer = { callback, delay }
      timeouts.push(timer)
      return timer
    },
    cancelTimeout: (timer) => cancelledTimeouts.push(timer),
    scheduleInterval: (callback, delay) => {
      const timer = { callback, delay }
      intervals.push(timer)
      return timer
    },
    cancelInterval: (timer) => cancelledIntervals.push(timer),
  })
  return { controller, warnings, timeouts, cancelledTimeouts, intervals, cancelledIntervals }
}

test('reads only status data and alerts once for a newly invalid Douyin login', async () => {
  const calls = []
  const { controller, warnings } = createController({
    request: {
      get: async (...args) => {
        calls.push(args)
        return { data: { configured: true, state: 'invalid', label: '登录已失效', detail: '请重新连接' } }
      },
    },
  })

  await controller.loadCookieStatus(true, { probe: false })
  await controller.loadCookieStatus(true, { probe: false })
  assert.deepEqual(calls, [
    ['http://api.test/cookie', { params: { refresh: true, probe: false }, timeout: 30000 }],
    ['http://api.test/cookie', { params: { refresh: true, probe: false }, timeout: 30000 }],
  ])
  assert.equal(controller.cookieConfigured.value, true)
  assert.equal(controller.cookieState.value, 'invalid')
  assert.equal(controller.cookieStatusDetail.value, '请重新连接')
  assert.equal(warnings.length, 1)
})

test('Bilibili status never probes Douyin and reports a usable failure state', async () => {
  const calls = []
  const { controller } = createController({
    request: {
      get: async (...args) => {
        calls.push(args)
        return { data: { cookies: { bilibili: { configured: true, state: 'valid', detail: '可用' } } } }
      },
    },
  })
  await controller.loadBilibiliCookieStatus(true)
  assert.deepEqual(calls, [[
    'http://api.test/creator-sources/health',
    { params: { refresh: true, probe_douyin: false }, timeout: 15000 },
  ]])
  assert.equal(controller.bilibiliCookieConfigured.value, true)
  assert.equal(controller.bilibiliCookieState.value, 'valid')
  assert.equal(controller.bilibiliCookieStatusText.value, '可用')
})

test('idle fallback and periodic polling can both be cancelled', () => {
  const { controller, timeouts, cancelledTimeouts, intervals, cancelledIntervals } = createController()
  controller.scheduleDeferredCookieProbe()
  assert.equal(timeouts[0].delay, 1500)
  controller.cancelDeferredCookieProbe()
  assert.deepEqual(cancelledTimeouts, [timeouts[0]])

  controller.startCookieStatusPolling()
  controller.startCookieStatusPolling()
  assert.deepEqual(intervals.map((timer) => timer.delay), [60000, 300000])
  controller.stopCookieStatusPolling()
  assert.deepEqual(cancelledIntervals, intervals)
})
