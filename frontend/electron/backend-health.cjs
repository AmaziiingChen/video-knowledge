const BACKEND_SERVICE_ID = 'knowledgehub-backend'

function isExpectedBackendHealth(payload, instanceToken) {
  return Boolean(
    payload
    && typeof payload === 'object'
    && payload.status === 'ok'
    && payload.service === BACKEND_SERVICE_ID
    && typeof instanceToken === 'string'
    && instanceToken.length > 0
    && payload.instance_token === instanceToken
  )
}

module.exports = {
  BACKEND_SERVICE_ID,
  isExpectedBackendHealth,
}
