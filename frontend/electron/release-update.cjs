const RELEASE_MANIFEST_URL = 'https://knowledgehub-release-manifest.knowledgehub4chen.workers.dev/v1/manifest.json'
const RELEASE_PAGE_PREFIX = 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v'

function versionKey(value) {
  const match = String(value || '').trim().match(/^v?(\d+(?:\.\d+){0,3})$/)
  return match ? match[1].split('.').map((part) => Number(part)) : null
}

function isNewerVersion(latest, current) {
  const latestKey = versionKey(latest)
  const currentKey = versionKey(current)
  if (!latestKey || !currentKey) return false
  const size = Math.max(latestKey.length, currentKey.length)
  for (let index = 0; index < size; index += 1) {
    const difference = (latestKey[index] || 0) - (currentKey[index] || 0)
    if (difference) return difference > 0
  }
  return false
}

function isOfficialReleasePage(value, latestVersion) {
  try {
    const parsed = new URL(String(value || '').trim())
    return parsed.protocol === 'https:'
      && parsed.hostname === 'github.com'
      && parsed.port === ''
      && parsed.username === ''
      && parsed.password === ''
      && parsed.search === ''
      && parsed.hash === ''
      && parsed.href === `${RELEASE_PAGE_PREFIX}${latestVersion}`
  } catch {
    return false
  }
}

function updateStatus(payload, currentVersion) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { state: 'invalid', current_version: currentVersion }
  }
  const latestVersion = String(payload.latest_version || '').trim()
  const downloadPageUrl = String(payload.download_page_url || '').trim()
  if (!versionKey(currentVersion) || !versionKey(latestVersion) || !isOfficialReleasePage(downloadPageUrl, latestVersion)) {
    return { state: 'invalid', current_version: currentVersion }
  }
  const available = isNewerVersion(latestVersion, currentVersion)
  return {
    state: available ? 'available' : 'up_to_date',
    current_version: currentVersion,
    latest_version: latestVersion,
    download_page_url: available ? downloadPageUrl : '',
    release_notes: String(payload.release_notes || '').slice(0, 500),
  }
}

async function checkDesktopReleaseUpdate({ fetcher, currentVersion, timeoutMs = 6000 }) {
  if (typeof fetcher !== 'function') return { state: 'unavailable', current_version: currentVersion }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetcher(RELEASE_MANIFEST_URL, {
      method: 'GET',
      redirect: 'error',
      signal: controller.signal,
    })
    if (!response?.ok) return { state: 'unavailable', current_version: currentVersion }
    return updateStatus(await response.json(), currentVersion)
  } catch {
    return { state: 'unavailable', current_version: currentVersion }
  } finally {
    clearTimeout(timer)
  }
}

module.exports = {
  RELEASE_MANIFEST_URL,
  checkDesktopReleaseUpdate,
  isOfficialReleasePage,
  updateStatus,
}
