const SCHEMA_VERSION = 1
const CURRENT_PRIVACY_NOTICE_VERSION = '2026-08-telemetry-v3'
const ACCEPTED_PRIVACY_NOTICE_VERSIONS = new Set([
  '2026-08-telemetry-v2',
  CURRENT_PRIVACY_NOTICE_VERSION,
])
const MAX_EVENTS_PER_REQUEST = 100
const MAX_BODY_BYTES = 256 * 1024
const MAX_EVENT_AGE_MS = 16 * 24 * 60 * 60 * 1000
const MAX_FUTURE_SKEW_MS = 24 * 60 * 60 * 1000
const MIN_SECRET_BYTES = 32

const BATCH_FIELDS = ['schema_version', 'privacy_notice_version', 'installation_id', 'events']
const EVENT_FIELDS_REQUIRED = [
  'schema_version', 'privacy_notice_version', 'event_id', 'event_name', 'occurred_at',
  'app_version', 'platform', 'architecture', 'os_major', 'properties',
]
const PROPERTY_ORDER = [
  'action', 'export_kind', 'input_kind', 'processing_mode', 'result',
  'result_count_bucket', 'stage', 'state', 'view',
]

const EVENT_FIELDS = Object.freeze({
  app_started: [], workspace_opened: ['view'], import_started: ['input_kind'], import_completed: ['result'],
  task_enqueued: ['processing_mode'], pipeline_stage_reached: ['stage'], pipeline_stage_failed: ['stage'],
  task_finished: ['result', 'stage'], task_control_used: ['action'], paddle_ocr_completed: ['result'],
  obsidian_sync_completed: ['result'], search_completed: ['result_count_bucket'],
  clipboard_listener_changed: ['state'], update_check_completed: ['result'],
  telemetry_consent_changed: ['state'], update_download_page_opened: [],
  export_completed: ['export_kind', 'result'],
})

const ENUM_VALUES = Object.freeze({
  action: new Set(['retry', 'pause', 'resume', 'cancel']),
  export_kind: new Set(['markdown', 'other']), input_kind: new Set(['link', 'other']),
  processing_mode: new Set(['full', 'transcript', 'other']),
  result: new Set(['accepted', 'available', 'conflict', 'disabled', 'empty', 'failed', 'succeeded', 'unavailable', 'up_to_date', 'other']),
  result_count_bucket: new Set(['0', '1_5', '6_20', '21_100', '101_plus', 'other']),
  stage: new Set(['analyze', 'asr', 'download', 'executor', 'export', 'ocr', 'prepare', 'queued', 'summary', 'transcribe', 'unknown', 'other']),
  state: new Set(['enabled', 'disabled', 'other']),
  view: new Set(['campus', 'creator', 'knowledge', 'library', 'prompts', 'reports', 'rss', 'wechat', 'other']),
})

const RFC3339_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/

function json(status, value, headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      ...headers,
    },
  })
}

function hasExactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const keys = Object.keys(value)
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key))
}

function validUuid(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
}

function parsedOccurredAt(value, nowMs) {
  if (typeof value !== 'string' || !RFC3339_UTC.test(value)) return null
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp) || timestamp < nowMs - MAX_EVENT_AGE_MS || timestamp > nowMs + MAX_FUTURE_SKEW_MS) return null
  return timestamp
}

function validEvent(event, nowMs, noticeVersion) {
  if (!hasExactKeys(event, EVENT_FIELDS_REQUIRED)) return false
  if (event.schema_version !== SCHEMA_VERSION || event.privacy_notice_version !== noticeVersion) return false
  if (!validUuid(event.event_id) || !Object.hasOwn(EVENT_FIELDS, event.event_name)) return false
  if (parsedOccurredAt(event.occurred_at, nowMs) === null) return false
  if (typeof event.app_version !== 'string' || !/^[0-9A-Za-z._-]{1,40}$/.test(event.app_version)) return false
  if (event.platform !== 'darwin' && event.platform !== 'macos') return false
  if (!['arm64', 'x64', 'other'].includes(event.architecture) || !Number.isInteger(event.os_major) || event.os_major < 10 || event.os_major > 99) return false

  const allowed = EVENT_FIELDS[event.event_name]
  if (!hasExactKeys(event.properties, allowed)) return false
  return allowed.every((key) => typeof event.properties[key] === 'string' && ENUM_VALUES[key].has(event.properties[key]))
}

function validContentType(value) {
  if (typeof value !== 'string') return false
  const parts = value.split(';').map((part) => part.trim().toLowerCase()).filter(Boolean)
  return parts[0] === 'application/json' && parts.slice(1).every((part) => /^charset\s*=\s*"?utf-8"?$/.test(part))
}

async function readBoundedJson(request) {
  const declaredLength = request.headers.get('content-length')
  if (declaredLength !== null) {
    if (!/^\d+$/.test(declaredLength)) return { error: 'invalid_payload' }
    const length = Number(declaredLength)
    if (!Number.isSafeInteger(length)) return { error: 'invalid_payload' }
    if (length > MAX_BODY_BYTES) return { error: 'payload_too_large' }
  }
  if (!request.body) return { error: 'invalid_payload' }

  const reader = request.body.getReader()
  const chunks = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > MAX_BODY_BYTES) {
        try { await reader.cancel() } catch { /* best effort */ }
        return { error: 'payload_too_large' }
      }
      chunks.push(value)
    }
    const bytes = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
      bytes.set(chunk, offset)
      offset += chunk.byteLength
    }
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return { payload: JSON.parse(text) }
  } catch {
    return { error: 'invalid_payload' }
  }
}

