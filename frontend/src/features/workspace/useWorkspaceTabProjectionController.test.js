import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'

import { useWorkspaceTabProjectionController } from './useWorkspaceTabProjectionController.js'

function createController({
  tabs = [{ id: 'content:1', content_item_id: '1', status: 'inbox' }],
  activeTabId = 'content:1',
  items = [{ id: '1', title: 'Listed', status: 'inbox', video_path: '/listed.mp4' }],
  selected = null,
  tasks = [],
  result = {},
} = {}) {
  return useWorkspaceTabProjectionController({
    workspaceTabs: ref(tabs),
    activeWorkspaceTabId: ref(activeTabId),
    allContentItems: ref(items),
    selectedContentItem: ref(selected),
    batchTasks: ref(tasks),
    result: reactive(result),
    selectedMarkdownSourceText: ref('已加载正文'),
    articlePreviews: reactive({ 1: { html: '<p>预览</p>' } }),
    isActiveTask: (task) => ['queued', 'running'].includes(task?.status),
    localApiRequestUrl: (url) => `local:${url}`,
    apiBase: 'http://api.test',
  })
}

test('keeps a hydrated selected item over a paginated pending library row', () => {
  const selected = {
    id: '1',
    title: 'Hydrated',
    text_readiness: { status: 'ready' },
    original_file_path: '/original.pdf',
  }
  const controller = createController({
    selected,
    items: [{ id: '1', title: 'Listed', text_readiness: { status: 'pending' } }],
  })

  assert.equal(controller.activeWorkspaceContent.value.title, 'Hydrated')
  assert.equal(controller.contentForTab('content:1').title, 'Hydrated')
  assert.equal(controller.originalMediaUrlForTab('content:1'), 'local:http://api.test/media?path=%2Foriginal.pdf')
})

test('uses a live task before stale task or global result snapshots', () => {
  const controller = createController({
    tasks: [
      { task_id: 'old', content_item_id: '1', status: 'succeeded', transcript: 'old' },
      { task_id: 'live', content_item_id: '1', status: 'running', transcript: 'live', video_path: '/live.mp4' },
    ],
    result: { content_item_id: '1', transcript: 'global' },
  })

  assert.equal(controller.resultForTab('content:1').task_id, 'live')
  assert.equal(controller.activeWorkspaceTranscript.value, 'live')
  assert.equal(controller.mediaUrlForTab('content:1'), 'local:http://api.test/media?path=%2Flive.mp4')
})

test('falls back to the selected source text only for the active article family', () => {
  const article = { id: '1', content_type: 'article', status: 'ready' }
  const controller = createController({ items: [article], selected: article })

  assert.equal(controller.transcriptForTab('content:1'), '已加载正文')
  assert.equal(controller.activeWorkspaceTranscript.value, '已加载正文')
  assert.deepEqual(controller.articlePreviewForTab('content:1'), { html: '<p>预览</p>' })
})
