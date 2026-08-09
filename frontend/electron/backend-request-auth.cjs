function isProtectedBackendRequest(url) {
  try {
    const target = new URL(String(url || ''))
    return target.protocol === 'http:'
      && target.hostname === '127.0.0.1'
      && target.port === '8000'
      && target.pathname.startsWith('/api/')
  } catch {
    return false
  }
}

function shouldInjectBackendToken(details, mainWebContentsId) {
  return Number.isInteger(mainWebContentsId)
    && details?.webContentsId === mainWebContentsId
    && isProtectedBackendRequest(details?.url)
}

function withBackendToken(headers = {}, token = '') {
  return token ? { ...headers, 'X-KnowledgeHub-Token': token } : { ...headers }
}

module.exports = { isProtectedBackendRequest, shouldInjectBackendToken, withBackendToken }
