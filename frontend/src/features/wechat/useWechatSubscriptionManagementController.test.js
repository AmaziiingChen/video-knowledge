import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatSubscriptionManagementController } from './useWechatSubscriptionManagementController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createController({ subscriptions = [], groups = [], request = {}, observeTask = () => {} } = {}) {
  const messages = []
  const calls = { subscriptions: 0, content: 0 }
  const state = {
    selectedAccountId: ref('account-1'),
    subscriptions: ref(subscriptions),
    reportGroups: ref(groups),
    subscriptionStates: ref({}),
    syncInterval: ref(1440),
    autoProcess: ref(false),
  }
  const controller = useWechatSubscriptionManagementController({
    ...state,
    loadSubscriptions: async () => { calls.subscriptions += 1 },
    refreshContentItems: async () => { calls.content += 1 },
    observeTask,
    request: {
      post: async () => ({ data: {} }),
      patch: async () => ({ data: {} }),
      delete: async () => ({ data: {} }),
      ...request,
    },
    apiBase: 'http://api.test/wechat-subscriptions',
    notify: Object.fromEntries(['success', 'warning', 'error', 'info'].map((type) => [type, (message) => messages.push([type, message])])),
    errorMessage: (_error, fallback) => fallback,
  })
  return { controller, messages, calls, ...state }
}

test('subscribing keeps the initial-sync payload, visible state and incremental refresh contract', async () => {
  let observer
  const requests = []
  const { controller, subscriptions, subscriptionStates, calls, messages } = createController({
    request: {
      post: async (...args) => {
        requests.push(args)
        return { data: { subscription: { id: 'sub-1', account_id: 'account-1', fakeid: 'fake-1', mp_name: '测试号' }, sync: { task_id: 'sync-1' } } }
      },
    },
    observeTask: (_taskId, handlers) => { observer = handlers },
  })

  await controller.subscribeWeChatAccount({ fakeid: 'fake-1', name: '测试号', biz: 'biz-1' })

  assert.deepEqual(requests, [[
    'http://api.test/wechat-subscriptions',
    {
      account_id: 'account-1', fakeid: 'fake-1', mp_name: '测试号', biz: 'biz-1', avatar_url: '', description: '',
      sync_interval_minutes: 1440, auto_process: false, initial_sync: true, initial_limit: 10,
    },
    { timeout: 15000 },
  ]])
  assert.equal(subscriptions.value[0].id, 'sub-1')
  assert.equal(subscriptionStates.value['account-1:fake-1'], 'checking')
  await observer.onSucceeded()
  assert.deepEqual(subscriptionStates.value, {})
  assert.deepEqual(calls, { subscriptions: 1, content: 2 })
  assert.deepEqual(messages, [['success', '公众号已订阅，正在后台检查最近文章']])
})

test('a stale optimistic update cannot overwrite or roll back a newer response', async () => {
  const first = deferred()
  const second = deferred()
  let patchCount = 0
  const { controller, subscriptions } = createController({
    subscriptions: [{ id: 'sub-1', enabled: true, mp_name: '测试号' }],
    request: {
      patch: async () => {
        patchCount += 1
        return patchCount === 1 ? first.promise : second.promise
      },
    },
  })

  const oldUpdate = controller.updateWeChatSubscription(subscriptions.value[0], { enabled: false })
  const newUpdate = controller.updateWeChatSubscription(subscriptions.value[0], { enabled: true })
  second.resolve({ data: { id: 'sub-1', enabled: true, server_version: 2 } })
  await newUpdate
  first.reject(new Error('offline'))
  await oldUpdate

  assert.deepEqual(subscriptions.value, [{ id: 'sub-1', enabled: true, mp_name: '测试号', server_version: 2 }])
})

test('bulk updates admit only supported fields and group additions skip duplicates and full memberships', async () => {
  const patches = []
  const { controller, subscriptions, messages } = createController({
    groups: [{ id: 'group-1', name: '校园生活' }],
    subscriptions: [
      { id: 'sub-1', group_ids: [] },
      { id: 'sub-2', group_ids: ['group-1'] },
      { id: 'sub-3', group_ids: ['a', 'b', 'c'] },
    ],
    request: {
      patch: async (...args) => {
        patches.push(args)
        return { data: { id: args[0].split('/').at(-1), ...args[1] } }
      },
    },
  })

  await controller.bulkUpdateWeChatSubscriptions({
    subscriptionIds: ['sub-1'],
    payload: { enabled: false, mp_name: 'must not pass' },
    label: '状态',
  })
  await controller.bulkAddWeChatSubscriptionGroup({ subscriptionIds: subscriptions.value.map((item) => item.id), groupId: 'group-1' })

  assert.deepEqual(patches, [
    ['http://api.test/wechat-subscriptions/sub-1', { enabled: false }, { timeout: 10000 }],
    ['http://api.test/wechat-subscriptions/sub-1', { group_ids: ['group-1'] }, { timeout: 10000 }],
  ])
  assert.deepEqual(messages, [
    ['success', '已更新 1 个公众号的状态'],
    ['success', '已将“校园生活”添加到 1 个公众号；2 个已存在该分组或已达到上限'],
  ])
})

test('profile refresh always releases its busy state after an error', async () => {
  const { controller, messages } = createController({ request: { post: async () => { throw new Error('offline') } } })
  await controller.refreshWeChatSubscriptionProfile('sub-1')
  assert.equal(controller.refreshingWeChatProfileId.value, '')
  assert.deepEqual(messages, [['error', '更新公众号资料失败']])
})
