const test = require('node:test')
const assert = require('node:assert/strict')

const {
  backendSpawnOptions,
  terminateBackendProcess,
} = require('./backend-process.cjs')

test('places Unix backend launches in an isolated process group', () => {
  assert.deepEqual(backendSpawnOptions('darwin'), { detached: true })
  assert.deepEqual(backendSpawnOptions('linux'), { detached: true })
  assert.deepEqual(backendSpawnOptions('win32'), { detached: false })
})

test('terminates the full Unix backend process group but not unrelated processes', () => {
  const calls = []
  const stopped = terminateBackendProcess({ pid: 4321 }, {
    platform: 'darwin',
    kill: (...args) => calls.push(args),
  })

  assert.equal(stopped, true)
  assert.deepEqual(calls, [[-4321, 'SIGTERM']])
})

test('uses the direct child process on Windows and tolerates an exited process', () => {
  const calls = []
  assert.equal(terminateBackendProcess({ pid: 98 }, {
    platform: 'win32',
    kill: (...args) => calls.push(args),
  }), true)
  assert.deepEqual(calls, [[98, 'SIGTERM']])
  assert.equal(terminateBackendProcess({ pid: 98 }, {
    kill: () => { const error = new Error('gone'); error.code = 'ESRCH'; throw error },
  }), true)
})
