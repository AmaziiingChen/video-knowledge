import assert from 'node:assert/strict'
import test from 'node:test'

import { useWechatDraftController } from './useWechatDraftController.js'

function makeTimers() {
  let nextId = 0
  const active = new Set()
  return {
    active,
    setTimeout() {
      const id = ++nextId
      active.add(id)
      return id
    },
    clearTimeout(id) {
      active.delete(id)
    },
  }
}

function silentNotifications() {
  return { error() {}, info() {}, success() {} }
}

test('loads draft defaults in order and releases its background task poll', async () => {
  const requests = []
  const timers = makeTimers()
  const request = {
    async get(url) {
      requests.push(url)
      if (url.endsWith('/ip-preflight')) return { data: { status: 'verified', can_submit: true } }
      if (url.endsWith('/draft-task')) {
        return { data: { task_id: 'task-1', status: 'running', progress: 20 } }
      }
      return {
        data: {
          title: '每周报告',
          digest: '摘要',
          preview_html: '<p>预览</p>',
          cover_url: '/cover.png',
        },
      }
    },
  }
  const controller = useWechatDraftController({
    apiBase: 'http://local.test/wechat-publishing',
    ensurePublishingConfigured: async () => true,
    request,
    notify: silentNotifications(),
    timers,
  })

  await controller.openWechatDraftDialog({ id: 'report-1', title: '回退标题' })

  assert.equal(controller.wechatDraftDialogVisible.value, true)
  assert.equal(controller.wechatDraftTitle.value, '每周报告')
  assert.equal(controller.wechatDraftIpPreflight.value.can_submit, true)
  assert.equal(controller.wechatDraftTask.value.task_id, 'task-1')
  assert.deepEqual(requests, [
    'http://local.test/wechat-publishing/reports/report-1',
    'http://local.test/wechat-publishing/ip-preflight',
    'http://local.test/wechat-publishing/reports/report-1/draft-task',
  ])
  assert.equal(timers.active.size, 1)

  controller.disposeWechatDraftController()
  assert.equal(timers.active.size, 0)
})

test('does not open or request report data before publishing is configured', async () => {
  let requests = 0
  const controller = useWechatDraftController({
    ensurePublishingConfigured: async () => false,
    request: { get: async () => { requests += 1 } },
    notify: silentNotifications(),
  })

  await controller.openWechatDraftDialog({ id: 'report-1' })

  assert.equal(controller.wechatDraftDialogVisible.value, false)
  assert.equal(requests, 0)
})
