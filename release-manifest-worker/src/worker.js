const MANIFEST_PATH = '/v1/manifest.json'
const GITHUB_LATEST_RELEASE_URL = 'https://github.com/AmaziiingChen/video-knowledge/releases/latest'
const GITHUB_RELEASE_PREFIX = 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/'

function json(status, value, cacheControl = 'no-store', headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'cache-control': cacheControl,
      'content-type': 'application/json; charset=utf-8',
      'x-content-type-options': 'nosniff',
      ...headers,
    },
  })
}

function unavailable() {
  return json(503, { error: 'release_unavailable' })
}

function releaseVersion(tagName) {
  const match = /^v(\d+(?:\.\d+){1,3})$/.exec(String(tagName || '').trim())
  return match ? match[1] : ''
}

function isOfficialReleasePage(value, tagName) {
  try {
    const url = new URL(String(value || ''))
    return url.href === GITHUB_RELEASE_PREFIX + tagName
  } catch {
    return false
  }
}

export async function handleReleaseManifestRequest(request, envOrFetcher, injectedFetcher = fetch) {
  const fetcher = typeof envOrFetcher === 'function' ? envOrFetcher : injectedFetcher
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.pathname !== MANIFEST_PATH || url.search || url.hash) {
    return json(404, { error: 'not_found' })
  }

  let upstream
  try {
    upstream = await fetcher(GITHUB_LATEST_RELEASE_URL, { redirect: 'manual' })
  } catch {
    return unavailable()
  }
  if (upstream.status !== 302) {
    return unavailable()
  }
  const releasePage = upstream.headers.get('location') || ''
  const tagName = releasePage.startsWith(GITHUB_RELEASE_PREFIX)
    ? releasePage.slice(GITHUB_RELEASE_PREFIX.length)
    : ''
  const latestVersion = releaseVersion(tagName)
  if (!latestVersion || !isOfficialReleasePage(releasePage, tagName)) return unavailable()
  return json(200, {
    latest_version: latestVersion,
    download_page_url: releasePage,
    release_notes: '',
  }, 'public, max-age=300, stale-while-revalidate=60')
}

export default { fetch: handleReleaseManifestRequest }
