const test = require('node:test')
const assert = require('node:assert/strict')

const { clipboardText, createClipboardRelay } = require('./clipboard-relay.cjs')

test('primes the current clipboard and relays only a later native change', async () => {
  let current = 'https://b23.tv/already-there'
  let tick = null
  const sent = []
  const relay = createClipboardRelay({
    readText: () => current,
    sendText: async (text) => sent.push(text),
    setIntervalFn: (callback) => { tick = callback; return { unref: () => {} } },
    clearIntervalFn: () => {},
  })

  assert.equal(relay.start(), true)
  await tick()
  assert.deepEqual(sent, [])

  current = '2.33 复制打开抖音 https://v.douyin.com/TezMfui44Lo/'
  await tick()
  assert.deepEqual(sent, [current])
})

test('retries a changed clipboard value after a local relay failure', async () => {
  let current = ''
  let attempts = 0
  const relay = createClipboardRelay({
    readText: () => current,
    sendText: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('backend restarting')
    },
    setIntervalFn: () => ({ unref: () => {} }),
    clearIntervalFn: () => {},
  })
  relay.start()
  current = 'https://b23.tv/DcyQ6Ci'

  assert.equal(await relay.scanOnce(), false)
  assert.equal(await relay.scanOnce(), true)
  assert.equal(attempts, 2)
})

test('rejects blank and unexpectedly large native clipboard payloads', () => {
  assert.equal(clipboardText('  '), '')
  assert.equal(clipboardText('x'.repeat(11), 10), '')
  assert.equal(clipboardText(' https://b23.tv/example '), 'https://b23.tv/example')
})
