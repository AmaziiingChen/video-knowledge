import assert from 'node:assert/strict'
import test from 'node:test'

import {
  REMOTE_READING_PROGRESS_PREFIX,
  parseRemoteReadingProgressMessage,
  remoteReadingProgressBridgeScript,
} from './remoteReadingProgress.js'

test('reads bounded remote preview progress without receiving page text', () => {
  assert.deepEqual(parseRemoteReadingProgressMessage(`${REMOTE_READING_PROGRESS_PREFIX}${JSON.stringify({
    kind: 'progress', progress: 51.6, characterCount: 2345,
  })}`), { progress: 52, characterCount: 2345 })
})

test('rejects unrelated and malformed remote preview messages', () => {
  assert.equal(parseRemoteReadingProgressMessage('ordinary guest console output'), null)
  assert.equal(parseRemoteReadingProgressMessage(`${REMOTE_READING_PROGRESS_PREFIX}{bad json}`), null)
  assert.equal(parseRemoteReadingProgressMessage(`${REMOTE_READING_PROGRESS_PREFIX}{"kind":"progress","progress":101,"characterCount":1}`), null)
})

test('the guest bridge reports only a percentage and character count on scroll', () => {
  const script = remoteReadingProgressBridgeScript(3500)
  assert.match(script, /window\.addEventListener\('scroll', schedule/u)
  assert.match(script, /const characterCount = 3500 \|\|/u)
  assert.match(script, /characterCount/u)
  assert.doesNotMatch(script, /text:\s*document\.body/u)
})
