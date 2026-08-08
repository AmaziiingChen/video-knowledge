import assert from 'node:assert/strict'
import test from 'node:test'

function installWindow(origin, desktop = false) {
  globalThis.window = {
    location: { origin, href: `${origin}/` },
    knowledgeHubDesktop: desktop ? { backendAccessToken: () => Promise.resolve('desktop-token') } : undefined,
  }
}

test('source checkout routes local API requests through its loopback proxy', async () => {
  installWindow('http://127.0.0.1:5173')
  const { localApiRequestUrl } = await import('./localApiAuth.js')
  assert.equal(localApiRequestUrl('http://127.0.0.1:8000/api/tasks?limit=1'), '/api/tasks?limit=1')
})

test('desktop and non-local requests keep their original destination', async () => {
  installWindow('knowledgehub://app', true)
  const { localApiRequestUrl } = await import('./localApiAuth.js')
  assert.equal(localApiRequestUrl('http://127.0.0.1:8000/api/tasks'), 'http://127.0.0.1:8000/api/tasks')
  assert.equal(localApiRequestUrl('https://example.com/api/tasks'), 'https://example.com/api/tasks')
})
