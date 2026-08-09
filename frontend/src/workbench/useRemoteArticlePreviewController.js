import { computed, reactive, ref, watch } from 'vue'

import { readableCharacterCount } from '../utils/reportReadingStats.js'

import {
  parseWechatRemoteSelectionMessage,
  wechatRemoteSelectionBridgeScript,
} from './wechatRemoteSelection.js'
import {
  parseRemoteReadingProgressMessage,
  remoteReadingProgressBridgeScript,
} from './remoteReadingProgress.js'
import {
  parseRemoteOutlineMessage,
  remoteOutlineBridgeScript,
} from './remoteOutlineBridge.js'

const WECHAT_REMOTE_LOAD_TIMEOUT_MS = 15_000

function emptyOutline() {
  return { entries: [], activeId: '' }
}

function wechatRemoteScrollbarCss() {
  const muted = getComputedStyle(document.documentElement).getPropertyValue('--vk-muted').trim()
  return `
    * { scrollbar-width: thin; scrollbar-color: transparent transparent; }
    *::-webkit-scrollbar { width: 6px !important; height: 6px !important; }
    *::-webkit-scrollbar-track,
    *::-webkit-scrollbar-corner { background: transparent !important; }
    *::-webkit-scrollbar-thumb {
      border: 2px solid transparent !important;
      border-radius: 999px !important;
      background: transparent !important;
      background-clip: padding-box !important;
    }
    *:hover::-webkit-scrollbar-thumb {
      background: color-mix(in srgb, ${muted} 26%, transparent) !important;
      background-clip: padding-box !important;
    }
  `
}

