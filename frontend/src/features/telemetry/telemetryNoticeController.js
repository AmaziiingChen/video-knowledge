import {
  assertTelemetryEnabledState,
  shouldMigrateLegacyTelemetryOptOut,
  shouldShowTelemetryNotice,
} from './telemetryNoticeState.js'

export const TELEMETRY_NOTICE_RETRY_OFFSETS_MS = Object.freeze([
  0,
  2_000,
  6_000,
  15_000,
  30_000,
  45_000,
])

export function createTelemetryNoticeController({
  fetchStatus,
  disableTelemetry,
  readSeenVersion,
  rememberVersion,
  updateNotice,
  retryOffsets = TELEMETRY_NOTICE_RETRY_OFFSETS_MS,
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  now = Date.now,
}) {
  let retryTimer = null
  let startedAt = 0
  let stopped = false

  function scheduleRetry(attemptIndex) {
    if (stopped || attemptIndex >= retryOffsets.length) return
    const dueAt = startedAt + retryOffsets[attemptIndex]
    retryTimer = schedule(() => {
      retryTimer = null
      return load(attemptIndex)
    }, Math.max(0, dueAt - now()))
  }

  async function load(attemptIndex) {
    let status
    try {
      status = await fetchStatus()
    } catch {
      scheduleRetry(attemptIndex + 1)
      return
    }
    if (stopped) return

    const version = String(status?.privacy_notice_version || '')
    const seenVersion = String(readSeenVersion() || '')

    if (shouldMigrateLegacyTelemetryOptOut(status, seenVersion)) {
      try {
        const disabledStatus = await disableTelemetry()
        assertTelemetryEnabledState(disabledStatus, false)
        if (stopped) return
        rememberVersion(version)
        updateNotice({ version, visible: false })
        return
      } catch {
        // Keep the factual disclosure visible when an automatic legacy
        // opt-out migration cannot be confirmed. The user can retry from the
        // notice or Settings without the UI falsely claiming it is disabled.
      }
    }

    if (!stopped) {
      updateNotice({
        version,
        visible: shouldShowTelemetryNotice(status, seenVersion),
      })
    }
  }

  function start() {
    stopped = false
    startedAt = now()
    return load(0)
  }

  function stop() {
    stopped = true
    if (retryTimer !== null) {
      cancelSchedule(retryTimer)
      retryTimer = null
    }
  }

  return { start, stop }
}
