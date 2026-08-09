const test = require('node:test')
const assert = require('node:assert/strict')

const { isProtectedBackendRequest, shouldInjectBackendToken, withBackendToken } = require('./backend-request-auth.cjs')

test('only the main renderer may receive the backend token for protected loopback API media', () => {
  assert.equal(isProtectedBackendRequest('http://127.0.0.1:8000/api/media?path=clip.mp4'), true)
  assert.equal(isProtectedBackendRequest('http://localhost:8000/api/media'), false)
  assert.equal(isProtectedBackendRequest('https://example.invalid/api/media'), false)
  assert.equal(shouldInjectBackendToken({ webContentsId: 42, url: 'http://127.0.0.1:8000/api/media?path=clip.mp4' }, 42), true)
  assert.equal(shouldInjectBackendToken({ webContentsId: 43, url: 'http://127.0.0.1:8000/api/media?path=clip.mp4' }, 42), false)
})

test('injection preserves browser media headers and never uses a URL token', () => {
  assert.deepEqual(withBackendToken({ Range: 'bytes=0-' }, 'desktop-token'), {
    Range: 'bytes=0-',
    'X-KnowledgeHub-Token': 'desktop-token',
  })
})
