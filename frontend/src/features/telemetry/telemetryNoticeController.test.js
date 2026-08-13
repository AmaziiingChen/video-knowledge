import assert from 'node:assert/strict'
import test from 'node:test'

import { createTelemetryNoticeController } from './telemetryNoticeController.js'

const defaultOnStatus = {
  enabled: true,
  privacy_notice_version: '2026-08-telemetry-v3',
  notice_required: true,
  preference_source: 'default_enabled',
}

test('preserves a legacy v2 refusal before showing the default-on notice', async () => {
  const updates = []
  const remembered = []
  let disableCalls = 0
  const controller = createTelemetryNoticeController({
    fetchStatus: async () => defaultOnStatus,
    disableTelemetry: async () => {
      disableCalls += 1
      return { ...defaultOnStatus, enabled: false, notice_required: false, preference_source: 'explicit_disabled' }
    },
    readSeenVersion: () => '2026-08-telemetry-v2',
    rememberVersion: (version) => remembered.push(version),
    updateNotice: (state) => updates.push(state),
  })

  await controller.start()

  assert.equal(disableCalls, 1)
  assert.deepEqual(remembered, ['2026-08-telemetry-v3'])
  assert.deepEqual(updates, [{ version: '2026-08-telemetry-v3', visible: false }])
})

test('keeps the notice visible when a 2xx migration response still says enabled', async () => {
  const updates = []
  const controller = createTelemetryNoticeController({
    fetchStatus: async () => defaultOnStatus,
    disableTelemetry: async () => defaultOnStatus,
    readSeenVersion: () => '2026-08-telemetry-v2',
    rememberVersion: () => assert.fail('must not remember an unconfirmed opt-out'),
    updateNotice: (state) => updates.push(state),
  })

  await controller.start()

  assert.deepEqual(updates, [{ version: '2026-08-telemetry-v3', visible: true }])
})

test('retries failed status reads at bounded absolute offsets before 60 seconds', async () => {
  const scheduled = []
  let clock = 10_000
  let calls = 0
  const controller = createTelemetryNoticeController({
    fetchStatus: async () => {
      calls += 1
      throw new Error('backend is still starting')
    },
    disableTelemetry: async () => assert.fail('no status was loaded'),
    readSeenVersion: () => '',
    rememberVersion: () => {},
    updateNotice: () => assert.fail('failed reads must not invent status'),
    retryOffsets: [0, 2_000, 6_000],
    schedule: (callback, delay) => {
      scheduled.push({ callback, delay })
      return scheduled.length
    },
    cancelSchedule: () => {},
    now: () => clock,
  })

  await controller.start()
  assert.equal(calls, 1)
  assert.equal(scheduled[0].delay, 2_000)

  clock = 12_000
  await scheduled.shift().callback()
  assert.equal(calls, 2)
  assert.equal(scheduled[0].delay, 4_000)

  clock = 16_000
  await scheduled.shift().callback()
  assert.equal(calls, 3)
  assert.equal(scheduled.length, 0)
})
