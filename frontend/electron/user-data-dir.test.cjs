const test = require('node:test')
const assert = require('node:assert/strict')

const { applyUserDataDirectoryOverride } = require('./user-data-dir.cjs')

test('keeps the normal Electron user-data path when no override is configured', () => {
  const calls = []
  assert.equal(applyUserDataDirectoryOverride({ setPath: (...args) => calls.push(args) }, ''), '')
  assert.deepEqual(calls, [])
})

test('uses an explicit absolute directory for isolated release validation', () => {
  const calls = []
  const resolved = applyUserDataDirectoryOverride(
    { setPath: (...args) => calls.push(args) },
    '/private/tmp/knowledgehub-release-profile',
  )
  assert.equal(resolved, '/private/tmp/knowledgehub-release-profile')
  assert.deepEqual(calls, [['userData', '/private/tmp/knowledgehub-release-profile']])
})

test('rejects a relative override instead of silently using an ambiguous profile', () => {
  assert.throws(
    () => applyUserDataDirectoryOverride({ setPath() {} }, 'release-profile'),
    /绝对路径/,
  )
})
