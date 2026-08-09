import assert from 'node:assert/strict'
import test from 'node:test'

import { useLibraryTrashController } from './useLibraryTrashController.js'

function createController({ request = {}, dependencies = {} } = {}) {
  const successes = []
  const errors = []
  const notices = []
  const notify = (options) => {
    notices.push(options)
    return { close: () => { options.closed = true } }
  }
  notify.success = (message) => successes.push(message)
  notify.error = (message) => errors.push(message)
  const calls = { content: [], folders: [], reveal: [], expand: [], reset: 0 }
  const controller = useLibraryTrashController({
    request: {
      get: async () => ({ data: [] }),
      post: async () => ({ data: {} }),
      delete: async () => ({ data: {} }),
      ...request,
    },
    notify,
    renderVNode: (tag, props, children) => ({ tag, props, children }),
    loadContentItems: async () => { calls.content.push(true) },
    loadLibraryFolders: async () => { calls.folders.push(true) },
    revealContentItems: async (ids) => { calls.reveal.push(ids) },
    expandLibraryFolders: (ids) => { calls.expand.push(ids) },
    resetLibraryHistory: () => { calls.reset += 1 },
    ...dependencies,
  })
  return { controller, calls, successes, errors, notices }
}

test('loads trash entries and always releases its loading state', async () => {
  const { controller } = createController({ request: { get: async () => ({ data: [{ id: 'trash-1' }] }) } })
  await controller.loadLibraryTrash()
  assert.deepEqual(controller.libraryTrashEntries.value, [{ id: 'trash-1' }])
  assert.equal(controller.loadingLibraryTrash.value, false)
})

test('restoring entries refreshes the tree, reveals files, expands folders, and clears history', async () => {
  const requests = []
  const { controller, calls, successes } = createController({
    request: {
      get: async () => ({ data: [] }),
      post: async (...args) => {
        requests.push(args)
        return { data: { restored_content_ids: ['content-1'], restored_folder_ids: ['folder-1'] } }
      },
    },
  })

  assert.equal(await controller.restoreLibraryTrashEntry({ entry_type: 'content', id: 'trash-1', name: '资料' }), true)
  assert.deepEqual(requests, [[
    'http://127.0.0.1:8000/api/content/trash/content/trash-1/restore', null, { timeout: 10000 },
  ]])
  assert.equal(calls.content.length, 1)
  assert.deepEqual(calls.reveal, [['content-1']])
  assert.deepEqual(calls.expand, [['folder-1']])
  assert.equal(calls.reset, 1)
  assert.deepEqual(successes, ['已恢复“资料”'])
})

test('a failed restore refreshes recoverable views but leaves history untouched', async () => {
  const { controller, calls, errors } = createController({
    request: { post: async () => { throw new Error('恢复连接失败') } },
  })

  assert.equal(await controller.restoreLibraryTrashEntry({ entry_type: 'folder', id: 'trash-1' }), false)
  assert.equal(calls.content.length, 1)
  assert.equal(calls.reset, 0)
  assert.deepEqual(errors, ['恢复连接失败'])
})

test('permanent delete and empty trash refresh their affected views and report counts', async () => {
  const deleted = []
  const { controller, calls, successes } = createController({
    request: {
      delete: async (...args) => {
        deleted.push(args)
        return args[0].endsWith('/trash')
          ? { data: { deleted_content_count: 2, deleted_folder_count: 1 } }
          : { data: {} }
      },
    },
  })

  await controller.permanentlyDeleteLibraryTrashEntry({ entry_type: 'content', id: 'trash-1' })
  await controller.emptyLibraryTrash()
  assert.deepEqual(deleted.map(([url]) => url), [
    'http://127.0.0.1:8000/api/content/trash/content/trash-1',
    'http://127.0.0.1:8000/api/content/trash',
  ])
  assert.equal(calls.content.length, 1)
  assert.equal(calls.folders.length, 1)
  assert.equal(calls.reset, 1)
  assert.deepEqual(successes, ['已彻底删除', '已清空回收站（3 项）'])
})

test('the undo notice closes and restores at most once', async () => {
  let restores = 0
  const { controller, notices, successes } = createController({
    request: { post: async () => { restores += 1; return { data: {} } } },
  })
  controller.showTrashUndoMessage([{ entry_type: 'content', id: 'trash-1', name: '资料' }], '已移入回收站')
  const undo = notices[0].message.children[1].props.onClick
  await Promise.all([undo(), undo()])

  assert.equal(restores, 1)
  assert.equal(notices[0].closed, true)
  assert.deepEqual(successes, ['已撤销移除“资料”'])
})
