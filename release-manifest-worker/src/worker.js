const MANIFEST_PATH = '/v1/manifest.json'
const GITHUB_LATEST_RELEASE_URL = 'https://github.com/AmaziiingChen/video-knowledge/releases/latest'
const GITHUB_LATEST_RELEASE_API_URL = 'https://api.github.com/repos/AmaziiingChen/video-knowledge/releases/latest'
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

function unavailable(stage, status = 0) {
  const headers = { 'x-release-manifest-stage': stage }
  if (status) headers['x-release-manifest-upstream-status'] = String(status)
  return json(503, { error: 'release_unavailable' }, 'no-store', headers)
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

function manifestResponse(tagName, releasePage, releaseNotes = '') {
  const latestVersion = releaseVersion(tagName)
  if (!latestVersion || !isOfficialReleasePage(releasePage, tagName)) return null
  return json(200, {
    latest_version: latestVersion,
    download_page_url: releasePage,
    release_notes: String(releaseNotes || '').slice(0, 500),
  }, 'public, max-age=300, stale-while-revalidate=60')
}

async function fetchLatestReleasePage(fetcher) {
  try {
    const upstream = await fetcher(GITHUB_LATEST_RELEASE_URL, { redirect: 'manual' })
    if (upstream.status === 302) {
      const releasePage = upstream.headers.get('location') || ''
      const tagName = releasePage.startsWith(GITHUB_RELEASE_PREFIX)
        ? releasePage.slice(GITHUB_RELEASE_PREFIX.length)
        : ''
      const manifest = manifestResponse(tagName, releasePage)
      if (manifest) return manifest
    }
  } catch {
    // Fall through to GitHub's stable JSON API. Some edge routes do not
    // preserve the public redirect used above.
  }

  let apiResponse
  try {
    apiResponse = await fetcher(GITHUB_LATEST_RELEASE_API_URL, {
      headers: {
        accept: 'application/vnd.github+json',
        'user-agent': 'KnowledgeHub-release-manifest',
      },
    })
  } catch {
    return unavailable('upstream_fetch')
  }
  if (!apiResponse.ok) return unavailable('upstream_response', apiResponse.status)

  let release
  try {
    release = await apiResponse.json()
  } catch {
    return unavailable('upstream_payload')
  }
  if (!release || typeof release !== 'object' || Array.isArray(release)) {
    return unavailable('upstream_payload')
  }
  const manifest = manifestResponse(release.tag_name, release.html_url, release.body)
  return manifest || unavailable('release_validation')
}

export async function handleReleaseManifestRequest(request, envOrFetcher, injectedFetcher = fetch) {
  const fetcher = typeof envOrFetcher === 'function' ? envOrFetcher : injectedFetcher
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.pathname !== MANIFEST_PATH || url.search || url.hash) {
    return json(404, { error: 'not_found' })
  }

  return fetchLatestReleasePage(fetcher)
}

export default { fetch: handleReleaseManifestRequest }
