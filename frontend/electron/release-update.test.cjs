const test = require('node:test')
const assert = require('node:assert/strict')

const {
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
