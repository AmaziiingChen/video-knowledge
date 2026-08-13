import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatReportGroupController } from './useWechatReportGroupController.js'

function createController() {
  const calls = []
  const notifications = []
  const selectedReportPromptGroupId = ref('old-group')
  const request = {
    async post(...args) {
      calls.push(['post', ...args])
      return { data: { id: 'new-group' } }
    },
    async delete(...args) {
      calls.push(['delete', ...args])
      return { data: { affected_subscription_count: 2 } }
    },
    async put(...args) { calls.push(['put', ...args]) },
  }
  const controller = useWechatReportGroupController({
    reportGroupApi: '/api/wechat/report-groups',
    loadSubscriptions: async () => { calls.push(['load-subscriptions']) },
    loadReportPrompts: async () => { calls.push(['load-prompts']) },
    selectedReportPromptGroupId,
    request,
    notify: {
      success: (message) => notifications.push(['success', message]),
      error: (message) => notifications.push(['error', message]),
    },
    errorMessage: (error, fallback) => error?.message || fallback,
  })
  return { calls, controller, notifications, request, selectedReportPromptGroupId }
}

test('creates a report group, selects it for prompts, then refreshes both dependent views', async () => {
  const { calls, controller, notifications, selectedReportPromptGroupId } = createController()
  let completed = 0

  await controller.createWeChatReportGroup({ name: '每周观察' }, () => { completed += 1 })

  assert.deepEqual(calls, [
    ['post', '/api/wechat/report-groups', { name: '每周观察' }, { timeout: 10000 }],
    ['load-subscriptions'],
    ['load-prompts'],
  ])
  assert.equal(completed, 1)
  assert.equal(selectedReportPromptGroupId.value, 'new-group')
  assert.deepEqual(notifications, [['success', '报告分组已添加；可前往“提示词 → 分组报告”完善区间报告写法']])
})

test('deletes one group at a time and releases its busy state after refresh', async () => {
  const { calls, controller, notifications } = createController()
  const group = { id: 'g-1', name: '每周观察' }

  await controller.deleteWeChatReportGroup(group)

  assert.deepEqual(calls, [
    ['delete', '/api/wechat/report-groups/g-1', { timeout: 10000 }],
    ['load-subscriptions'],
    ['load-prompts'],
  ])
  assert.equal(controller.wechatDeletingGroupId.value, '')
  assert.deepEqual(notifications, [['success', '分组“每周观察”已删除，已从 2 个公众号移除标签']])
})

test('does not start a second group deletion while one is already in progress', async () => {
  const { calls, controller } = createController()
  controller.wechatDeletingGroupId.value = 'g-1'

  await controller.deleteWeChatReportGroup({ id: 'g-2', name: '另一个分组' })

  assert.deepEqual(calls, [])
  assert.equal(controller.wechatDeletingGroupId.value, 'g-1')
})

test('saves an encoded report schedule and never invokes its completion callback after an error', async () => {
  const { calls, controller, notifications, request } = createController()
  let completed = 0

  await controller.saveWeChatReportSchedule('weekly/report', { enabled: true }, () => { completed += 1 })
  assert.deepEqual(calls, [
    ['put', '/api/wechat/report-groups/weekly%2Freport/schedule', { enabled: true }, { timeout: 10000 }],
    ['load-subscriptions'],
  ])
  assert.equal(completed, 1)
  assert.equal(controller.wechatSavingScheduleGroupId.value, '')
  assert.deepEqual(notifications, [['success', '已开启定时生成']])

  request.put = async () => { throw new Error('无法保存') }
  await controller.saveWeChatReportSchedule('g-1', { enabled: false }, () => { completed += 1 })
  assert.equal(completed, 1)
  assert.equal(controller.wechatSavingScheduleGroupId.value, '')
  assert.deepEqual(notifications.at(-1), ['error', '无法保存'])
})
