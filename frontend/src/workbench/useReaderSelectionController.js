import { computed, ref } from 'vue'

import { shouldClaimReaderFocus } from './readerPointerFocus.js'

export function useReaderSelectionController({
  activeContentTab,
  activeArticlePreviewFrame,
  contentHero,
  contentForTab,
  isWechatRemoteVisible,
  wechatRemoteWebviews,
  onAsk,
  getDocument = () => document,
  getWindow = () => window,
  scheduleFrame = (callback) => window.requestAnimationFrame(callback),
  cancelFrame = (frame) => window.cancelAnimationFrame(frame),
}) {
  const selectedTextAction = ref(null)
  let frameDocument = null
  let pointerIsDown = false
  let revealFrame = 0

  const selectedTextActionStyle = computed(() => {
    const rect = selectedTextAction.value?.rect
    if (!rect) return {}
    const viewport = getWindow()
    const actionWidth = 64
    const actionHeight = 32
    const horizontalMargin = 10
    const opensAbove = rect.top - actionHeight - 8 >= horizontalMargin
    const left = Math.max(horizontalMargin, Math.min(viewport.innerWidth - actionWidth - horizontalMargin, rect.right - actionWidth))
    const top = opensAbove ? rect.top - actionHeight - 8 : Math.min(viewport.innerHeight - actionHeight - horizontalMargin, rect.bottom + 8)
    return {
      left: `${Math.round(left)}px`,
      top: `${Math.round(top)}px`,
      '--reader-selection-origin': opensAbove ? 'center bottom' : 'center top',
      '--reader-selection-tail-top': opensAbove ? 'auto' : '-4px',
      '--reader-selection-tail-bottom': opensAbove ? '-4px' : 'auto',
    }
  })

  function clearSelectedTextAction() {
    selectedTextAction.value = null
  }

  function selectionBelongsToReader(range, ownerDocument) {
    const container = range.commonAncestorContainer
    const element = container?.nodeType === Node.ELEMENT_NODE ? container : container?.parentElement
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false
    if (ownerDocument && activeArticlePreviewFrame.value?.contentDocument === ownerDocument) return ownerDocument.body.contains(element)
    return Boolean(element.closest('.report-markdown, .article-preview-body, .transcript-timeline'))
  }

  function captureReadableSelection(selection, ownerDocument) {
    if (!selection || selection.isCollapsed || !selection.rangeCount) {
      clearSelectedTextAction()
      return
    }
    const range = selection.getRangeAt(0)
    const text = String(selection.toString() || '').trim().replace(/\s+/gu, ' ').trim()
    const tab = activeContentTab.value
    const content = tab ? contentForTab(tab.id) : null
    if (!text || !content?.id || text.length < 2 || !selectionBelongsToReader(range, ownerDocument)) {
      clearSelectedTextAction()
      return
    }
    const rangeRect = range.getBoundingClientRect()
    if (!rangeRect.width && !rangeRect.height) {
      clearSelectedTextAction()
      return
    }
    const frame = activeArticlePreviewFrame.value
    const isFrameSelection = ownerDocument && frame?.contentDocument === ownerDocument
    const frameRect = isFrameSelection ? frame.getBoundingClientRect() : null
    selectedTextAction.value = {
      text: text.slice(0, 12000),
      contentItemId: String(content.id),
      contentTitle: content.title || tab?.title || '当前内容',
      rect: isFrameSelection && frameRect
        ? {
            left: frameRect.left + rangeRect.left,
            top: frameRect.top + rangeRect.top,
            width: rangeRect.width,
            height: rangeRect.height,
            right: frameRect.left + rangeRect.right,
            bottom: frameRect.top + rangeRect.bottom,
          }
        : rangeRect,
    }
  }

  function handleDocumentSelectionChange() {
    if (isWechatRemoteVisible() || pointerIsDown) {
      clearSelectedTextAction()
      return
    }
    const ownerDocument = getDocument()
    captureReadableSelection(getWindow().getSelection?.(), ownerDocument)
  }

  function handleArticlePreviewSelectionChange(event) {
    const ownerDocument = event?.target
    if (pointerIsDown) {
      clearSelectedTextAction()
      return
    }
    captureReadableSelection(ownerDocument?.defaultView?.getSelection?.(), ownerDocument)
  }

  function handleSelectedTextPointerDown(event) {
    // The floating action is teleported to body. Preserve the captured quote
    // until its button click can hand it to the assistant.
    if (typeof Element !== 'undefined' && event?.target instanceof Element && event.target.closest('.reader-selection-ask')) return
    if (shouldClaimReaderFocus(event?.target)) contentHero.value?.focus({ preventScroll: true })
    pointerIsDown = true
    if (revealFrame) {
      cancelFrame(revealFrame)
      revealFrame = 0
    }
    clearSelectedTextAction()
  }

  function handleSelectedTextPointerUp(event) {
    pointerIsDown = false
    const ownerDocument = event?.currentTarget?.defaultView ? event.currentTarget : getDocument()
    if (revealFrame) cancelFrame(revealFrame)
    revealFrame = scheduleFrame(() => {
      revealFrame = 0
      if (!isWechatRemoteVisible()) captureReadableSelection(ownerDocument.defaultView?.getSelection?.(), ownerDocument)
    })
  }

  function handleSelectedTextPointerCancel() {
    pointerIsDown = false
    clearSelectedTextAction()
  }

  function detachArticlePreviewSelectionFrame() {
    if (!frameDocument) return
    frameDocument.removeEventListener('selectionchange', handleArticlePreviewSelectionChange)
    frameDocument.removeEventListener('pointerdown', handleSelectedTextPointerDown, true)
    frameDocument.removeEventListener('pointerup', handleSelectedTextPointerUp, true)
    frameDocument.removeEventListener('pointercancel', handleSelectedTextPointerCancel, true)
    frameDocument = null
  }

  function attachArticlePreviewSelectionFrame(nextFrameDocument) {
    if (frameDocument === nextFrameDocument) return
    detachArticlePreviewSelectionFrame()
    frameDocument = nextFrameDocument
    nextFrameDocument.addEventListener('selectionchange', handleArticlePreviewSelectionChange)
    nextFrameDocument.addEventListener('pointerdown', handleSelectedTextPointerDown, true)
    nextFrameDocument.addEventListener('pointerup', handleSelectedTextPointerUp, true)
    nextFrameDocument.addEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  }

  function handleWechatRemoteSelection({ contentItemId, webview, selection }) {
    if (selection?.kind === 'clear') {
      clearSelectedTextAction()
      return
    }
    if (!selection || !webview) return
    const tab = activeContentTab.value
    const content = tab ? contentForTab(tab.id) : null
    if (!content?.id || String(content.id) !== String(contentItemId)) return
    const webviewRect = webview.getBoundingClientRect?.()
    if (!webviewRect) return
    selectedTextAction.value = {
      text: selection.text,
      contentItemId: String(content.id),
      contentTitle: content.title || tab.title || '当前内容',
      source: 'wechat-remote',
      rect: {
        left: webviewRect.left + selection.rect.left,
        top: webviewRect.top + selection.rect.top,
        right: webviewRect.left + selection.rect.right,
        bottom: webviewRect.top + selection.rect.bottom,
        width: selection.rect.right - selection.rect.left,
        height: selection.rect.bottom - selection.rect.top,
      },
    }
  }

  function askAboutSelectedText() {
    const selection = selectedTextAction.value
    if (!selection) return
    onAsk({
      contentItemId: selection.contentItemId,
      contentTitle: selection.contentTitle,
      text: selection.text,
    })
    getWindow().getSelection?.()?.removeAllRanges()
    activeArticlePreviewFrame.value?.contentDocument?.defaultView?.getSelection?.()?.removeAllRanges()
    if (selection.source === 'wechat-remote') {
      const webview = wechatRemoteWebviews.get(selection.contentItemId)
      void webview?.executeJavaScript?.('window.getSelection?.().removeAllRanges()').catch(() => {})
    }
    clearSelectedTextAction()
  }

  function mountReaderSelectionController() {
    const ownerDocument = getDocument()
    ownerDocument.addEventListener('selectionchange', handleDocumentSelectionChange)
    ownerDocument.addEventListener('pointerdown', handleSelectedTextPointerDown, true)
    ownerDocument.addEventListener('pointerup', handleSelectedTextPointerUp, true)
    ownerDocument.addEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  }

  function disposeReaderSelectionController() {
    if (revealFrame) cancelFrame(revealFrame)
    revealFrame = 0
    const ownerDocument = getDocument()
    ownerDocument.removeEventListener('selectionchange', handleDocumentSelectionChange)
    ownerDocument.removeEventListener('pointerdown', handleSelectedTextPointerDown, true)
    ownerDocument.removeEventListener('pointerup', handleSelectedTextPointerUp, true)
    ownerDocument.removeEventListener('pointercancel', handleSelectedTextPointerCancel, true)
    detachArticlePreviewSelectionFrame()
  }

  return {
    selectedTextAction,
    selectedTextActionStyle,
    askAboutSelectedText,
    attachArticlePreviewSelectionFrame,
    clearSelectedTextAction,
    disposeReaderSelectionController,
    handleWechatRemoteSelection,
    mountReaderSelectionController,
  }
}
