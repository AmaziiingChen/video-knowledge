import assert from 'node:assert/strict'
import test from 'node:test'
import { handleTelemetryRequest } from './collector.js'

const INSTALLATION_ID = '2ab1d7b9-5481-4f47-8ba5-94767a8b1be9'
const EVENT_ID = '66195774-659b-4c7e-9bd5-bebf8021e6f5'
const NOTICE_VERSION = '2026-08-telemetry-v2'
const MAX_BODY_BYTES = 256 * 1024

function payloadFor(eventName = 'workspace_opened', properties = { view: 'library' }) {
  return {
    schema_version: 1,
    privacy_notice_version: NOTICE_VERSION,
    installation_id: INSTALLATION_ID,
    events: [{
      schema_version: 1,
      privacy_notice_version: NOTICE_VERSION,
      event_id: EVENT_ID,
      event_name: eventName,
      occurred_at: new Date().toISOString(),
      app_version: '0.1.0',
      platform: 'macos',
      architecture: 'arm64',
      os_major: 15,
      properties,
    }],
  }
}

function request(value = payloadFor(), { method = 'POST', path = '/v1/events', headers = {}, body } = {}) {
  const options = { method, headers: { 'content-type': 'application/json', ...headers } }
  if (method !== 'GET' && method !== 'HEAD') options.body = body ?? JSON.stringify(value)
  return new Request(`https://telemetry.example.test${path}`, options)
}

function environment({ globalAllowed = true, installationAllowed = true, secret = 's'.repeat(32), write } = {}) {
  const writes = []
  const globalKeys = []
  const installationKeys = []
  return {
    writes,
    globalKeys,
    installationKeys,
    env: {
      INSTALLATION_HMAC_KEY: secret,
      TELEMETRY: { writeDataPoint: write || ((point) => writes.push(point)) },
      INGEST_GLOBAL_RATE_LIMITER: {
        limit: async ({ key }) => {
          globalKeys.push(key)
          return { success: globalAllowed }
        },
      },
      INGEST_INSTALLATION_RATE_LIMITER: {
        limit: async ({ key }) => {
          installationKeys.push(key)
          return { success: installationAllowed }
        },
      },
    },
  }
}

test('accepts the exact versioned schema and writes queryable Analytics Engine slots', async () => {
  const harness = environment()
  const value = payloadFor()
  const response = await handleTelemetryRequest(request(value), harness.env)

  assert.equal(response.status, 202)
  assert.deepEqual(await response.json(), { accepted: 1 })
  assert.equal(harness.writes.length, 1)
  const point = harness.writes[0]
  assert.equal(point.blobs.length, 15)
  assert.deepEqual(point.blobs.slice(0, 6), [EVENT_ID, 'workspace_opened', '0.1.0', NOTICE_VERSION, 'macos', 'arm64'])
  assert.equal(point.blobs[14], 'library')
  assert.deepEqual(point.doubles.slice(0, 2), [1, 15])
  assert.equal(point.doubles[2], Date.parse(value.events[0].occurred_at) / 1000)
  assert.match(point.indexes[0], /^\d{4}-\d{2}:[0-9a-f]{24}$/)
  assert.equal(JSON.stringify(point).includes(INSTALLATION_ID), false)
  assert.deepEqual(harness.globalKeys, ['v1-events'])
  assert.equal(harness.installationKeys.length, 1)
  assert.equal(harness.installationKeys[0].includes(INSTALLATION_ID), false)
})

test('accepts every catalog event only with its exact enum properties', async () => {
  const cases = [
    ['app_started', {}], ['workspace_opened', { view: 'library' }], ['import_started', { input_kind: 'link' }],
    ['import_completed', { result: 'accepted' }], ['task_enqueued', { processing_mode: 'full' }],
    ['pipeline_stage_reached', { stage: 'download' }], ['pipeline_stage_failed', { stage: 'asr' }],
    ['task_finished', { result: 'succeeded', stage: 'summary' }], ['task_control_used', { action: 'pause' }],
    ['paddle_ocr_completed', { result: 'empty' }], ['obsidian_sync_completed', { result: 'conflict' }],
    ['search_completed', { result_count_bucket: '21_100' }], ['clipboard_listener_changed', { state: 'enabled' }],
    ['update_check_completed', { result: 'up_to_date' }], ['telemetry_consent_changed', { state: 'enabled' }],
    ['update_download_page_opened', {}], ['export_completed', { export_kind: 'markdown', result: 'succeeded' }],
  ]
  for (const [eventName, properties] of cases) {
    const harness = environment()
    const response = await handleTelemetryRequest(request(payloadFor(eventName, properties)), harness.env)
    assert.equal(response.status, 202, eventName)
    assert.equal(harness.writes.length, 1, eventName)
  }
})

