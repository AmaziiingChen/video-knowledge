import assert from 'node:assert/strict'
import test from 'node:test'

import { handleReleaseManifestRequest } from './worker.js'

const LATEST_RELEASE_PAGE = 'https://github.com/AmaziiingChen/video-knowledge/releases/latest'
const RELEASE_PAGE = 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.1'

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

test('uses the platform fetch when Workers passes an environment object', async () => {
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
    {},
    async () => latestReleaseResponse(),
  )

  assert.equal(response.status, 200)
  assert.equal((await response.json()).latest_version, '0.1.1')
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
