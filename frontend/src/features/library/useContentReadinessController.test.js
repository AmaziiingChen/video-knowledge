import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useContentReadinessController } from './useContentReadinessController.js'

function createController({ items = [{ id: 'content-1', title: '旧标题' }], request = {} } = {}) {
  const allContentItems = ref(items)
  const selectedContentItem = ref(items[0] || null)
  let filterCalls = 0
  const controller = useContentReadinessController({
    allContentItems,
    selectedContentItem,
    applyContentFilter: () => { filterCalls += 1 },
    request: { get: async () => ({ data: {} }), ...request },
    apiBase: 'http://api.test',
  })
  return { controller, allContentItems, selectedContentItem, filterCalls: () => filterCalls }
}

test('detail hydration replaces an existing lazy-tree item and refreshes presentation', async () => {
  const calls = []
  const { controller, allContentItems, filterCalls } = createController({
    request: {
      get: async (...args) => {
        calls.push(args)
        return { data: { id: 'content-1', title: '完整标题', text_readiness: { state: 'ready' } } }
      },
    },
  })
  const detail = await controller.getContentItemDetail('content-1')
  assert.deepEqual(calls, [['http://api.test/content/item/content-1', { timeout: 10000 }]])
  assert.equal(detail.title, '完整标题')
  assert.deepEqual(allContentItems.value, [detail])
  assert.equal(filterCalls(), 1)
})

test('text readiness updates both the tree row and its selected detail', () => {
  const { controller, allContentItems, selectedContentItem, filterCalls } = createController()
  controller.mergeContentTextReadiness('content-1', { state: 'queued', retryable: true })
  assert.deepEqual(allContentItems.value[0].text_readiness, { state: 'queued', retryable: true })
  assert.deepEqual(selectedContentItem.value.text_readiness, { state: 'queued', retryable: true })
  assert.equal(filterCalls(), 1)
})

test('readiness refresh returns no value when the local backend is unavailable', async () => {
  const { controller } = createController({ request: { get: async () => { throw new Error('offline') } } })
  assert.equal(await controller.refreshContentTextReadiness('content-1'), null)
})