test('rejects prototype event names and all batch or event extra fields', async () => {
  for (const eventName of ['toString', 'valueOf', '__proto__', 'constructor']) {
    const value = payloadFor()
    value.events[0].event_name = eventName
    value.events[0].properties = {}
    const harness = environment()
    assert.equal((await handleTelemetryRequest(request(value), harness.env)).status, 400)
    assert.equal(harness.writes.length, 0)
  }

  for (const mutate of [
    (value) => { value.raw_content = 'private' },
    (value) => { value.events[0].raw_content = 'private' },
    (value) => { delete value.events[0].app_version },
    (value) => { value.events[0].properties.extra = 'private' },
  ]) {
    const value = payloadFor()
    mutate(value)
    const harness = environment()
    assert.equal((await handleTelemetryRequest(request(value), harness.env)).status, 400)
    assert.equal(harness.writes.length, 0)
  }
})

test('rejects mismatched versions, malformed fields and out-of-window timestamps', async () => {
  const mutations = [
    (value) => { value.schema_version = 2 },
    (value) => { value.events[0].schema_version = '1' },
    (value) => { value.events[0].privacy_notice_version = 'old' },
    (value) => { value.events[0].properties.view = 1 },
    (value) => { value.events[0].occurred_at = new Date(Date.now() - 17 * 24 * 60 * 60 * 1000).toISOString() },
    (value) => { value.events[0].occurred_at = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString() },
    (value) => { value.events[0].occurred_at = '2026-08-13T12:00:00+08:00' },
  ]
  for (const mutate of mutations) {
    const value = payloadFor()
    mutate(value)
    const harness = environment()
    assert.equal((await handleTelemetryRequest(request(value), harness.env)).status, 400)
    assert.equal(harness.writes.length, 0)
  }
})

test('enforces route, method, media type and content encoding before parsing', async () => {
  const cases = [
    [request(payloadFor(), { method: 'GET' }), 404],
    [request(payloadFor(), { path: '/other' }), 404],
    [request(payloadFor(), { headers: { 'content-type': 'application/jsonp' } }), 415],
    [request(payloadFor(), { headers: { 'content-type': 'application/json; charset=gbk' } }), 415],
    [request(payloadFor(), { headers: { 'content-encoding': 'gzip' } }), 415],
  ]
  for (const [input, status] of cases) {
    const harness = environment()
    assert.equal((await handleTelemetryRequest(input, harness.env)).status, status)
    assert.equal(harness.writes.length, 0)
  }
  const harness = environment()
  assert.equal((await handleTelemetryRequest(request(payloadFor(), { headers: { 'content-type': 'application/json; charset="utf-8"' } }), harness.env)).status, 202)
})

test('enforces declared and streamed body size without trusting Content-Length', async () => {
  let harness = environment()
  let response = await handleTelemetryRequest(request(payloadFor(), { headers: { 'content-length': String(MAX_BODY_BYTES + 1) } }), harness.env)
  assert.equal(response.status, 413)
  assert.equal(harness.writes.length, 0)

  harness = environment()
  response = await handleTelemetryRequest(request(null, { body: ' '.repeat(MAX_BODY_BYTES + 1) }), harness.env)
  assert.equal(response.status, 413)
  assert.equal(harness.writes.length, 0)

  harness = environment()
  response = await handleTelemetryRequest(request(null, { headers: { 'content-length': 'not-a-number' }, body: '{}' }), harness.env)
  assert.equal(response.status, 400)
})

test('rate limits before writes and returns a bounded retry instruction', async () => {
  let harness = environment({ globalAllowed: false })
  let response = await handleTelemetryRequest(request(), harness.env)
  assert.equal(response.status, 429)
  assert.equal(response.headers.get('retry-after'), '60')
  assert.deepEqual(harness.installationKeys, [])
  assert.deepEqual(harness.writes, [])

  harness = environment({ installationAllowed: false })
  response = await handleTelemetryRequest(request(), harness.env)
  assert.equal(response.status, 429)
  assert.deepEqual(harness.writes, [])
})

test('fails closed when bindings or a sufficiently strong secret are unavailable', async () => {
  for (const mutate of [
    (env) => { delete env.TELEMETRY },
    (env) => { delete env.INGEST_GLOBAL_RATE_LIMITER },
    (env) => { delete env.INGEST_INSTALLATION_RATE_LIMITER },
    (env) => { env.INSTALLATION_HMAC_KEY = 'short' },
  ]) {
    const harness = environment()
    mutate(harness.env)
    assert.equal((await handleTelemetryRequest(request(), harness.env)).status, 503)
    assert.deepEqual(harness.writes, [])
  }
})

test('returns a fixed unavailable error if Analytics Engine rejects a point', async () => {
  const harness = environment({ write: () => { throw new Error(`do not expose ${INSTALLATION_ID}`) } })
  const response = await handleTelemetryRequest(request(), harness.env)
  assert.equal(response.status, 503)
  assert.deepEqual(await response.json(), { error: 'collector_unavailable' })
})
