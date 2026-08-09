import assert from 'node:assert/strict'
import test from 'node:test'

import {
  truncateWechatDigest,
  wechatDraftSubmitState,
  wechatDraftTaskStageLabel,
} from './wechatDraftPresentation.js'

test('keeps the existing durable draft task stage wording', () => {
  assert.equal(wechatDraftTaskStageLabel('checking_wechat_ip'), '正在检查公众号 IP 白名单')
  assert.equal(wechatDraftTaskStageLabel('creating_wechat_draft'), '正在创建公众号草稿')
  assert.equal(wechatDraftTaskStageLabel('unknown'), '正在处理中')
})

test('truncates a WeChat digest on a UTF-8 byte boundary', () => {
  assert.equal(truncateWechatDigest('  中文abc  ', 7), '中文a')
  assert.equal(truncateWechatDigest('plain text', 5), 'plain')
})

test('submits only a current, verified and complete draft form', () => {
  const ready = wechatDraftSubmitState({
    ipPreflight: { can_submit: true },
    title: '周报',
    coverUrl: '/cover.png',
  })
  assert.deepEqual(ready, {
    alreadyCreated: false,
    disabled: false,
    label: '存入草稿箱',
    taskRunning: false,
  })

  const stalePublication = wechatDraftSubmitState({
    ipPreflight: { can_submit: true },
    title: '周报',
    coverUrl: '/cover.png',
    latestPublication: { status: 'draft_created', is_current_source: false },
  })
  assert.equal(stalePublication.disabled, false)

  const currentPublication = wechatDraftSubmitState({
    ipPreflight: { can_submit: true },
    title: '周报',
    coverUrl: '/cover.png',
    latestPublication: { status: 'draft_created', is_current_source: true },
  })
  assert.equal(currentPublication.disabled, true)
  assert.equal(currentPublication.label, '草稿已创建')
})