export function useRemoteArticlePreviewController({
  activeContentTab,
  workspaceTabs,
  contentForTab,
  isWechatArticleTab,
  localHtmlOriginalPageUrl,
  readerTextForMetadata,
  clearSelectedTextAction,
  handleWechatRemoteSelection,
  isDesktopAvailable = () => Boolean(window.knowledgeHubDesktop),
  onPreviewFindResult = () => {},
  resetPreviewFindResult = () => {},
  onPreviewFindRefresh = () => {},
  isPreviewFindOpen = () => false,
  getPreviewFindQuery = () => '',
  scheduleTimeout = (callback, delay) => window.setTimeout(callback, delay),
  cancelTimeout = (timer) => window.clearTimeout(timer),
  remoteScrollbarCss = wechatRemoteScrollbarCss,
}) {
  const activeLocalHtmlRemoteWebview = ref(null)
  const wechatRemotePages = reactive({})
  const localHtmlRemoteFailures = reactive({})
  const remoteReadingProgressByKey = reactive({})
  const remoteOutlines = reactive({})
  const wechatRemoteWebviews = new Map()
  const wechatRemoteLoadTimers = new Map()
  const wechatRemoteFindListeners = new Map()
  const wechatRemoteFindRequestIds = new Map()
  let localHtmlRemoteFindRequestId = null

  const activeWechatContent = computed(() => {
    const tab = activeContentTab.value
    if (!tab || !isWechatArticleTab(tab.id)) return null
    return contentForTab(tab.id) || null
  })
  const canEmbedRemotePage = computed(() => Boolean(isDesktopAvailable()))
  const canOpenWechatRemotePage = computed(() => Boolean(
    canEmbedRemotePage.value
    && /^https:\/\/mp\.weixin\.qq\.com\//.test(String(activeWechatContent.value?.source_url || ''))
  ))
  const activeWechatRemotePage = computed(() => {
    const contentItemId = activeWechatContent.value?.id
    return contentItemId ? wechatRemotePages[contentItemId] || null : null
  })
  const openedWechatRemotePages = computed(() => Object.values(wechatRemotePages))
  const isWechatRemoteVisible = computed(() => (
    Boolean(activeWechatRemotePage.value && isWechatRemotePageVisible(activeWechatRemotePage.value))
  ))
  const activeLocalHtmlRemotePage = computed(() => {
    const tabId = activeContentTab.value?.id || ''
    const sourceUrl = localHtmlOriginalPageUrl(tabId)
    if (!canEmbedRemotePage.value || !tabId || !sourceUrl || localHtmlRemoteFailures[tabId]) return null
    return { contentItemId: tabId, sourceUrl }
  })
  const isLocalHtmlRemoteVisible = computed(() => Boolean(activeLocalHtmlRemotePage.value))
  const activeRemoteOutlineKey = computed(() => {
    if (isWechatRemoteVisible.value) return `wechat:${activeWechatContent.value?.id || ''}`
    if (isLocalHtmlRemoteVisible.value) return `local-html:${activeContentTab.value?.id || ''}`
    return ''
  })
  const activeRemoteOutline = computed(() => (
    remoteOutlines[activeRemoteOutlineKey.value] || emptyOutline()
  ))
  const activeRemoteOutlineVersion = computed(() => (
    `${activeRemoteOutlineKey.value}:${activeRemoteOutline.value.entries.map((entry) => entry.id).join('|')}`
  ))
  const activeRemoteOutlineWebview = computed(() => {
    if (isWechatRemoteVisible.value) return wechatRemoteWebviews.get(activeWechatContent.value?.id) || null
    if (isLocalHtmlRemoteVisible.value) return activeLocalHtmlRemoteWebview.value || null
    return null
  })
  const activeRemoteReadingProgress = computed(() => {
    const key = activeRemoteReadingProgressKey()
    return key ? remoteReadingProgressByKey[key] || null : null
  })
  const wechatRemoteActionLabel = computed(() => {
    if (isWechatRemoteVisible.value) return '查看缓存正文'
    if (activeWechatRemotePage.value?.status === 'ready') return '在软件内打开原文'
    if (activeWechatRemotePage.value?.status === 'failed') return '重新加载软件内原文'
    if (activeWechatRemotePage.value?.status === 'loading') return '正在打开原文'
    return '在软件内打开原文'
  })

  function activeRemoteReadingProgressKey() {
    if (isWechatRemoteVisible.value) return `wechat:${activeWechatContent.value?.id || ''}`
    if (isLocalHtmlRemoteVisible.value) return `local-html:${activeContentTab.value?.id || ''}`
    return ''
  }

  function ensureWechatRemotePageOpen() {
    const content = activeWechatContent.value
    if (!content || !canOpenWechatRemotePage.value || wechatRemotePages[content.id]) return
    wechatRemotePages[content.id] = {
      contentItemId: content.id,
      sourceUrl: content.source_url,
      status: 'loading',
      visible: true,
      loadAttempt: 0,
    }
    scheduleWechatRemoteLoadTimeout(content.id)
  }

  function clearWechatRemoteLoadTimer(contentItemId) {
    const timer = wechatRemoteLoadTimers.get(contentItemId)
    if (!timer) return
    cancelTimeout(timer)
    wechatRemoteLoadTimers.delete(contentItemId)
  }

  function scheduleWechatRemoteLoadTimeout(contentItemId) {
    clearWechatRemoteLoadTimer(contentItemId)
    const timer = scheduleTimeout(() => {
      const page = wechatRemotePages[contentItemId]
      if (!page || page.status !== 'loading') return
      page.status = 'failed'
      page.visible = false
    }, WECHAT_REMOTE_LOAD_TIMEOUT_MS)
    wechatRemoteLoadTimers.set(contentItemId, timer)
  }

  function setWechatRemoteWebview(contentItemId, webview) {
    const previous = wechatRemoteWebviews.get(contentItemId)
    const previousListener = wechatRemoteFindListeners.get(contentItemId)
    if (previous && previousListener) previous.removeEventListener?.('found-in-page', previousListener)
    wechatRemoteFindListeners.delete(contentItemId)
    if (!webview) {
      wechatRemoteWebviews.delete(contentItemId)
      return
    }
    const listener = (event) => handleWechatRemoteFoundInPage(contentItemId, event)
    webview.addEventListener?.('found-in-page', listener)
    wechatRemoteFindListeners.set(contentItemId, listener)
    wechatRemoteWebviews.set(contentItemId, webview)
  }

  function isWechatRemotePageVisible(page) {
    return Boolean(
      page?.visible
      && page.status === 'ready'
      && page.contentItemId === activeWechatContent.value?.id
    )
  }

  async function handleWechatRemotePageLoaded(contentItemId, event) {
    const page = wechatRemotePages[contentItemId]
    const webview = event?.target || wechatRemoteWebviews.get(contentItemId)
    if (!page || !webview || page.sourceUrl !== webview.src) return
    try {
      await webview.insertCSS(remoteScrollbarCss())
    } catch {
      // The original page remains readable when a particular guest page rejects injected CSS.
    }
    try {
      await webview.executeJavaScript(wechatRemoteSelectionBridgeScript())
    } catch {
      // The page remains readable even when its guest renderer rejects the optional selection bridge.
    }
    try {
      const tabId = workspaceTabs().find((tab) => (
        String(tab.content_item_id || '') === String(contentItemId)
      ))?.id || activeContentTab.value?.id
      await webview.executeJavaScript(remoteReadingProgressBridgeScript(
        readableCharacterCount(readerTextForMetadata(tabId))
      ))
    } catch {
      // Progress is supplemental; do not let it block the original-page preview.
    }
    try {
      await webview.executeJavaScript(remoteOutlineBridgeScript())
    } catch {
      // A source page without readable headings simply has no outline rail.
    }
    if (wechatRemoteWebviews.get(contentItemId) !== webview) return
    clearWechatRemoteLoadTimer(contentItemId)
    page.status = 'ready'
    if (isPreviewFindOpen()) onPreviewFindRefresh()
  }

  function handleWechatRemoteFoundInPage(contentItemId, event) {
    const webview = wechatRemoteWebviews.get(contentItemId)
    const result = event?.result
    if (!result || !webview || !isWechatRemoteVisible.value) return
    if (result.requestId !== wechatRemoteFindRequestIds.get(contentItemId)) return
    onPreviewFindResult({
      matchCount: result.matches,
      activeMatchOrdinal: result.activeMatchOrdinal,
    })
  }

  function handleWechatRemoteConsoleMessage(contentItemId, event) {
    const webview = wechatRemoteWebviews.get(contentItemId)
    if (!webview || event?.target !== webview || !isWechatRemotePageVisible(wechatRemotePages[contentItemId])) return
    const outline = parseRemoteOutlineMessage(event?.message)
    if (outline) {
      applyRemoteOutlineMessage(`wechat:${contentItemId}`, outline)
      return
    }
    const progress = parseRemoteReadingProgressMessage(event?.message)
    if (progress) {
      remoteReadingProgressByKey[`wechat:${contentItemId}`] = progress
      return
    }
    const selection = parseWechatRemoteSelectionMessage(event?.message)
    if (!selection) return
    handleWechatRemoteSelection({ contentItemId, webview, selection })
  }

  function handleWechatRemotePageFailed(contentItemId, event) {
    if (event?.target && event.target !== wechatRemoteWebviews.get(contentItemId)) return
    if (Number(event?.errorCode) === -3) return
    const page = wechatRemotePages[contentItemId]
    if (!page) return
    clearWechatRemoteLoadTimer(contentItemId)
    page.status = 'failed'
    page.visible = false
  }

  function toggleWechatRemotePage() {
    const content = activeWechatContent.value
    if (!content || !canOpenWechatRemotePage.value) return
    clearSelectedTextAction()
    const existing = wechatRemotePages[content.id]
    if (!existing) {
      wechatRemotePages[content.id] = {
        contentItemId: content.id,
        sourceUrl: content.source_url,
        status: 'loading',
        visible: true,
        loadAttempt: 0,
      }
      scheduleWechatRemoteLoadTimeout(content.id)
      return
    }
    if (existing.status === 'loading') return
    if (existing.status === 'failed') {
      reloadWechatRemotePage(existing)
      return
    }
    existing.visible = !existing.visible
  }

  function reloadWechatRemotePage(page) {
    if (!page?.sourceUrl) return
    page.visible = true
    page.status = 'loading'
    scheduleWechatRemoteLoadTimeout(page.contentItemId)
    const webview = wechatRemoteWebviews.get(page.contentItemId)
    if (webview && typeof webview.reload === 'function') {
      webview.reload()
      return
    }
    page.loadAttempt += 1
  }

  function handleLocalHtmlRemotePageFailed(contentItemId, event) {
    if (Number(event?.errorCode) === -3) return
    localHtmlRemoteFailures[contentItemId] = true
  }

  async function handleLocalHtmlRemotePageLoaded(event) {
    const webview = event?.target || activeLocalHtmlRemoteWebview.value
    try {
      await webview?.executeJavaScript?.(remoteReadingProgressBridgeScript(
        readableCharacterCount(readerTextForMetadata(activeContentTab.value?.id))
      ))
    } catch {
      // The original source remains usable if the optional progress bridge is refused.
    }
    try {
      await webview?.executeJavaScript?.(remoteOutlineBridgeScript())
    } catch {
      // A source page without readable headings simply has no outline rail.
    }
    if (isPreviewFindOpen()) onPreviewFindRefresh()
  }

  function handleLocalHtmlRemoteConsoleMessage(contentItemId, event) {
    const webview = activeLocalHtmlRemoteWebview.value
    if (!webview || event?.target !== webview || !isLocalHtmlRemoteVisible.value) return
    const outline = parseRemoteOutlineMessage(event?.message)
    if (outline && String(contentItemId) === String(activeContentTab.value?.id || '')) {
      applyRemoteOutlineMessage(`local-html:${contentItemId}`, outline)
      return
    }
    const progress = parseRemoteReadingProgressMessage(event?.message)
    if (!progress || String(contentItemId) !== String(activeContentTab.value?.id || '')) return
    remoteReadingProgressByKey[`local-html:${contentItemId}`] = progress
  }

  function handleLocalHtmlRemoteFoundInPage(event) {
    const result = event?.result
    if (!result || result.requestId !== localHtmlRemoteFindRequestId) return
    onPreviewFindResult({
      matchCount: result.matches,
      activeMatchOrdinal: result.activeMatchOrdinal,
    })
  }

  function applyRemoteOutlineMessage(key, message) {
    if (message.kind === 'outline') {
      remoteOutlines[key] = {
        entries: message.entries,
        activeId: message.activeId,
      }
      return
    }
    if (message.kind === 'active' && remoteOutlines[key]) {
      remoteOutlines[key].activeId = message.activeId
    }
  }

  function scrollToRemoteOutlineEntry(entry) {
    const webview = activeRemoteOutlineWebview.value
    const id = String(entry?.id || '')
    if (!webview?.executeJavaScript || !id) return
    void webview.executeJavaScript(
      `window.__knowledgeHubRemoteOutlineScrollTo?.(${JSON.stringify(id)})`
    ).catch(() => {})
  }

  function previewFindMode() {
    if (isWechatRemoteVisible.value) return 'wechat'
    if (isLocalHtmlRemoteVisible.value) return 'local-html'
    return 'local'
  }

  function refreshRemotePreviewFind() {
    if (previewFindMode() === 'wechat') refreshWechatRemoteFind()
    else if (previewFindMode() === 'local-html') refreshLocalHtmlRemoteFind()
  }

  function clearRemotePreviewFind({ clearSelection = false } = {}) {
    clearWechatRemoteFind({ clearSelection })
    clearLocalHtmlRemoteFind({ clearSelection })
  }

  function navigateRemotePreviewFind(mode, query, direction) {
    if (mode === 'wechat') {
      const contentItemId = activeWechatContent.value?.id
      const webview = contentItemId ? wechatRemoteWebviews.get(contentItemId) : null
      if (!contentItemId || !webview?.findInPage) return
      try {
        wechatRemoteFindRequestIds.set(contentItemId, webview.findInPage(query, {
          forward: direction >= 0,
          findNext: false,
          matchCase: false,
        }))
      } catch {
        wechatRemoteFindRequestIds.delete(contentItemId)
      }
      return
    }
    if (mode !== 'local-html') return
    const webview = activeLocalHtmlRemoteWebview.value
    if (!webview?.findInPage) return
    try {
      localHtmlRemoteFindRequestId = webview.findInPage(query, {
        forward: direction >= 0,
        findNext: false,
        matchCase: false,
      })
    } catch {
      localHtmlRemoteFindRequestId = null
    }
  }

  function clearLocalHtmlRemoteFind({ clearSelection = false } = {}) {
    const webview = activeLocalHtmlRemoteWebview.value
    if (!webview?.stopFindInPage) return
    try {
      webview.stopFindInPage(clearSelection ? 'clearSelection' : 'keepSelection')
    } catch {
      // The remote page may have just been detached while tabs are switching.
    }
    localHtmlRemoteFindRequestId = null
  }

  function clearWechatRemoteFind({ clearSelection = false } = {}) {
    const contentItemId = activeWechatContent.value?.id
    const webview = contentItemId ? wechatRemoteWebviews.get(contentItemId) : null
    if (!contentItemId || !webview?.stopFindInPage) return
    try {
      webview.stopFindInPage(clearSelection ? 'clearSelection' : 'keepSelection')
    } catch {
      // The original-page preview may have just been detached while tabs are switching.
    }
    wechatRemoteFindRequestIds.delete(contentItemId)
  }

  function refreshLocalHtmlRemoteFind() {
    const query = String(getPreviewFindQuery()).trim()
    const webview = activeLocalHtmlRemoteWebview.value
    resetPreviewFindResult()
    if (!query || !webview?.findInPage) {
      clearLocalHtmlRemoteFind({ clearSelection: !query })
      return
    }
    try {
      localHtmlRemoteFindRequestId = webview.findInPage(query, {
        forward: true,
        findNext: true,
        matchCase: false,
      })
    } catch {
      localHtmlRemoteFindRequestId = null
    }
  }

  function refreshWechatRemoteFind() {
    const query = String(getPreviewFindQuery()).trim()
    const contentItemId = activeWechatContent.value?.id
    const webview = contentItemId ? wechatRemoteWebviews.get(contentItemId) : null
    resetPreviewFindResult()
    if (!query || !contentItemId || !webview?.findInPage) {
      clearWechatRemoteFind({ clearSelection: !query })
      return
    }
    try {
      wechatRemoteFindRequestIds.set(contentItemId, webview.findInPage(query, {
        forward: true,
        findNext: true,
        matchCase: false,
      }))
    } catch {
      wechatRemoteFindRequestIds.delete(contentItemId)
    }
  }

  function disposeRemoteArticlePreviewController() {
    for (const contentItemId of wechatRemoteLoadTimers.keys()) clearWechatRemoteLoadTimer(contentItemId)
    for (const contentItemId of wechatRemoteWebviews.keys()) setWechatRemoteWebview(contentItemId, null)
    wechatRemoteWebviews.clear()
    wechatRemoteFindRequestIds.clear()
  }

  watch(
    () => [activeWechatContent.value?.id || '', activeWechatContent.value?.source_url || ''],
    () => ensureWechatRemotePageOpen(),
    { immediate: true },
  )

  watch(
    () => workspaceTabs().map((tab) => tab.content_item_id || '').join('|'),
    () => {
      const tabs = workspaceTabs()
      const openContentIds = new Set(tabs.map((tab) => tab.content_item_id).filter(Boolean))
      const openTabIds = new Set(tabs.map((tab) => String(tab.id || '')).filter(Boolean))
      for (const contentItemId of Object.keys(wechatRemotePages)) {
        if (openContentIds.has(contentItemId)) continue
        clearWechatRemoteLoadTimer(contentItemId)
        delete wechatRemotePages[contentItemId]
        setWechatRemoteWebview(contentItemId, null)
        wechatRemoteFindRequestIds.delete(contentItemId)
        delete remoteReadingProgressByKey[`wechat:${contentItemId}`]
        delete remoteOutlines[`wechat:${contentItemId}`]
      }
      for (const key of Object.keys(remoteReadingProgressByKey)) {
        if (!key.startsWith('local-html:')) continue
        if (!openTabIds.has(key.slice('local-html:'.length))) delete remoteReadingProgressByKey[key]
      }
      for (const key of Object.keys(remoteOutlines)) {
        if (!key.startsWith('local-html:')) continue
        if (!openTabIds.has(key.slice('local-html:'.length))) delete remoteOutlines[key]
      }
    },
  )

  return {
    activeLocalHtmlRemotePage,
    activeLocalHtmlRemoteWebview,
    activeRemoteOutline,
    activeRemoteOutlineKey,
    activeRemoteOutlineVersion,
    activeRemoteOutlineWebview,
    activeRemoteReadingProgress,
    activeWechatContent,
    activeWechatRemotePage,
    canOpenWechatRemotePage,
    disposeRemoteArticlePreviewController,
    handleLocalHtmlRemoteConsoleMessage,
    handleLocalHtmlRemoteFoundInPage,
    handleLocalHtmlRemotePageFailed,
    handleLocalHtmlRemotePageLoaded,
    handleWechatRemoteConsoleMessage,
    handleWechatRemotePageFailed,
    handleWechatRemotePageLoaded,
    isLocalHtmlRemoteVisible,
    isWechatRemotePageVisible,
    isWechatRemoteVisible,
    navigateRemotePreviewFind,
    openedWechatRemotePages,
    previewFindMode,
    refreshRemotePreviewFind,
    clearRemotePreviewFind,
    scrollToRemoteOutlineEntry,
    setWechatRemoteWebview,
    toggleWechatRemotePage,
    wechatRemoteActionLabel,
    wechatRemoteWebviews,
  }
}
