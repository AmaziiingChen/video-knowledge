import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useUnreadDockBadgeController } from './useUnreadDockBadgeController.js'

function createController({ items, viewedIds = [], explicitlyUnreadIds = [], viewedBefore = '' } = {}) {
  const updates = []
  const controller = useUnreadDockBadgeController({
    allContentItems: ref(items || []),
    viewedContentIds: ref(viewedIds),
    explicitlyUnreadContentIds: ref(explicitlyUnreadIds),
    contentViewedBefore: ref(viewedBefore),
    desktop: { setUnreadBadgeCount: async (count) => updates.push(count) },
  })
  return { controller, updates }
}

test('mirrors the library unread rule into the desktop badge', async () => {
  const { controller, updates } = createController({
    viewedBefore: '2026-08-01T00:00:00.000Z',
    viewedIds: ['read'],
    items: [
      { id: 'old', created_at: '2026-07-01T00:00:00.000Z' },
      { id: 'read', created_at: '2026-08-02T00:00:00.000Z' },
      { id: 'new', created_at: '2026-08-02T00:00:00.000Z' },
    ],
  })

  await nextTick()
  assert.equal(controller.unreadCount.value, 1)
  assert.deepEqual(updates, [1])
  controller.dispose()
  await nextTick()
  assert.deepEqual(updates, [1, 0])
})

test('updates the badge when an item is marked read', async () => {
  const viewedContentIds = ref([])
  const updates = []
  const controller = useUnreadDockBadgeController({
    allContentItems: ref([{ id: 'new', created_at: '2026-08-02T00:00:00.000Z' }]),
    viewedContentIds,
    explicitlyUnreadContentIds: ref([]),
    contentViewedBefore: ref('2026-08-01T00:00:00.000Z'),
    desktop: { setUnreadBadgeCount: async (count) => updates.push(count) },
  })

  await nextTick()
  viewedContentIds.value = ['new']
  await nextTick()
  assert.deepEqual(updates, [1, 0])
  controller.dispose()
})
