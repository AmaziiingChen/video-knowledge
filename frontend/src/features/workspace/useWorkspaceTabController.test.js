import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWorkspaceTabController } from './useWorkspaceTabController.js'

function content(id, overrides = {}) {
  return {
    id,
    title: `资料 ${id}`,
    source_provider: 'wechat',
    status: 'ready',
    ...overrides,
  }
}

function createController({ tabs = [], items = [], details = {}, selected = null } = {}) {
  const selectedItems = []
  const resets = { markdown: 0, qa: 0 }
  const revealed = []
  const deleted = []
  const errors = []
  const detailRequests = []
  const workspaceTabs = ref(tabs)
  const activeWorkspaceTabId = ref(tabs[0]?.id || '')
  const activeView = ref('reports')
  const selectedContentItem = ref(selected)
  const controller = useWorkspaceTabController({
    workspaceTabs,
    activeWorkspaceTabId,
    activeView,
    allContentItems: ref(items),
    selectedContentItem,
    getContentItemDetail: async (id) => { detailRequests.push(id); return details[id] || null },
    selectContentItem: async (item, options) => { selectedItems.push([item, options]) },
    resetMarkdownState: () => { resets.markdown += 1 },
    detachQaSession: () => { resets.qa += 1 },
    revealLibraryNodeLocation: async (target) => { revealed.push(target) },
    deleteContentItem: async (item) => { deleted.push(item) },
    notify: { error: (message) => errors.push(message) },
  })
  return {
    controller,
    workspaceTabs,
    activeWorkspaceTabId,
    activeView,
    selectedContentItem,
    selectedItems,
    resets,
    revealed,
    deleted,
    errors,
    detailRequests,
  }
}

test('opening a content tab updates existing metadata and activates the hydrated item', async () => {
  const initial = content('one', { title: '旧标题', status: 'inbox' })
  const { controller, workspaceTabs, activeWorkspaceTabId, activeView, selectedItems } = createController({
    tabs: [{ id: 'content:one', content_item_id: 'one', title: '旧标题', status: 'inbox' }],
    items: [initial],
  })

  await controller.openContentTab(content('one', { title: '新标题' }))

  assert.equal(workspaceTabs.value.length, 1)
  assert.equal(workspaceTabs.value[0].title, '新标题')
  assert.equal(activeWorkspaceTabId.value, 'content:one')
  assert.equal(activeView.value, 'library')
  assert.deepEqual(selectedItems, [[initial, undefined]])
})

test('closing the active tab selects the next remaining tab and resets only after the final close', async () => {
  const one = content('one')
  const two = content('two')
  const three = content('three')
  const state = createController({
    tabs: [
      { id: 'content:one', content_item_id: 'one' },
      { id: 'content:two', content_item_id: 'two' },
      { id: 'content:three', content_item_id: 'three' },
    ],
    items: [one, two, three],
  })
  state.activeWorkspaceTabId.value = 'content:two'

  state.controller.closeWorkspaceTab('content:two')
  await Promise.resolve()

  assert.deepEqual(state.workspaceTabs.value.map((tab) => tab.id), ['content:one', 'content:three'])
  assert.equal(state.activeWorkspaceTabId.value, 'content:three')
  assert.deepEqual(state.selectedItems, [[three, undefined]])
  assert.deepEqual(state.resets, { markdown: 0, qa: 0 })

  state.controller.closeWorkspaceTabs(['content:one', 'content:three'])
  assert.equal(state.activeWorkspaceTabId.value, '')
  assert.equal(state.selectedContentItem.value, null)
  assert.deepEqual(state.resets, { markdown: 1, qa: 1 })
})

test('restored tabs hydrate missing details and preserve preview-awaiting selection', async () => {
  const hydrated = content('one', { title: '已恢复资料' })
  const { controller, workspaceTabs, selectedItems } = createController({
    tabs: [{ id: 'content:one', content_item_id: 'one', title: '旧标题' }],
    details: { one: hydrated },
  })

  await controller.syncActiveWorkspaceTabSelection({ awaitPrimaryPreview: true })

  assert.equal(workspaceTabs.value[0].title, '已恢复资料')
  assert.deepEqual(selectedItems, [[hydrated, { awaitPrimaryPreview: true }]])
})

test('completed tasks hydrate only their detail before opening its tab', async () => {
  const hydrated = content('one')
  const state = createController({ items: [hydrated], details: { one: hydrated } })

  await state.controller.syncCompletedTaskContent('one')

  assert.equal(state.activeWorkspaceTabId.value, 'content:one')
  assert.deepEqual(state.workspaceTabs.value.map((tab) => tab.content_item_id), ['one'])
  assert.deepEqual(state.selectedItems, [[hydrated, undefined]])
  assert.deepEqual(state.detailRequests, ['one'])
})

test('tab reveal and deletion use the content identity and keep a missing item recoverable', async () => {
  const current = content('one')
  const state = createController({ items: [current] })

  await state.controller.revealWorkspaceTabLocation({ content_item_id: 'one' })
  await state.controller.deleteWorkspaceTabContent({ content_item_id: 'one' })
  await state.controller.deleteWorkspaceTabContent({ content_item_id: 'missing' })

  assert.deepEqual(state.revealed, [{ type: 'content', id: 'one' }])
  assert.deepEqual(state.deleted, [current])
  assert.deepEqual(state.errors, ['找不到该文件，无法移入回收站'])
})
