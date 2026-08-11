import assert from 'node:assert/strict'
import test from 'node:test'
import { handleTelemetryRequest } from './collector.js'

const payload = {
  schema_version: 1,
  privacy_notice_version: '2026-08-telemetry-v1',
  installation_id: '2ab1d7b9-5481-4f47-8ba5-94767a8b1be9',
  events: [{
    event_id: '66195774-659b-4c7e-9bd5-bebf8021e6f5', event_name: 'workspace_opened',
    occurred_at: '2026-08-11T10:00:00Z', app_version: '0.1.0', platform: 'macos', architecture: 'arm64', os_major: 15,
    properties: { view: 'library' },
  }],
}

function request(value = payload) {
  return new Request('https://telemetry.example.test/v1/events', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(value),
  })
}

test('accepts only the versioned, fixed telemetry schema and stores no request metadata', async () => {
  const writes = []
  const response = await handleTelemetryRequest(request(), {
    INSTALLATION_HMAC_KEY: 'test-secret', TELEMETRY: { writeDataPoint: (point) => writes.push(point) },
  })
  assert.equal(response.status, 202)
  assert.deepEqual(await response.json(), { accepted: 1 })
  assert.equal(writes.length, 1)
  assert.deepEqual(writes[0].blobs.slice(0, 4), ['workspace_opened', '0.1.0', 'macos', 'arm64'])
  assert.match(writes[0].indexes[0], /^\d{4}-\d{2}:[0-9a-f]{24}$/)
})

test('rejects unexpected fields and never writes a data point', async () => {
  const writes = []
  const invalid = structuredClone(payload)
  invalid.events[0].properties = { view: 'a search term must never arrive here' }
  const response = await handleTelemetryRequest(request(invalid), {
    INSTALLATION_HMAC_KEY: 'test-secret', TELEMETRY: { writeDataPoint: (point) => writes.push(point) },
  })
  assert.equal(response.status, 400)
  assert.equal(writes.length, 0)
})
