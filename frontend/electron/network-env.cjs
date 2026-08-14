const PROXY_ENVIRONMENT_NAMES = [
  'ALL_PROXY',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'all_proxy',
  'http_proxy',
  'https_proxy',
  'no_proxy',
]

const TELEMETRY_PROXY_ENVIRONMENT_NAME = 'KNOWLEDGEHUB_TELEMETRY_PROXY_URL'

function validatedTelemetryProxyUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  try {
    const parsed = new URL(raw)
    if (
      !['http:', 'https:'].includes(parsed.protocol)
      || parsed.username
      || parsed.password
      || !parsed.hostname
      || !['', '/'].includes(parsed.pathname)
      || parsed.search
      || parsed.hash
    ) return ''
    const port = parsed.port ? Number(parsed.port) : null
    if (port !== null && (!Number.isInteger(port) || port < 1 || port > 65535)) return ''
    return `${parsed.protocol}//${parsed.host}`
  } catch {
    return ''
  }
}

function telemetryProxyFromEnvironment(environment = {}) {
  for (const name of ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy']) {
    const proxyUrl = validatedTelemetryProxyUrl(environment[name])
    if (proxyUrl) return proxyUrl
  }
  return ''
}

function directChildEnvironment(environment = {}) {
  const telemetryProxyUrl = telemetryProxyFromEnvironment(environment)
  const result = { ...environment }
  for (const name of PROXY_ENVIRONMENT_NAMES) delete result[name]
  delete result[TELEMETRY_PROXY_ENVIRONMENT_NAME]
  if (telemetryProxyUrl) result[TELEMETRY_PROXY_ENVIRONMENT_NAME] = telemetryProxyUrl
  return result
}

module.exports = {
  TELEMETRY_PROXY_ENVIRONMENT_NAME,
  directChildEnvironment,
  telemetryProxyFromEnvironment,
  validatedTelemetryProxyUrl,
}
