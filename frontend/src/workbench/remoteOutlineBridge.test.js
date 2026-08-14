import assert from 'node:assert/strict'
import test from 'node:test'

import {
  REMOTE_OUTLINE_PREFIX,
  parseRemoteOutlineMessage,
  remoteOutlineBridgeScript,
} from './remoteOutlineBridge.js'

test('accepts a bounded remote original-page outline', () => {
  assert.deepEqual(parseRemoteOutlineMessage(`${REMOTE_OUTLINE_PREFIX}${JSON.stringify({
    kind: 'outline',
    activeId: 'remote-outline-2',
    entries: [{ id: 'remote-outline-2', text: '第二节', preview: '节的开头。', level: 2 }],
  })}`), {
    kind: 'outline',
    activeId: 'remote-outline-2',
    entries: [{ id: 'remote-outline-2', text: '第二节', preview: '节的开头。', level: 2, order: 0 }],
  })
})

test('rejects malformed remote original-page outline messages', () => {
  assert.equal(parseRemoteOutlineMessage('ordinary guest console output'), null)
  assert.equal(parseRemoteOutlineMessage(`${REMOTE_OUTLINE_PREFIX}{bad json}`), null)
})

test('the guest bridge exposes heading navigation without transmitting the full body', () => {
  const script = remoteOutlineBridgeScript()
  assert.match(script, /__knowledgeHubRemoteOutlineScrollTo/u)
  assert.match(script, /h1, h2, h3, h4/u)
  assert.match(script, /role="heading"/u)
  assert.match(script, /strong, b/u)
  assert.match(script, /MutationObserver/u)
  assert.doesNotMatch(script, /bodyText/u)
})
