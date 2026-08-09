import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { useWechatSubscriptionSyncController } from './useWechatSubscriptionSyncController.js'

function createController({ subscriptions = [], enqueueTask, observeTask } = {}) {
  const messages = []
  const loaded = { subscriptions: 0, content: 0 }
  const controller = useWechatSubscriptionSyncController({
    subscriptions: ref(subscriptions),
    enqueueTask,
    observeTask,
    loadSubscriptions: async () => { loaded.subscriptions += 1 },
    refreshContentItems: async () => { loaded.content += 1 },
    notify: Object.fromEntries(['success', 'error', 'warning', 'info'].map((type) => [type, (message) => messages.push([type, message])])),
    errorMessage: (_error, fallback) => fallback,
  })
  return { controller, messages, loaded }
}

test('single sync keeps the enqueue payload and refreshes after a successful task', async () => {
  let observer
  const { controller, messages, loaded } = createController({
    subscriptions: [{ id: 'sub-1', mp_name: '测试号', source_url: 'https://example.test' }],
    enqueueTask: async (payload) => {
      assert.deepEqual(payload, { kind: 'wechat_subscription', source_title: '测试号', source_url: 'https://example.test', subscription_id: 'sub-1', mode: 'latest', max_items: 10, published_after: undefined, published_before: undefined })
      return { task_id: 'task-1' }
    },
    observeTask: (_taskId, handlers) => { observer = handlers },
  })
  await controller.syncWeChatSubscription('sub-1')
  assert.equal(controller.syncingWeChatSubscriptionId.value, '')
  await observer.onSucceeded({ found_count: 3, imported_count: 2, queued_for_analysis: 1 })
  assert.equal(loaded.subscriptions, 1)
  assert.deepEqual(messages, [['success', '已开始检查公众号更新'], ['success', '检查完成：检查到 3 篇，新增 2 篇，已加入 1 篇自动分析']])
})

test('bulk sync handles empty subscriptions and maps progress to the enabled total', async () => {
  const empty = createController({ subscriptions: [], enqueueTask: async () => { throw new Error('must not run') } })
  await empty.controller.syncAllWeChatSubscriptions()
  assert.deepEqual(empty.messages, [['info', '没有已启用的公众号需要更新']])

  let observer
  const { controller, messages, loaded } = createController({
    subscriptions: [{ enabled: true }, { enabled: true }, { enabled: false }],
    enqueueTask: async (payload) => { assert.deepEqual(payload, { kind: 'wechat_bulk', source_title: '检查全部公众号' }); return { task_id: 'bulk-1', status: 'queued' } },
    observeTask: (_taskId, handlers) => { observer = handlers },
  })
  await controller.syncAllWeChatSubscriptions()
  observer.onUpdate({ status: 'running', overall_progress: 53, logs: [{ message: '正在检查：测试号，稍候' }] })
  assert.equal(controller.wechatBulkSyncState.value.completed, 1)
  assert.equal(controller.wechatBulkSyncState.value.current_name, '测试号')
  await observer.onSucceeded({ completed: 2, succeeded: 1, failed: 1, imported_count: 4, status: 'completed_with_errors' })
  assert.deepEqual(loaded, { subscriptions: 1, content: 1 })
  assert.equal(messages.at(-1)[0], 'warning')
})

test('failed task observers preserve error feedback', async () => {
  let observer
  const { controller, messages } = createController({
    subscriptions: [{ id: 'sub-1', enabled: true }],
    enqueueTask: async () => ({ task_id: 'task-1' }),
    observeTask: (_taskId, handlers) => { observer = handlers },
  })
  await controller.syncWeChatSubscription('sub-1')
  observer.onFailed('远端拒绝请求')
  assert.deepEqual(messages.at(-1), ['error', '远端拒绝请求'])
})
