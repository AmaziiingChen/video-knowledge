import assert from 'node:assert/strict'
import test from 'node:test'

import { handleReleaseManifestRequest } from './worker.js'

const LATEST_RELEASE_PAGE = 'https://github.com/AmaziiingChen/video-knowledge/releases/latest'
const RELEASE_PAGE = 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.1'
const LATEST_RELEASE_API = 'https://api.github.com/repos/AmaziiingChen/video-knowledge/releases/latest'

function latestReleaseResponse(location = RELEASE_PAGE) {
  return new Response(null, { status: 302, headers: { location } })
}

test('serves only the public manifest path and uses the fixed GitHub latest-release redirect', async () => {
  const calls = []
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
    async (url, init) => {
      calls.push({ url, init })
      return latestReleaseResponse()
    },
  )

  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), {
    latest_version: '0.1.1',
    download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.1',
    release_notes: '',
  })
  assert.deepEqual(calls, [{
    url: LATEST_RELEASE_PAGE,
    init: { redirect: 'manual' },
  }])
  assert.equal(response.headers.get('cache-control'), 'public, max-age=300, stale-while-revalidate=60')
})

test('uses platform fetch rather than mistaking the Workers runtime context for a fetcher', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return latestReleaseResponse()
  }
  try {
    const response = await handleReleaseManifestRequest(
      new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
      {},
      { waitUntil() {} },
    )

    assert.equal(response.status, 200)
    assert.equal((await response.json()).latest_version, '0.1.1')
    assert.equal(calls.length, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('falls back to GitHub\'s release API when the public redirect is unavailable', async () => {
  const calls = []
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
    async (url, init) => {
      calls.push({ url, init })
      if (url === LATEST_RELEASE_PAGE) return new Response('unavailable', { status: 503 })
      return Response.json({
        tag_name: 'v0.1.7',
        html_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.7',
        body: '修复更新检查。',
      })
    },
  )

  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), {
    latest_version: '0.1.7',
    download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.7',
    release_notes: '修复更新检查。',
  })
  assert.deepEqual(calls, [
    { url: LATEST_RELEASE_PAGE, init: { redirect: 'manual' } },
    {
      url: LATEST_RELEASE_API,
      init: {
        headers: {
          accept: 'application/vnd.github+json',
          'user-agent': 'KnowledgeHub-release-manifest',
        },
      },
    },
  ])
})

test('rejects other routes without fetching GitHub', async () => {
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json?preview=1'),
    async () => { throw new Error('must not fetch') },
  )
  assert.equal(response.status, 404)
  assert.deepEqual(await response.json(), { error: 'not_found' })
})

test('fails closed for malformed or redirected release pages', async () => {
  for (const location of [
    'https://github.com/AmaziiingChen/video-knowledge/releases/latest',
    'https://github.com/AmaziiingChen/video-knowledge/releases/tag/latest',
    'https://example.com/releases/tag/v0.1.1',
  ]) {
    const response = await handleReleaseManifestRequest(
      new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
      async () => latestReleaseResponse(location),
    )
    assert.equal(response.status, 503)
    assert.deepEqual(await response.json(), { error: 'release_unavailable' })
  }
})

test('fails closed for upstream errors and unexpected redirect responses', async () => {
  const cases = [
    async () => new Response('upstream', { status: 500 }),
    async () => new Response(null, { status: 301, headers: { location: RELEASE_PAGE } }),
    async () => new Response(null, { status: 302 }),
    async () => { throw new Error('network unavailable') },
  ]
  for (const fetcher of cases) {
    const response = await handleReleaseManifestRequest(
      new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
      fetcher,
    )
    assert.equal(response.status, 503)
    assert.deepEqual(await response.json(), { error: 'release_unavailable' })
  }
})
