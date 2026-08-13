import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useLibraryOpenFolderController } from './useLibraryOpenFolderController.js'

function createController({
  folders = [],
  history = {},
  revealed = [],
  unreadCounts = new Map(),
  initiallyOpen = [],
} = {}) {
  const events = []
  const persisted = []
  const libraryFolders = ref(folders)
  const folderHistoryStates = ref(history)
  const revealedLibraryFolderIds = ref(revealed)
  const folderUnreadCounts = ref(unreadCounts)
  const controller = useLibraryOpenFolderController({
    libraryFolders,
    folderHistoryStates,
    revealedLibraryFolderIds,
    folderUnreadCounts,
    emit: (...args) => events.push(args),
    loadOpenFolderIds: () => new Set(initiallyOpen),
    saveOpenFolderIds: (ids) => persisted.push(new Set(ids)),
  })
  return {
    controller,
    events,
    persisted,
    libraryFolders,
    folderHistoryStates,
    revealedLibraryFolderIds,
    folderUnreadCounts,
  }
}

test('hydrates only known open folders and does not duplicate loaded or loading requests', async () => {
  const state = createController({
    folders: [{ id: 'ready' }, { id: 'loading' }, { id: 'pending' }],
    history: { ready: { loaded: true }, loading: { loading: true } },
    initiallyOpen: ['ready', 'loading', 'pending', 'missing'],
  })
  await nextTick()

  assert.deepEqual(state.events, [
    ['load-folder-history', { folderId: 'pending', append: false }],
  ])
  assert.equal(state.controller.folderHistoryState('ready').loaded, true)
  assert.equal(state.controller.folderHistoryState('missing'), null)
})

test('hydrates a saved open branch once when its folder arrives after startup', async () => {
  const state = createController({ initiallyOpen: ['later'] })
  await nextTick()
  assert.deepEqual(state.events, [])

  state.libraryFolders.value = [{ id: 'later' }]
  await nextTick()

  assert.deepEqual(state.events, [
    ['load-folder-history', { folderId: 'later', append: false }],
  ])
})

test('opens and closes a folder with the original lazy-load and persistence contract', async () => {
  const state = createController({ folders: [{ id: 7 }] })
  state.controller.toggleFolder(7)
  await nextTick()

  assert.equal(state.controller.isFolderOpen('7'), true)
  assert.deepEqual(state.events, [
    ['load-folder-history', { folderId: '7', append: false }],
  ])
  assert.deepEqual([...state.persisted[0]], ['7'])

  state.controller.toggleFolder('7')
  await nextTick()
  assert.equal(state.controller.isFolderOpen('7'), false)
  assert.equal(state.events.length, 1)
  assert.deepEqual([...state.persisted.at(-1)], [])
})

test('reveals a folder and every known ancestor without looping on malformed parents', async () => {
  const state = createController({
    folders: [
      { id: 'root' },
      { id: 'child', parent_folder_id: 'root' },
      { id: 'leaf', parent_folder_id: 'child' },
      { id: 'cycle-a', parent_folder_id: 'cycle-b' },
      { id: 'cycle-b', parent_folder_id: 'cycle-a' },
    ],
    revealed: ['leaf', 'missing', 'cycle-a'],
  })
  await nextTick()

  assert.deepEqual(
    [...state.controller.openFolderIds.value].sort(),
    ['child', 'cycle-a', 'cycle-b', 'leaf', 'root'],
  )
  assert.deepEqual(
    [...state.persisted[0]].sort(),
    ['child', 'cycle-a', 'cycle-b', 'leaf', 'root'],
  )
  assert.deepEqual(
    state.events.map(([, payload]) => payload.folderId).sort(),
    ['child', 'cycle-a', 'cycle-b', 'leaf', 'root'],
  )
})

test('keeps virtual roots local and expands only folders in an unread descendant chain', () => {
  const state = createController({
    folders: [
      { id: 'root' },
      { id: 'child', parent_folder_id: 'root' },
      { id: 'leaf', parent_folder_id: 'child' },
      { id: 'other' },
    ],
    unreadCounts: new Map([
      ['root', 1],
      ['child', 1],
      ['leaf', 1],
      ['other', 0],
    ]),
  })

  assert.equal(state.controller.isNodeOpen({ type: 'unread-root' }), false)
  assert.equal(state.controller.isNodeOpen({ type: 'pinned-root' }), true)
  assert.equal(state.controller.toggleVirtualRoot({ type: 'pinned-root' }), true)
  assert.equal(state.controller.isNodeOpen({ type: 'pinned-root' }), false)
  assert.equal(state.controller.toggleVirtualRoot({ type: 'folder', id: 'root' }), false)
  state.controller.expandUnreadInNode({ type: 'unread-root', unreadCount: 1 })
  assert.equal(state.controller.isNodeOpen({ type: 'unread-root' }), true)

  state.controller.expandUnreadInNode({ type: 'folder', id: 'root', unreadCount: 1 })
  assert.deepEqual([...state.controller.openFolderIds.value].sort(), ['child', 'leaf', 'root'])
  assert.deepEqual([...state.persisted.at(-1)].sort(), ['child', 'leaf', 'root'])
})
