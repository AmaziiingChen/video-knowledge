import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useCompletionNotificationController } from './useCompletionNotificationController.js'

function createController({ items = [], request = {}, getContentItemDetail = async () => null } = {}) {
  const allContentItems = ref(items)
  const activeView = ref('library')
  const opened = []
  const trayUpdates = []
  const intervals = []
  const cancelled = []
  const controller = useCompletionNotificationController({
    allContentItems,
    getContentItemDetail,
    openContentTab: async (item) => opened.push(item),
    activeView,
    ribbonItems: [{ view: 'library' }, { view: 'reports' }],
    desktop: { setPendingNotifications: async (entries) => trayUpdates.push(entries) },
    request: {
      get: async () => ({ data: [] }),
      post: async () => ({ data: {} }),
      ...request,
    },
    apiBase: 'http://api.test',
    scheduleInterval: (callback, delay) => {
      const timer = { callback, delay }
      intervals.push(timer)
      return timer
    },
    cancelInterval: (timer) => cancelled.push(timer),
  })
  return { controller, activeView, opened, trayUpdates, intervals, cancelled }
}

test('refreshes bounded notifications into the desktop tray without surfacing auxiliary failures', async () => {
  const calls = []
  const { controller, trayUpdates } = createController({
    request: {
      get: async (...args) => {
        calls.push(args)
        return { data: [{ id: 'notice-1' }] }
      },
    },
  })
  await controller.loadCompletionNotifications()
  assert.deepEqual(calls, [['http://api.test/completion-notifications', { params: { limit: 20 }, timeout: 10000 }]])
  assert.deepEqual(controller.completionNotifications.value, [{ id: 'notice-1' }])
  assert.deepEqual(trayUpdates, [[{ id: 'notice-1' }]])
})

test('opens local content, marks a notification seen, then refreshes the tray', async () => {
  const calls = []
  const item = { id: 'content-1', title: '资料' }
  const { controller, opened } = createController({
    items: [item],
    request: {
      get: async (...args) => { calls.push(args); return { data: [] } },
      post: async (...args) => { calls.push(args); return { data: {} } },
    },
  })
  await controller.openCompletionNotification({ id: 'notice-1', content_item_id: 'content-1' })
  assert.deepEqual(opened, [item])
  assert.deepEqual(calls, [
    ['http://api.test/completion-notifications/seen', { ids: ['notice-1'] }, { timeout: 10000 }],
    ['http://api.test/completion-notifications', { params: { limit: 20 }, timeout: 10000 }],
  ])
})

test('uses allowed target views and releases its only interval on stop', () => {
  const { controller, activeView, intervals, cancelled } = createController()
  controller.openCompletionNotification({ target_view: 'reports' })
  assert.equal(activeView.value, 'reports')
  controller.startCompletionNotificationPolling()
  controller.startCompletionNotificationPolling()
  assert.deepEqual(intervals.map((timer) => timer.delay), [15000])
  controller.stopCompletionNotificationPolling()
  assert.deepEqual(cancelled, intervals)
})
