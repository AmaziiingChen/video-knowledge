import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useLibraryNodeEditingController } from './useLibraryNodeEditingController.js'

function createController({ nodes = [] } = {}) {
  const events = []
  const persistedFolderIds = []
  const openFolderIds = ref(new Set())
  const selectedKeys = ref(new Set())
  const selectedNodes = ref(nodes)
  const controller = useLibraryNodeEditingController({
    openFolderIds,
    selectedKeys,
    selectedNodes,
    saveOpenFolderIds: (ids) => persistedFolderIds.push(new Set(ids)),
    emit: (...args) => events.push(args),
  })
  return { controller, events, openFolderIds, persistedFolderIds, selectedKeys, selectedNodes }
}

test('creates a child-folder draft, persists its open parent, and focuses the latest editor input', async () => {
  const { controller, openFolderIds, persistedFolderIds } = createController()
  const first = { focusCalls: 0, selectCalls: 0, focus() { this.focusCalls += 1 }, select() { this.selectCalls += 1 } }
  const last = { focusCalls: 0, selectCalls: 0, focus() { this.focusCalls += 1 }, select() { this.selectCalls += 1 } }
  controller.editingInput.value = [first, last]

  controller.startNewFolder('folder-1')
  await nextTick()

  assert.equal(openFolderIds.value.has('folder-1'), true)
  assert.deepEqual([...persistedFolderIds[0]], ['folder-1'])
  assert.deepEqual(
    { ...controller.editingNode.value, id: undefined },
    { type: 'folder', id: undefined, value: '新建文件夹', isNew: true, parentFolderId: 'folder-1' },
  )
  assert.match(controller.editingNode.value.id, /^new:\d+$/u)
  assert.deepEqual([first.focusCalls, first.selectCalls, last.focusCalls, last.selectCalls], [0, 0, 1, 1])
})

test('emits the original create and rename payloads and cancels an empty edit', () => {
  const { controller, events } = createController()

  controller.startNewFolder(null)
  controller.editingNode.value.value = '  资料夹  '
  controller.commitEditing()
  controller.startRename({ type: 'folder', id: 'folder-1', name: '旧文件夹' })
  assert.equal(controller.isEditing({ type: 'folder', id: 'folder-1' }), true)
  controller.commitEditing()
  controller.startRename({ type: 'content', id: 'content-1', name: '旧标题' })
  controller.commitEditing()
  controller.editingNode.value = { type: 'folder', id: 'empty', value: '   ', isNew: false }
  controller.commitEditing()

  assert.deepEqual(events, [
    ['create-folder', { name: '资料夹', parent_folder_id: null }],
    ['rename-folder', { id: 'folder-1', name: '旧文件夹' }],
    ['rename-content', { id: 'content-1', title: '旧标题' }],
  ])
  assert.equal(controller.editingNode.value, null)
})

test('uses the selected folder for picker and dropped imports without changing either payload', () => {
  const folder = { type: 'folder', id: 'folder-1' }
  const { controller, events } = createController({ nodes: [folder] })
  const picker = { clickCalls: 0, click() { this.clickCalls += 1 } }
  controller.markdownImportInput.value = picker
  const pickedFile = { name: 'notes.md' }
  const droppedFile = { name: 'report.pdf' }
  const pickerEvent = { target: { files: [pickedFile], value: 'selected' } }

  controller.chooseMarkdownFile()
  controller.importMarkdownFile(pickerEvent)
  controller.importDroppedFiles({ dataTransfer: { files: [droppedFile] } })

  assert.equal(picker.clickCalls, 1)
  assert.equal(pickerEvent.target.value, '')
  assert.deepEqual(events, [
    ['import-markdown', { files: [pickedFile], libraryFolderId: 'folder-1' }],
    ['import-markdown', { files: [droppedFile], libraryFolderId: 'folder-1' }],
  ])
})

test('retains single-delete payloads and clears selection after a multi-delete request', () => {
  const folder = { type: 'folder', id: 'folder-1', raw: { id: 'folder-1', name: '资料' } }
  const content = { type: 'content', id: 'content-1', raw: { id: 'content-1', title: '文章' } }
  const { controller, events, selectedKeys } = createController({ nodes: [folder, content] })
  selectedKeys.value = new Set(['folder:folder-1', 'content:content-1'])

  controller.requestDelete(folder)
  controller.requestDelete(content)
  controller.requestDeleteSelected()

  assert.deepEqual(events, [
    ['delete-folder', folder.raw],
    ['delete-content', content.raw],
    ['delete-selected', [
      { id: 'folder-1', name: '资料', type: 'folder' },
      { id: 'content-1', title: '文章', type: 'content' },
    ]],
  ])
  assert.deepEqual([...selectedKeys.value], [])
})
