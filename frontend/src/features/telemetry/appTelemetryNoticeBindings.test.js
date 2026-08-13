import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const appSource = await readFile(new URL('../../App.vue', import.meta.url), 'utf8')

test('the root notice acknowledges locally and performs a real backend opt-out', () => {
  assert.match(appSource, /@acknowledge="acknowledgeTelemetryNotice"/)
  assert.match(appSource, /@disable="disableTelemetryFromNotice"/)
  assert.match(appSource, /createTelemetryNoticeController\(\{/)
  assert.match(appSource, /disableTelemetry: requestTelemetryDisabled/)
  assert.match(appSource, /return assertTelemetryEnabledState\(response\.data \|\| \{\}, false\)/)
  assert.match(appSource, /void telemetryNoticeController\.start\(\)/)
  assert.match(appSource, /telemetryNoticeController\.stop\(\)/)
  assert.doesNotMatch(appSource, /@dismiss="dismissTelemetryNotice"/)
})
