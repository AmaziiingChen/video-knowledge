const MANIFEST_PATH = '/v1/manifest.json'
const GITHUB_LATEST_RELEASE_URL = 'https://api.github.com/repos/AmaziiingChen/video-knowledge/releases/latest'
const GITHUB_RELEASE_PREFIX = 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/'
const MAX_GITHUB_RESPONSE_BYTES = 64 * 1024
const MAX_RELEASE_NOTES_CHARS = 500

function json(status, value, cacheControl = 'no-store') {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      'cache-control': cacheControl,
      'content-type': 'application/json; charset=utf-8',
      'x-content-type-options': 'nosniff',
    },
  })
}

function releaseVersion(tagName) {
  const match = /^v(\d+(?:\.\d+){1,3})$/.exec(String(tagName || '').trim())
  return match ? match[1] : ''
}

function isOfficialReleasePage(value, tagName) {
  try {
    const url = new URL(String(value || ''))
    return url.href === `${GITHUB_RELEASE_PREFIX}${tagName}`
  } catch {
    return false
  }
}

function releaseManifest(release) {
  if (!release || typeof release !== 'object' || Array.isArray(release) || release.draft || release.prerelease) return null
  const tagName = String(release.tag_name || '').trim()
  const latestVersion = releaseVersion(tagName)
  if (!latestVersion || !isOfficialReleasePage(release.html_url, tagName)) return null
  return {
    latest_version: latestVersion,
    download_page_url: `${GITHUB_RELEASE_PREFIX}${tagName}`,
    release_notes: String(release.body || '').replaceAll('\u0000', '').slice(0, MAX_RELEASE_NOTES_CHARS),
  }
}

async function readBoundedJson(response) {
  const declaredLength = response.headers.get('content-length')
  if (declaredLength !== null && (!/^\d+$/.test(declaredLength) || Number(declaredLength) > MAX_GITHUB_RESPONSE_BYTES)) return null
  if (!response.body) return null
  const reader = response.body.getReader()
  const chunks = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > MAX_GITHUB_RESPONSE_BYTES) {
        await reader.cancel()
        return null
      }
      chunks.push(value)
    }
    const bytes = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
      bytes.set(chunk, offset)
      offset += chunk.byteLength
    }
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  } catch {
    try { await reader.cancel() } catch { /* best effort */ }
    return null
  }
}

export async function handleReleaseManifestRequest(request, fetcher = fetch) {
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.pathname !== MANIFEST_PATH || url.search || url.hash) {
    return json(404, { error: 'not_found' })
  }

  let upstream
  try {
    upstream = await fetcher(GITHUB_LATEST_RELEASE_URL, {
      headers: { accept: 'application/vnd.github+json' },
      redirect: 'error',
      cf: { cacheEverything: true, cacheTtl: 300 },
    })
  } catch {
    return json(503, { error: 'release_unavailable' })
  }
  if (!upstream.ok || !/^application\/json(?:;|$)/i.test(upstream.headers.get('content-type') || '')) {
    return json(503, { error: 'release_unavailable' })
  }
  const payload = await readBoundedJson(upstream)
  const manifest = releaseManifest(payload)
  if (!manifest) return json(503, { error: 'release_unavailable' })
  return json(200, manifest, 'public, max-age=300, stale-while-revalidate=60')
}

export default { fetch: handleReleaseManifestRequest }
