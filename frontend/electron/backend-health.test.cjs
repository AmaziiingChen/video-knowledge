const test = require('node:test')
const assert = require('node:assert/strict')

const {
  BACKEND_SERVICE_ID,
  isExpectedBackendHealth,
} = require('./backend-health.cjs')

test('desktop accepts only the backend instance it launched', () => {
  const expected = {
    status: 'ok',
    service: BACKEND_SERVICE_ID,
    instance_token: 'launch-token',
  }

  assert.equal(isExpectedBackendHealth(expected, 'launch-token'), true)
  assert.equal(isExpectedBackendHealth(expected, 'another-launch'), false)
  assert.equal(isExpectedBackendHealth({ status: 'ok' }, 'launch-token'), false)
  assert.equal(isExpectedBackendHealth(expected, ''), false)
})