async function importHmacKey(secret) {
  if (typeof secret !== 'string') return null
  const bytes = new TextEncoder().encode(secret)
  if (bytes.byteLength < MIN_SECRET_BYTES) return null
  return crypto.subtle.importKey('raw', bytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
}

async function hmacIndex(key, purpose, noticeVersion, month, installationId) {
  const message = noticeVersion === '2026-08-telemetry-v2'
    ? `${purpose}:${month}:${installationId}`
    : `${purpose}:${noticeVersion}:${month}:${installationId}`
  const encoded = new TextEncoder().encode(message)
  const signature = await crypto.subtle.sign('HMAC', key, encoded)
  return [...new Uint8Array(signature)].slice(0, 12).map((value) => value.toString(16).padStart(2, '0')).join('')
}

function eventMonth(timestampMs) {
  return new Date(timestampMs).toISOString().slice(0, 7)
}

function analyticsPoint(event, installationIndex, timestampMs) {
  const values = PROPERTY_ORDER.map((key) => String(event.properties[key] || ''))
  return {
    blobs: [
      event.event_id, event.event_name, event.app_version, event.privacy_notice_version,
      event.platform, event.architecture, ...values,
    ],
    doubles: [event.schema_version, event.os_major, timestampMs / 1000],
    indexes: [installationIndex],
  }
}

async function allowRate(limiter, key) {
  if (!limiter || typeof limiter.limit !== 'function') return null
  try {
    const result = await limiter.limit({ key })
    return Boolean(result?.success)
  } catch {
    return null
  }
}

export async function handleTelemetryRequest(request, env) {
  const url = new URL(request.url)
  if (url.pathname !== '/v1/events' || request.method !== 'POST') return json(404, { error: 'not_found' })
  if (!env.TELEMETRY || !env.INSTALLATION_HMAC_KEY || !env.INGEST_GLOBAL_RATE_LIMITER || !env.INGEST_INSTALLATION_RATE_LIMITER) {
    return json(503, { error: 'collector_unavailable' })
  }

  const globalAllowed = await allowRate(env.INGEST_GLOBAL_RATE_LIMITER, 'v1-events')
  if (globalAllowed === null) return json(503, { error: 'collector_unavailable' })
  if (!globalAllowed) return json(429, { error: 'rate_limited' }, { 'retry-after': '60' })

  if (!validContentType(request.headers.get('content-type'))) return json(415, { error: 'unsupported_media_type' })
  const contentEncoding = String(request.headers.get('content-encoding') || 'identity').trim().toLowerCase()
  if (contentEncoding !== 'identity') return json(415, { error: 'unsupported_media_type' })

  const decoded = await readBoundedJson(request)
  if (decoded.error === 'payload_too_large') return json(413, { error: 'payload_too_large' })
  if (decoded.error) return json(400, { error: 'invalid_payload' })

  const payload = decoded.payload
  const nowMs = Date.now()
  if (
    !hasExactKeys(payload, BATCH_FIELDS)
    || payload.schema_version !== SCHEMA_VERSION
    || !ACCEPTED_PRIVACY_NOTICE_VERSIONS.has(payload.privacy_notice_version)
    || !validUuid(payload.installation_id)
    || !Array.isArray(payload.events)
    || !payload.events.length
    || payload.events.length > MAX_EVENTS_PER_REQUEST
    || !payload.events.every((event) => validEvent(event, nowMs, payload.privacy_notice_version))
  ) return json(400, { error: 'invalid_payload' })

  let hmacKey
  try {
    hmacKey = await importHmacKey(env.INSTALLATION_HMAC_KEY)
  } catch {
    hmacKey = null
  }
  if (!hmacKey) return json(503, { error: 'collector_unavailable' })

  const currentMonth = eventMonth(nowMs)
  let rateKey
  try {
    rateKey = await hmacIndex(
      hmacKey,
      'rate',
      payload.privacy_notice_version,
      currentMonth,
      payload.installation_id,
    )
  } catch {
    return json(503, { error: 'collector_unavailable' })
  }
  const installationAllowed = await allowRate(env.INGEST_INSTALLATION_RATE_LIMITER, rateKey)
  if (installationAllowed === null) return json(503, { error: 'collector_unavailable' })
  if (!installationAllowed) return json(429, { error: 'rate_limited' }, { 'retry-after': '60' })

  const indexes = new Map()
  try {
    for (const event of payload.events) {
      const timestampMs = parsedOccurredAt(event.occurred_at, nowMs)
      const month = eventMonth(timestampMs)
      if (!indexes.has(month)) {
        const digest = await hmacIndex(
          hmacKey,
          'analytics',
          payload.privacy_notice_version,
          month,
          payload.installation_id,
        )
        indexes.set(month, `${month}:${digest}`)
      }
      env.TELEMETRY.writeDataPoint(analyticsPoint(event, indexes.get(month), timestampMs))
    }
  } catch {
    return json(503, { error: 'collector_unavailable' })
  }
  return json(202, { accepted: payload.events.length })
}

export default { fetch: handleTelemetryRequest }
