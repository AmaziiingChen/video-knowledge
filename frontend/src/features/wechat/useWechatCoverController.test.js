import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatCoverController } from './useWechatCoverController.js'

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

test('tracks a queued cover task and releases its poll on disposal', async () => {
  const timers = makeTimers()
  const request = {
    async post(url) {
      assert.equal(url, 'http://local.test/publishing/reports/report-1/cover')
      return { data: { task_id: 'task-1' } }
    },
    async get(url) {
      if (url.includes('/covers')) return { data: { active_cover_id: '', covers: [] } }
      return { data: { status: 'running' } }
    },
  }
  const controller = useWechatCoverController({
    apiBase: 'http://local.test/publishing',
    taskApiBase: 'http://local.test/tasks',
    ensureCoverConfigured: async () => true,
    request,
    notify: silentNotifications(),
    timers,
  })

  await controller.regenerateWechatReportCover({ id: 'report-1', title: '周报' })
  await Promise.resolve()

  assert.deepEqual(controller.wechatCoverGeneratingContentIds.value, ['report-1'])
  assert.equal(timers.active.size, 1)
  controller.disposeWechatCoverController()
  assert.equal(timers.active.size, 0)
})

test('keeps draft cover state aligned when selecting an existing cover', async () => {
  const draftState = {
    contentItemId: ref('report-1'),
    coverStatus: ref(''),
    coverUrl: ref(''),
    dialogVisible: ref(true),
  }
  let refreshCount = 0
  const controller = useWechatCoverController({
    apiBase: 'http://local.test/publishing',
    request: {
      async post() {
        return {
          data: {
            active_cover_id: 'cover-2',
            cover_url: '/cover-2.png',
            covers: [{ id: 'cover-2' }],
          },
        }
      },
    },
    notify: silentNotifications(),
    draftState,
    refreshContentItems: async () => { refreshCount += 1 },
  })

  await controller.selectWechatReportCover({ contentItemId: 'report-1', coverId: 'cover-2' })

  assert.equal(draftState.coverUrl.value, '/cover-2.png')
  assert.equal(draftState.coverStatus.value, 'qwen_generated')
  assert.equal(controller.wechatCoverHistoryForContent('report-1').active_cover_id, 'cover-2')
  assert.equal(refreshCount, 1)
  controller.disposeWechatCoverController()
})
