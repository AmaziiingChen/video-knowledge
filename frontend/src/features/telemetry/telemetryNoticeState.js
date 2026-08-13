export const DEFAULT_ON_TELEMETRY_NOTICE_VERSION = '2026-08-telemetry-v3'
export const LEGACY_OPT_OUT_NOTICE_VERSION = '2026-08-telemetry-v2'

export function shouldShowTelemetryNotice(status, seenVersion = '') {
  const version = String(status?.privacy_notice_version || '')
  return Boolean(
    version === DEFAULT_ON_TELEMETRY_NOTICE_VERSION
    && status?.enabled === true
    && status?.notice_required === true
    && seenVersion !== version
  )
}

export function shouldMigrateLegacyTelemetryOptOut(status, seenVersion = '') {
  return Boolean(
    String(status?.privacy_notice_version || '') === DEFAULT_ON_TELEMETRY_NOTICE_VERSION
    && status?.enabled === true
    && status?.notice_required === true
    && status?.preference_source === 'default_enabled'
    && seenVersion === LEGACY_OPT_OUT_NOTICE_VERSION
  )
}

export function assertTelemetryEnabledState(status, expectedEnabled) {
  if (status?.enabled !== expectedEnabled) {
    throw new Error(expectedEnabled ? '遥测服务未确认开启' : '遥测服务未确认关闭')
  }
  return status
}
