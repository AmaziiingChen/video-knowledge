import assert from 'node:assert/strict'
import test from 'node:test'
import { setImmediate as waitForImmediate } from 'node:timers/promises'

import { ref } from 'vue'

import {
  isLocalHtmlDocument,
  useContentSelectionController,
} from './useContentSelectionController.js'

function createController({ selected = null, getDetail, qaActive = false } = {}) {
  const calls = {
    details: [],
    readiness: [],
    previews: [],
    activations: [],
    histories: [],
    viewed: [],
    ocr: 0,
    ai: [],
    markdown: [],
  }
  const selectedContentItem = ref(selected)
  const currentMarkdownItem = ref(null)
  const controller = useContentSelectionController({
    selectedContentItem,
    currentMarkdownItem,
    getContentItemDetail: async (id) => {
      calls.details.push(id)
      return getDetail ? getDetail(id) : selectedContentItem.value
    },
    updatePendingArticlePreviewReadiness: (item) => calls.readiness.push(item),
    loadArticlePreview: async (item) => calls.previews.push(item),
    activateQaSession: (id) => {
      calls.activations.push(id)
      return `session:${id}`
    },
    isQaSessionActive: () => qaActive,
    loadContentQaHistory: async (...args) => calls.histories.push(args),
    scheduleContentViewed: (id) => calls.viewed.push(id),
    loadCurrentArticleOcrStatus: async () => { calls.ocr += 1 },
    loadContentAiCalls: async (id) => calls.ai.push(id),
    loadMarkdownForItem: async (item) => calls.markdown.push(item),
  })
  return { controller, selectedContentItem, currentMarkdownItem, calls }
}

test('selects and hydrates an article through the established preview and session transaction', async () => {
  const item = { id: 'article-1', content_type: 'article', source_provider: 'wechat' }
  const detail = { ...item, title: 'Hydrated article' }
  const { controller, selectedContentItem, currentMarkdownItem, calls } = createController({
    getDetail: async () => detail,
  })

  await controller.selectContentItem(item, { awaitPrimaryPreview: true })

  assert.deepEqual(selectedContentItem.value, detail)
  assert.deepEqual(currentMarkdownItem.value, detail)
  assert.deepEqual(calls.details, ['article-1'])
  assert.deepEqual(calls.readiness, [detail])
  assert.deepEqual(calls.previews, [item])
  assert.deepEqual(calls.activations, ['article-1'])
  assert.deepEqual(calls.histories, [['article-1', 'session:article-1']])
  assert.deepEqual(calls.viewed, ['article-1'])
  assert.equal(calls.ocr, 1)
  assert.deepEqual(calls.ai, ['article-1'])
  assert.deepEqual(calls.markdown, [item])
})

test('a stale detail response cannot replace the newer selected content', async () => {
  let resolveFirstDetail
  const firstDetail = new Promise((resolve) => { resolveFirstDetail = resolve })
  const first = { id: 'first', content_type: 'document', source_provider: 'local_file' }
  const second = { id: 'second', content_type: 'document', source_provider: 'local_file' }
  const hydratedSecond = { ...second, title: 'Current' }
  const { controller, selectedContentItem, currentMarkdownItem, calls } = createController({
    getDetail: (id) => (id === 'first' ? firstDetail : hydratedSecond),
  })

  await controller.selectContentItem(first)
  await controller.selectContentItem(second, { awaitPrimaryPreview: true })
  resolveFirstDetail({ ...first, title: 'Stale' })
  await waitForImmediate()

  assert.deepEqual(selectedContentItem.value, hydratedSecond)
  assert.deepEqual(currentMarkdownItem.value, hydratedSecond)
  assert.deepEqual(calls.readiness, [hydratedSecond])
})

test('reselecting an inactive session activates it without reloading saved history', async () => {
  const item = { id: 'same', content_type: 'video', source_provider: 'bilibili' }
  const { controller, calls } = createController({ selected: item, getDetail: async () => item })

  await controller.selectContentItem(item, { awaitPrimaryPreview: true })

  assert.deepEqual(calls.activations, ['same'])
  assert.deepEqual(calls.histories, [])
  assert.deepEqual(calls.previews, [])
})

test('recognizes only local document HTML formats and filenames', () => {
  assert.equal(isLocalHtmlDocument({
    source_provider: 'local_file',
    content_type: 'document',
    source_metadata: { file_format: 'xhtml' },
  }), true)
  assert.equal(isLocalHtmlDocument({
    source_provider: 'local_file',
    content_type: 'document',
    source_metadata: { file_name: 'archive.htm' },
  }), true)
  assert.equal(isLocalHtmlDocument({
    source_provider: 'rss',
    content_type: 'document',
    source_metadata: { file_name: 'remote.html' },
  }), false)
  assert.equal(isLocalHtmlDocument({
    source_provider: 'local_file',
    content_type: 'audio',
    source_metadata: { file_format: 'html' },
  }), false)
})
