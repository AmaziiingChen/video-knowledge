export const LOCAL_API_ORIGIN = 'http://127.0.0.1:8000'
const configuredApiBase = typeof import.meta.env === 'object'
  ? String(import.meta.env.VITE_API_BASE || '').trim()
  : ''

export const API_BASE = (configuredApiBase || `${LOCAL_API_ORIGIN}/api`).replace(/\/+$/, '')
const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete'])

let accessTokenPromise = null

export function apiUrl(path = '') {
  const suffix = String(path || '').trim()
  if (!suffix) return API_BASE
  return `${API_BASE}/${suffix.replace(/^\/+/, '')}`
}

function isLocalApiUrl(value) {
  try {
    const url = new URL(String(value || ''), window.location.href)
    return url.origin === LOCAL_API_ORIGIN && url.pathname.startsWith('/api/')
  } catch {
    return false
  }
}

function shouldUseSourceApiProxy() {
  if (!window.location || window.knowledgeHubDesktop?.backendAccessToken) return false
  return ['http://127.0.0.1:5173', 'http://localhost:5173'].includes(window.location.origin)
}

export function localApiRequestUrl(value) {
  if (!isLocalApiUrl(value) || !shouldUseSourceApiProxy()) return value
  const url = new URL(String(value), window.location.href)
  return `${url.pathname}${url.search}${url.hash}`
}

async function desktopAccessToken() {
  if (!window.knowledgeHubDesktop?.backendAccessToken) return ''
  if (!accessTokenPromise) {
    accessTokenPromise = window.knowledgeHubDesktop.backendAccessToken().catch(() => '')
  }
  return accessTokenPromise
}

export async function localApiAuthHeaders(headers = {}) {
  const token = await desktopAccessToken()
  return token ? { ...headers, 'X-KnowledgeHub-Token': token } : headers
}

export function installLocalApiAuth(axios) {
  axios.interceptors.request.use(async (config) => {
    if (isLocalApiUrl(config.url)) config.url = localApiRequestUrl(config.url)
    const method = String(config.method || 'get').toLowerCase()
    if (!MUTATING_METHODS.has(method) || !isLocalApiUrl(config.url)) return config
    const token = await desktopAccessToken()
    if (token) {
      config.headers = config.headers || {}
      if (typeof config.headers.set === 'function') config.headers.set('X-KnowledgeHub-Token', token)
      else config.headers['X-KnowledgeHub-Token'] = token
    }
    return config
  })
}
