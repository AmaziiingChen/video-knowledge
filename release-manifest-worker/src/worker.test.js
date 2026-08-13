import assert from 'node:assert/strict'
import test from 'node:test'

import { handleReleaseManifestRequest } from './worker.js'

const RELEASE = {
  tag_name: 'v0.1.1',
  html_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.1',
  body: '修复稳定性问题',
  draft: false,
  prerelease: false,
}

function githubResponse(value = RELEASE, headers = { 'content-type': 'application/json; charset=utf-8' }) {
  return new Response(JSON.stringify(value), { status: 200, headers })
}

test('serves only the public manifest path and uses the fixed GitHub release API', async () => {
  const calls = []
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
    async (url, init) => {
      calls.push({ url, init })
      return githubResponse()
    },
  )

  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), {
    latest_version: '0.1.1',
    download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.1',
    release_notes: '修复稳定性问题',
  })
  assert.deepEqual(calls, [{
    url: 'https://api.github.com/repos/AmaziiingChen/video-knowledge/releases/latest',
    init: {
      headers: { accept: 'application/vnd.github+json' },
      redirect: 'error',
      cf: { cacheEverything: true, cacheTtl: 300 },
    },
  }])
  assert.equal(response.headers.get('cache-control'), 'public, max-age=300, stale-while-revalidate=60')
})

test('rejects other routes without fetching GitHub', async () => {
  const response = await handleReleaseManifestRequest(
    new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json?preview=1'),
    async () => { throw new Error('must not fetch') },
  )
  assert.equal(response.status, 404)
  assert.deepEqual(await response.json(), { error: 'not_found' })
})

test('fails closed for draft, prerelease, malformed or redirected release pages', async () => {
  for (const release of [
    { ...RELEASE, draft: true },
    { ...RELEASE, prerelease: true },
    { ...RELEASE, tag_name: 'latest' },
    { ...RELEASE, html_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/latest' },
  ]) {
    const response = await handleReleaseManifestRequest(
      new Request('https://knowledgehub-release-manifest.example.workers.dev/v1/manifest.json'),
      async () => githubResponse(release),
    )
    assert.equal(response.status, 503)
    assert.deepEqual(await response.json(), { error: 'release_unavailable' })
  }
})

test('fails closed for upstream errors, non-JSON and oversized bodies', async () => {
  const cases = [
    async () => new Response('upstream', { status: 500, headers: { 'content-type': 'text/plain' } }),
    async () => new Response('not json', { status: 200, headers: { 'content-type': 'text/plain' } }),
    async () => new Response(JSON.stringify(RELEASE), {
      status: 200,
      headers: { 'content-type': 'application/json', 'content-length': String(64 * 1024 + 1) },
    }),
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
