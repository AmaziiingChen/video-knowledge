import { ref } from 'vue'

import { readableCharacterCount } from '../utils/reportReadingStats.js'
import { readingProgressFromScroll } from './readingProgress.js'

export function useReadingProgressController({
  activeContentTab,
  activeArticlePreviewFrame,
  reportReader,
  isArticleTab,
  supportsReadingProgress,
  isRemoteReadingVisible,
  readerTextForMetadata,
  scheduleFrame = (callback) => window.requestAnimationFrame(callback),
  cancelFrame = (frame) => window.cancelAnimationFrame(frame),
}) {
  const readingProgress = ref(0)
  const readingCharacterCount = ref(0)
  let refreshFrame = 0
  let frameDocument = null

  function handleReadingScroll(event) {
    refreshReadingProgress(event?.currentTarget)
  }

  function handleArticlePreviewFrameScroll() {
    refreshReadingProgress(frameDocument?.scrollingElement || null)
  }

  function detachReadingProgressFrame() {
    if (!frameDocument) return
    frameDocument.defaultView?.removeEventListener('scroll', handleArticlePreviewFrameScroll)
    frameDocument = null
  }

  function attachReadingProgressFrame(nextFrameDocument) {
    if (frameDocument === nextFrameDocument) return
    detachReadingProgressFrame()
    frameDocument = nextFrameDocument
    nextFrameDocument.defaultView?.addEventListener('scroll', handleArticlePreviewFrameScroll, { passive: true })
  }

  function activeReadingScrollRoot() {
    const tab = activeContentTab.value
    if (!tab || !supportsReadingProgress.value) return null
    if (isArticleTab(tab.id)) return activeArticlePreviewFrame.value?.contentDocument?.scrollingElement || null
    return reportReader.value
  }

  function refreshReadingProgress(scrollRoot = null) {
    const tab = activeContentTab.value
    if (!tab || !supportsReadingProgress.value) {
      readingProgress.value = 0
      readingCharacterCount.value = 0
      return
    }
    if (isRemoteReadingVisible()) return
    const root = scrollRoot || activeReadingScrollRoot()
    if (root) readingProgress.value = readingProgressFromScroll(root)
    readingCharacterCount.value = readableCharacterCount(readerTextForMetadata(tab.id))
  }

  function scheduleReadingProgressRefresh() {
    if (refreshFrame) cancelFrame(refreshFrame)
    refreshFrame = scheduleFrame(() => {
      refreshFrame = 0
      refreshReadingProgress()
    })
  }

  function resetReadingProgress() {
    detachReadingProgressFrame()
    readingProgress.value = 0
    readingCharacterCount.value = 0
  }

  function disposeReadingProgressController() {
    if (refreshFrame) cancelFrame(refreshFrame)
    refreshFrame = 0
    detachReadingProgressFrame()
  }

  return {
    readingProgress,
    readingCharacterCount,
    handleReadingScroll,
    attachReadingProgressFrame,
    refreshReadingProgress,
    scheduleReadingProgressRefresh,
    resetReadingProgress,
    disposeReadingProgressController,
  }
}
