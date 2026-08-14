const test = require('node:test')
const assert = require('node:assert/strict')

const {
  GITHUB_LATEST_RELEASE_API_URL,
  RELEASE_MANIFEST_URL,
  checkDesktopReleaseUpdate,
  updateStatus,
} = require('./release-update.cjs')

const manifest = {
  latest_version: '0.1.5',
  download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.5',
  release_notes: '修复更新检查。',
}

test('desktop update reader accepts only the exact manifest and release page contract', async () => {
  const calls = []
  const status = await checkDesktopReleaseUpdate({
    currentVersion: '0.1.4',
    fetcher: async (...args) => {
      calls.push(args)
      return { ok: true, json: async () => manifest }
    },
  })

  assert.deepEqual(status, {
    state: 'available',
    current_version: '0.1.4',
    latest_version: '0.1.5',
    download_page_url: manifest.download_page_url,
    release_notes: manifest.release_notes,
  })
  assert.equal(calls[0][0], RELEASE_MANIFEST_URL)
  assert.equal(calls[0][1].redirect, 'error')
})

test('desktop update reader rejects a redirected or malformed release payload and preserves failures as unavailable', async () => {
  assert.deepEqual(updateStatus({
    ...manifest,
    download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/latest',
  }, '0.1.4'), { state: 'invalid', current_version: '0.1.4' })
  assert.deepEqual(await checkDesktopReleaseUpdate({
    currentVersion: '0.1.4',
    fetcher: async () => { throw new Error('proxy unavailable') },
  }), { state: 'unavailable', current_version: '0.1.4' })
})

test('desktop update reader falls back to the official GitHub API when workers.dev is unavailable', async () => {
  const calls = []
  const status = await checkDesktopReleaseUpdate({
    currentVersion: '0.1.7',
    fetcher: async (url, init) => {
      calls.push({ url, init })
      if (url === RELEASE_MANIFEST_URL) throw new Error('workers.dev is unreachable')
      return {
        ok: true,
        json: async () => ({
          tag_name: 'v0.1.8',
          html_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.8',
          body: '修复更新通道。',
        }),
      }
    },
  })

  assert.deepEqual(status, {
    state: 'available',
    current_version: '0.1.7',
    latest_version: '0.1.8',
    download_page_url: 'https://github.com/AmaziiingChen/video-knowledge/releases/tag/v0.1.8',
    release_notes: '修复更新通道。',
  })
  assert.equal(calls[0].url, RELEASE_MANIFEST_URL)
  assert.equal(calls[1].url, GITHUB_LATEST_RELEASE_API_URL)
  assert.deepEqual(calls[1].init.headers, {
    accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28',
  })
})
