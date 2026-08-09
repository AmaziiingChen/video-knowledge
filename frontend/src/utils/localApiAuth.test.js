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
  const { API_BASE, apiUrl, localApiRequestUrl } = await import('./localApiAuth.js')
  assert.equal(API_BASE, 'http://127.0.0.1:8000/api')
  assert.equal(apiUrl('/tasks'), 'http://127.0.0.1:8000/api/tasks')
  assert.equal(apiUrl(), API_BASE)
  assert.equal(localApiRequestUrl('http://127.0.0.1:8000/api/tasks?limit=1'), '/api/tasks?limit=1')
})

test('desktop and non-local requests keep their original destination', async () => {
  installWindow('knowledgehub://app', true)
  const { localApiRequestUrl } = await import('./localApiAuth.js')
  assert.equal(localApiRequestUrl('http://127.0.0.1:8000/api/tasks'), 'http://127.0.0.1:8000/api/tasks')
  assert.equal(localApiRequestUrl('https://example.com/api/tasks'), 'https://example.com/api/tasks')
})

test('axios attaches the desktop capability to local reads as well as writes', async () => {
  installWindow('knowledgehub://app', true)
  const { installLocalApiAuth } = await import('./localApiAuth.js')
  let requestInterceptor = null
  installLocalApiAuth({
    interceptors: {
      request: {
        use(handler) { requestInterceptor = handler },
      },
    },
  })

  const readRequest = await requestInterceptor({
    method: 'get',
    url: 'http://127.0.0.1:8000/api/content',
    headers: {},
  })
  assert.equal(readRequest.headers['X-KnowledgeHub-Token'], 'desktop-token')
})
