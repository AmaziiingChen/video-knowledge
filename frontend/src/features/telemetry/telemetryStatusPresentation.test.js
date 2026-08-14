import assert from 'node:assert/strict'
import test from 'node:test'

import { telemetryStatusPresentation } from './telemetryStatusPresentation.js'

test('presents pending, failed, disabled and synchronized diagnostic states', () => {
  assert.deepEqual(telemetryStatusPresentation({ loaded: true, enabled: true, pendingEvents: 8, uploadResult: 'failed' }), {
    label: '连接失败',
    tone: 'is-invalid',
    description: '本机有 8 条待发送事件。上次连接 Cloudflare 失败，应用会自动重试。',
  })
  assert.equal(telemetryStatusPresentation({ loaded: true }).label, '已关闭')
  assert.equal(telemetryStatusPresentation({ loaded: true, enabled: true }).label, '已同步')
})
