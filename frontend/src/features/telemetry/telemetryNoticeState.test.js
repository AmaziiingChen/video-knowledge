import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertTelemetryEnabledState,
  shouldMigrateLegacyTelemetryOptOut,
  shouldShowTelemetryNotice,
} from './telemetryNoticeState.js'

const status = {
  enabled: true,
  privacy_notice_version: '2026-08-telemetry-v3',
  notice_required: true,
  preference_source: 'default_enabled',
}

test('shows the current default-on disclosure exactly until that version is acknowledged', () => {
  assert.equal(shouldShowTelemetryNotice(status, ''), true)
  assert.equal(shouldShowTelemetryNotice(status, '2026-08-telemetry-v2'), true)
  assert.equal(shouldShowTelemetryNotice(status, '2026-08-telemetry-v3'), false)
})

test('does not claim diagnostics are enabled after an explicit opt-out', () => {
  assert.equal(shouldShowTelemetryNotice({ ...status, enabled: false }, ''), false)
  assert.equal(shouldShowTelemetryNotice({}, ''), false)
})

test('requires the current backend disclosure gate before showing default-on copy', () => {
  assert.equal(shouldShowTelemetryNotice({ ...status, notice_required: false }, ''), false)
  assert.equal(shouldShowTelemetryNotice({ ...status, notice_required: undefined }, ''), false)
  assert.equal(shouldShowTelemetryNotice({ ...status, privacy_notice_version: '2026-08-telemetry-v2' }, ''), false)
})

test('migrates only the legacy v2 refusal that the new backend defaulted on', () => {
  assert.equal(shouldMigrateLegacyTelemetryOptOut(status, '2026-08-telemetry-v2'), true)
  assert.equal(shouldMigrateLegacyTelemetryOptOut({ ...status, preference_source: 'explicit_enabled' }, '2026-08-telemetry-v2'), false)
  assert.equal(shouldMigrateLegacyTelemetryOptOut(status, ''), false)
})

test('requires an exact enabled state acknowledgement', () => {
  assert.equal(assertTelemetryEnabledState({ enabled: false }, false).enabled, false)
  assert.throws(() => assertTelemetryEnabledState({ enabled: true }, false), /未确认关闭/)
  assert.throws(() => assertTelemetryEnabledState({}, true), /未确认开启/)
})
