const SCHEMA_VERSION = 1
const PRIVACY_NOTICE_VERSION = '2026-08-telemetry-v1'
const MAX_EVENTS_PER_REQUEST = 100
const MAX_BODY_BYTES = 256 * 1024

const EVENT_FIELDS = {
  app_started: [], workspace_opened: ['view'], import_started: ['input_kind'], import_completed: ['result'],
  task_enqueued: ['processing_mode'], pipeline_stage_completed: ['stage'], pipeline_stage_failed: ['stage'],
  task_finished: ['result', 'stage'], task_control_used: ['action'], paddle_ocr_completed: ['result'],
  obsidian_sync_completed: ['result'], search_completed: ['result_count_bucket'],
  clipboard_listener_changed: ['state'], update_check_completed: ['result'],
  telemetry_consent_changed: ['state'], update_download_page_opened: [],
  media_download_completed: ['result', 'duration_bucket'], asr_completed: ['backend', 'result', 'duration_bucket'],
  ai_summary_completed: ['result', 'duration_bucket'], export_completed: ['export_kind', 'result'],
}

const ENUM_VALUES = {
  action: new Set(['retry', 'pause', 'resume', 'cancel']),
  backend: new Set(['faster_whisper', 'mlx', 'other']),
  duration_bucket: new Set(['0_1m', '1_10m', '10_60m', '60m_plus', 'other']),
  export_kind: new Set(['markdown', 'other']), input_kind: new Set(['link', 'other']),
  processing_mode: new Set(['full', 'transcript', 'other']),
  result: new Set(['accepted', 'available', 'conflict', 'disabled', 'empty', 'failed', 'succeeded', 'unavailable', 'up_to_date', 'other']),
  result_count_bucket: new Set(['0', '1_5', '6_20', '21_100', '101_plus', 'other']),
  stage: new Set(['analyze', 'asr', 'download', 'executor', 'export', 'ocr', 'prepare', 'queued', 'summary', 'transcribe', 'unknown', 'other']),
  state: new Set(['enabled', 'disabled', 'other']),
  view: new Set(['campus', 'creator', 'knowledge', 'library', 'prompts', 'reports', 'rss', 'wechat', 'other']),
}

function json(status, value) {
  return new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } })
}

function validUuid(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
}

function validEvent(event) {
  if (!event || typeof event !== 'object' || !validUuid(event.event_id)) return false
  if (!(event.event_name in EVENT_FIELDS) || typeof event.occurred_at !== 'string' || Number.isNaN(Date.parse(event.occurred_at))) return false
  if (typeof event.app_version !== 'string' || !/^[0-9A-Za-z._-]{1,40}$/.test(event.app_version)) return false
  if (event.platform !== 'darwin' && event.platform !== 'macos') return false
  if (!['arm64', 'x64', 'other'].includes(event.architecture) || !Number.isInteger(event.os_major) || event.os_major < 10 || event.os_major > 99) return false
  if (typeof event.properties !== 'object' || event.properties === null || Array.isArray(event.properties)) return false
  const allowed = EVENT_FIELDS[event.event_name]
  const keys = Object.keys(event.properties)
  if (keys.length !== allowed.length || keys.some((key) => !allowed.includes(key))) return false
  return keys.every((key) => ENUM_VALUES[key].has(event.properties[key]))
}

async function monthlyInstallationIndex(installationId, secret) {
  const period = new Date().toISOString().slice(0, 7)
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${period}:${installationId}`))
  return `${period}:${[...new Uint8Array(signature)].slice(0, 12).map((value) => value.toString(16).padStart(2, '0')).join('')}`
}

export async function handleTelemetryRequest(request, env) {
  const url = new URL(request.url)
  if (url.pathname !== '/v1/events' || request.method !== 'POST') return json(404, { error: 'not_found' })
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) return json(415, { error: 'unsupported_media_type' })
  const length = Number(request.headers.get('content-length') || 0)
  if (length > MAX_BODY_BYTES) return json(413, { error: 'payload_too_large' })

  let payload
  try {
    const body = await request.text()
    if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) return json(413, { error: 'payload_too_large' })
    payload = JSON.parse(body)
  } catch {
    return json(400, { error: 'invalid_payload' })
  }
  if (
    !payload || payload.schema_version !== SCHEMA_VERSION || payload.privacy_notice_version !== PRIVACY_NOTICE_VERSION
    || !validUuid(payload.installation_id) || !Array.isArray(payload.events)
    || !payload.events.length || payload.events.length > MAX_EVENTS_PER_REQUEST || !payload.events.every(validEvent)
  ) return json(400, { error: 'invalid_payload' })
  if (!env.TELEMETRY || !env.INSTALLATION_HMAC_KEY) return json(503, { error: 'collector_unavailable' })

  const index = await monthlyInstallationIndex(payload.installation_id, env.INSTALLATION_HMAC_KEY)
  for (const event of payload.events) {
    env.TELEMETRY.writeDataPoint({
      blobs: [event.event_id, event.event_name, event.app_version, event.platform, String(event.architecture || 'other'), JSON.stringify(event.properties)],
      doubles: [Number(event.schema_version || SCHEMA_VERSION), Number(event.os_major || 0)],
      indexes: [index],
    })
  }
  return json(202, { accepted: payload.events.length })
}

export default { fetch: handleTelemetryRequest }
