import { ref, watch } from 'vue'
import { clearPreviewTextHighlights, highlightPreviewText } from '../utils/previewTextSearch.js'

export function usePreviewFindController({
  hasActiveContent = () => false,
  getMode = () => 'local',
  getLocalRoot = () => null,
  getFocusFallback = () => null,
  onLocalMatchActivated = () => {},
  refreshRemote = () => {},
  navigateRemote = () => {},
  clearRemote = () => {},
  windowObject = window,
  documentObject = document,
} = {}) {
  const previewFindOpen = ref(false)
  const previewFindQuery = ref('')
  const previewFindMatchCount = ref(0)
  const previewFindActiveIndex = ref(-1)
  const previewFindTruncated = ref(false)
  const previewFindFocusRequest = ref(0)
  let highlightRoot = null
  let matches = []
  let refreshFrame = 0
  let restoreFocus = null
  let disposed = false

  function resetResult() {
    previewFindMatchCount.value = 0
    previewFindActiveIndex.value = -1
    previewFindTruncated.value = false
  }

  function updatePreviewFindActiveMatch(index, { scroll = false } = {}) {
    for (const match of matches) match.classList.remove('preview-find-active')
    if (!matches.length) {
      previewFindActiveIndex.value = -1
      return
    }
    const nextIndex = (index + matches.length) % matches.length
    const match = matches[nextIndex]
    match.classList.add('preview-find-active')
    previewFindActiveIndex.value = nextIndex
    if (!scroll) return
    onLocalMatchActivated(match)
    const reducedMotion = windowObject.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    match.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center', inline: 'nearest' })
  }

  function clearPreviewFindHighlights() {
    if (highlightRoot) clearPreviewTextHighlights(highlightRoot)
    highlightRoot = null
    matches = []
    resetResult()
  }

  function setRemoteFindResult({ matchCount = 0, activeMatchOrdinal = 0 } = {}) {
    previewFindMatchCount.value = Number(matchCount) || 0
    previewFindActiveIndex.value = Math.max(-1, (Number(activeMatchOrdinal) || 0) - 1)
    previewFindTruncated.value = false
  }

  function updatePreviewFindQuery(query) {
    previewFindQuery.value = query
    const mode = getMode()
    if (previewFindOpen.value && mode !== 'local') {
      refreshRemote(mode, previewFindQuery.value.trim())
    }
  }

  function refreshPreviewFind() {
    refreshFrame = 0
    if (!previewFindOpen.value || disposed) return
    const mode = getMode()
    if (mode !== 'local') {
      clearPreviewFindHighlights()
      refreshRemote(mode, previewFindQuery.value.trim())
      return
    }
    const root = getLocalRoot()
    if (highlightRoot && highlightRoot !== root) clearPreviewTextHighlights(highlightRoot)
    highlightRoot = root
    const highlighted = highlightPreviewText(root, previewFindQuery.value)
    matches = highlighted.matches
    previewFindTruncated.value = highlighted.truncated
    previewFindMatchCount.value = matches.length
    updatePreviewFindActiveMatch(0)
  }

  function schedulePreviewFindRefresh() {
    if (!previewFindOpen.value || disposed) return
    if (refreshFrame) windowObject.cancelAnimationFrame(refreshFrame)
    refreshFrame = windowObject.requestAnimationFrame(refreshPreviewFind)
  }

  function openPreviewFind() {
    if (!hasActiveContent()) return
    if (!previewFindOpen.value) {
      const ElementClass = windowObject.HTMLElement
      restoreFocus = ElementClass && documentObject.activeElement instanceof ElementClass
        ? documentObject.activeElement
        : null
      const selectedText = windowObject.getSelection?.()?.toString().trim() || ''
      if (!previewFindQuery.value && selectedText && selectedText.length <= 120) {
        previewFindQuery.value = selectedText
      }
      previewFindOpen.value = true
    }
    previewFindFocusRequest.value += 1
    schedulePreviewFindRefresh()
  }

  function closePreviewFind() {
    previewFindOpen.value = false
    previewFindQuery.value = ''
    clearRemote({ clearSelection: true })
    clearPreviewFindHighlights()
    const target = restoreFocus?.isConnected ? restoreFocus : getFocusFallback()
    restoreFocus = null
    target?.focus?.({ preventScroll: true })
  }

  function navigatePreviewFind(direction) {
    const query = previewFindQuery.value.trim()
    if (!query) return
    const mode = getMode()
    if (mode !== 'local') {
      navigateRemote(mode, query, direction)
      return
    }
    if (!matches.length) return
    updatePreviewFindActiveMatch(previewFindActiveIndex.value + direction, { scroll: true })
  }

  const stopQueryWatch = watch(previewFindQuery, () => {
    if (getMode() !== 'local' && previewFindOpen.value) return
    schedulePreviewFindRefresh()
  })

  function disposePreviewFindController() {
    disposed = true
    stopQueryWatch()
    if (refreshFrame) windowObject.cancelAnimationFrame(refreshFrame)
    refreshFrame = 0
    clearPreviewFindHighlights()
  }

  return {
    clearPreviewFindHighlights,
    closePreviewFind,
    disposePreviewFindController,
    navigatePreviewFind,
    openPreviewFind,
    previewFindActiveIndex,
    previewFindFocusRequest,
    previewFindMatchCount,
    previewFindOpen,
    previewFindQuery,
    previewFindTruncated,
    schedulePreviewFindRefresh,
    setRemoteFindResult,
    updatePreviewFindQuery,
  }
}
