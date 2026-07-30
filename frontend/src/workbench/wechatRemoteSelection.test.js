import assert from 'node:assert/strict'
import test from 'node:test'

import {
  WECHAT_REMOTE_SELECTION_PREFIX,
  parseWechatRemoteSelectionMessage,
  wechatRemoteSelectionBridgeScript,
} from './wechatRemoteSelection.js'

test('reads a bounded selected quote and its guest-page coordinates', () => {
  assert.deepEqual(parseWechatRemoteSelectionMessage(`${WECHAT_REMOTE_SELECTION_PREFIX}${JSON.stringify({
    kind: 'selection',
    text: '  公众号文章的选中文本  ',
    rect: { left: 8, top: 16, right: 88, bottom: 40 },
  })}`), {
    kind: 'selection',
    text: '公众号文章的选中文本',
    rect: { left: 8, top: 16, right: 88, bottom: 40 },
  })
})

test('rejects malformed guest console messages and keeps explicit clears', () => {
  assert.equal(parseWechatRemoteSelectionMessage('ordinary page console output'), null)
  assert.equal(parseWechatRemoteSelectionMessage(`${WECHAT_REMOTE_SELECTION_PREFIX}{bad json}`), null)
  assert.deepEqual(parseWechatRemoteSelectionMessage(`${WECHAT_REMOTE_SELECTION_PREFIX}{"kind":"clear"}`), { kind: 'clear' })
})

test('samples the guest selection after pointer release, never while it is changing', () => {
  const script = wechatRemoteSelectionBridgeScript()
  assert.match(script, /document\.addEventListener\('pointerup', scheduleSelection, true\)/u)
  assert.doesNotMatch(script, /selectionchange/u)
})
