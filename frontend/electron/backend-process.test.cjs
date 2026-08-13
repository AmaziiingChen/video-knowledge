const test = require('node:test')
const assert = require('node:assert/strict')

const {
  backendSpawnOptions,
  clearBackendLease,
  readBackendLease,
  terminateBackendProcess,
  terminateLeasedBackend,
  writeBackendLease,
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

test('only terminates a stale backend when it is both leased and recognizably ours', () => {
  const files = new Map()
  const fileSystem = {
    mkdirSync: () => {},
    writeFileSync: (file, content) => files.set(file, content),
    readFileSync: (file) => {
      if (!files.has(file)) {
        const error = new Error('missing')
        error.code = 'ENOENT'
        throw error
      }
      return files.get(file)
    },
    unlinkSync: (file) => {
      if (!files.delete(file)) {
        const error = new Error('missing')
        error.code = 'ENOENT'
        throw error
      }
    },
  }
  const calls = []
  assert.equal(writeBackendLease('/runtime', { pid: 4321 }, { fileSystem }), true)
  assert.deepEqual(readBackendLease('/runtime', { fileSystem }), { pid: 4321 })
  assert.equal(terminateLeasedBackend('/runtime', {
    fileSystem,
    isExpectedBackendProcess: (pid) => pid === 4321,
    kill: (...args) => calls.push(args),
  }), true)
  assert.deepEqual(calls, [[-4321, 'SIGTERM']])
  assert.equal(readBackendLease('/runtime', { fileSystem }), null)

  writeBackendLease('/runtime', { pid: 9876 }, { fileSystem })
  assert.equal(terminateLeasedBackend('/runtime', {
    fileSystem,
    isExpectedBackendProcess: () => false,
  }), false)
  assert.equal(clearBackendLease('/runtime', null, { fileSystem }), true)
})
