import assert from 'node:assert/strict'
import test from 'node:test'

import { useLibrarySourceGroupController } from './useLibrarySourceGroupController.js'

function createController({ confirmed = true } = {}) {
  const calls = []
  const notifications = []
  let groups = [{ id: 'group-1', name: '日报', sources: [{ kind: 'wechat', source_id: 'account/1' }] }]
  const request = {
    async get(...args) {
      calls.push(['get', ...args])
      return { data: groups }
    },
    async delete(...args) { calls.push(['delete', ...args]) },
  }
  const controller = useLibrarySourceGroupController({
    apiBase: '/api/content/source-groups',
    loadWeChatSubscriptions: async () => { calls.push(['load-wechat']) },
    loadCampusSources: async (options) => { calls.push(['load-campus', options]) },
    confirmDestructive: async (options) => {
      calls.push(['confirm', options])
      return confirmed
    },
    request,
    notify: {
      success: (message) => notifications.push(['success', message]),
      error: (message) => notifications.push(['error', message]),
    },
    errorMessage: (error, fallback) => error?.message || fallback,
  })
  return {
    calls,
    controller,
    notifications,
    request,
    setGroups: (value) => { groups = value },
  }
}

test('loads the current group before opening the source editor and falls back to the supplied group', async () => {
  const { calls, controller, setGroups } = createController()
  await controller.openSourceGroupEditor({ id: 'group-1', name: '过期名称' })
  assert.deepEqual(calls, [['get', '/api/content/source-groups', { timeout: 10000 }]])
  assert.equal(controller.sourceGroupEditor.value.name, '日报')
  assert.equal(controller.showSourceGroupEditor.value, true)

  setGroups([])
  await controller.openSourceGroupEditor({ id: 'missing', name: '仍可查看' })
  assert.deepEqual(controller.sourceGroupEditor.value, { id: 'missing', name: '仍可查看', sources: [] })
})

test('does not mutate a group when the user rejects the destructive confirmation', async () => {
  const { calls, controller } = createController({ confirmed: false })
  controller.sourceGroupEditor.value = { id: 'group-1', name: '日报' }

  await controller.removeSourceFromGroup({ kind: 'wechat', source_id: 'account-1', label: '每日新闻' })

  assert.equal(calls[0][0], 'confirm')
  assert.equal(calls.some((call) => call[0] === 'delete'), false)
  assert.equal(controller.removingSourceGroupKey.value, '')
})

test('removes a source, refreshes every dependent view, and closes an editor for a deleted group', async () => {
  const { calls, controller, notifications, setGroups } = createController()
  controller.sourceGroupEditor.value = { id: 'weekly/report', name: '日报' }
  setGroups([])

  await controller.removeSourceFromGroup({ kind: 'wechat/news', source_id: 'account/1', label: '每日新闻' })

  assert.deepEqual(calls.slice(0, 2), [
    ['confirm', {
      title: '移出分组',
      message: '将“每日新闻”移出“日报”？原来源与已收集内容会保留。',
      confirmLabel: '移出分组',
      cancelLabel: '保留',
    }],
    ['delete', '/api/content/source-groups/weekly%2Freport/sources/wechat%2Fnews/account%2F1', { timeout: 10000 }],
  ])
  assert.equal(calls.filter((call) => call[0] === 'get').length, 1)
  assert.equal(calls.filter((call) => call[0] === 'load-wechat').length, 1)
  assert.deepEqual(calls.find((call) => call[0] === 'load-campus'), ['load-campus', { silent: true }])
  assert.equal(controller.sourceGroupEditor.value, null)
  assert.equal(controller.showSourceGroupEditor.value, false)
  assert.equal(controller.removingSourceGroupKey.value, '')
  assert.deepEqual(notifications, [['success', '已将“每日新闻”移出“日报”']])
})

test('releases the busy state and reports a usable error if source removal fails', async () => {
  const { controller, notifications, request } = createController()
  controller.sourceGroupEditor.value = { id: 'group-1', name: '日报' }
  request.delete = async () => { throw new Error('网络异常') }

  await controller.removeSourceFromGroup({ kind: 'wechat', source_id: 'account-1' })

  assert.equal(controller.removingSourceGroupKey.value, '')
  assert.deepEqual(notifications, [['error', '网络异常']])
})
