import assert from 'node:assert/strict'
import test from 'node:test'
import { computed, ref } from 'vue'

import { useReadingProgressController } from './useReadingProgressController.js'

function createController({ activeTabId = 'report:1', remote = false } = {}) {
  const activeContentTab = ref({ id: activeTabId })
  const reportReader = ref({ scrollTop: 200, scrollHeight: 1000, clientHeight: 200 })
  const activeArticlePreviewFrame = ref(null)
  const frames = new Map()
  const cancelled = []
  let nextFrame = 0
  const controller = useReadingProgressController({
    activeContentTab,
    activeArticlePreviewFrame,
    reportReader,
    isArticleTab: (tabId) => tabId.startsWith('article:'),
    supportsReadingProgress: computed(() => true),
    isRemoteReadingVisible: () => remote,
    readerTextForMetadata: () => '阅读进度文本',
    scheduleFrame: (callback) => {
      const id = ++nextFrame
      frames.set(id, callback)
      return id
    },
    cancelFrame: (id) => {
      cancelled.push(id)
      frames.delete(id)
    },
  })
  return { controller, activeContentTab, activeArticlePreviewFrame, frames, cancelled }
}

test('derives local reader progress and ignores remote-reader DOM state', () => {
  const { controller } = createController()
  controller.refreshReadingProgress()
  assert.equal(controller.readingProgress.value, 25)
  assert.equal(controller.readingCharacterCount.value, 6)

  const remote = createController({ remote: true })
  remote.controller.refreshReadingProgress()
  assert.equal(remote.controller.readingProgress.value, 0)
  assert.equal(remote.controller.readingCharacterCount.value, 0)
})

test('attaches one iframe scroll listener and disposes scheduled work', () => {
  const { controller, activeContentTab, activeArticlePreviewFrame, frames, cancelled } = createController({ activeTabId: 'article:1' })
  const listeners = new Map()
  const frameDocument = {
    scrollingElement: { scrollTop: 400, scrollHeight: 1000, clientHeight: 200 },
    defaultView: {
      addEventListener: (name, listener) => listeners.set(name, listener),
      removeEventListener: (name) => listeners.delete(name),
    },
  }
  activeArticlePreviewFrame.value = { contentDocument: frameDocument }
  controller.attachReadingProgressFrame(frameDocument)
  listeners.get('scroll')()
  assert.equal(controller.readingProgress.value, 50)

  controller.scheduleReadingProgressRefresh()
  controller.scheduleReadingProgressRefresh()
  assert.deepEqual(cancelled, [1])
  frames.get(2)()
  assert.equal(controller.readingCharacterCount.value, 6)

  activeContentTab.value = null
  controller.refreshReadingProgress()
  assert.equal(controller.readingProgress.value, 0)
  controller.disposeReadingProgressController()
  assert.equal(listeners.has('scroll'), false)
})
