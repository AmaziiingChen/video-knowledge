import assert from 'node:assert/strict'
import test from 'node:test'

import { useTelemetrySettingsController } from './useTelemetrySettingsController.js'

const enabledStatus = {
  enabled: true,
  pending_events: 3,
  privacy_notice_version: '2026-08-telemetry-v3',
}

test('loads a confirmed telemetry state before enabling the settings control', async () => {
  const controller = useTelemetrySettingsController({
    httpClient: { get: async () => ({ data: enabledStatus }) },
  })

  const pending = controller.loadTelemetryStatus()
  assert.equal(controller.telemetryStatusLoading.value, true)
  assert.equal(controller.telemetryStatusLoaded.value, false)
  await pending

  assert.equal(controller.telemetryEnabled.value, true)
  assert.equal(controller.telemetryPendingEvents.value, 3)
  assert.equal(controller.telemetryStatusLoaded.value, true)
  assert.equal(controller.telemetryStatusError.value, '')
})

test('keeps the control unavailable and exposes a retryable status after a read failure', async () => {
  const controller = useTelemetrySettingsController({
    httpClient: { get: async () => { throw new Error('unavailable') } },
  })

  await controller.loadTelemetryStatus()

  assert.equal(controller.telemetryStatusLoaded.value, false)
  assert.equal(controller.telemetryStatusLoading.value, false)
  assert.match(controller.telemetryStatusError.value, /无法读取/)
})

test('saves only an exact disable acknowledgement', async () => {
  const requests = []
  const messages = []
  const controller = useTelemetrySettingsController({
    httpClient: {
      get: async () => ({ data: enabledStatus }),
      put: async (...args) => {
        requests.push(args)
        return { data: { ...enabledStatus, enabled: false, pending_events: 0 } }
      },
    },
    notifySuccess: (message) => messages.push(message),
  })
  await controller.loadTelemetryStatus()

  await controller.saveTelemetry(false)

  assert.deepEqual(requests[0][1], { enabled: false, privacy_notice_version: '' })
  assert.equal(controller.telemetryEnabled.value, false)
  assert.equal(controller.telemetryPendingEvents.value, 0)
  assert.deepEqual(messages, ['已关闭并清除本机遥测数据'])
})

test('uses the loaded disclosure version when diagnostics are enabled again', async () => {
  const requests = []
  const disabledStatus = { ...enabledStatus, enabled: false, pending_events: 0 }
  const controller = useTelemetrySettingsController({
    httpClient: {
      get: async () => ({ data: disabledStatus }),
      put: async (...args) => {
        requests.push(args)
        return { data: enabledStatus }
      },
    },
  })
  await controller.loadTelemetryStatus()

  await controller.saveTelemetry(true)

  assert.deepEqual(requests[0][1], {
    enabled: true,
    privacy_notice_version: '2026-08-telemetry-v3',
  })
  assert.equal(controller.telemetryEnabled.value, true)
})

test('rejects a contradictory 2xx save response and reconciles from the server', async () => {
  const errors = []
  let reads = 0
  const controller = useTelemetrySettingsController({
    httpClient: {
      get: async () => {
        reads += 1
        return { data: reads === 1 ? enabledStatus : { ...enabledStatus, enabled: false, pending_events: 0 } }
      },
      put: async () => ({ data: enabledStatus }),
    },
    notifyError: (message) => errors.push(message),
  })
  await controller.loadTelemetryStatus()

  await controller.saveTelemetry(false)

  assert.equal(reads, 2)
  assert.equal(controller.telemetryEnabled.value, false)
  assert.equal(controller.telemetryStatusLoaded.value, true)
  assert.deepEqual(errors, ['遥测设置保存失败'])
})
