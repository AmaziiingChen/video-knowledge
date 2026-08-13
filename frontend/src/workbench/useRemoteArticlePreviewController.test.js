import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { REMOTE_OUTLINE_PREFIX } from './remoteOutlineBridge.js'
import { useRemoteArticlePreviewController } from './useRemoteArticlePreviewController.js'

function makeWebview(src) {
  const listeners = new Map()
  const calls = { css: [], scripts: [], finds: [], stops: [], reloads: 0 }
  return {
    src,
    calls,
    addEventListener(name, listener) { listeners.set(name, listener) },
    removeEventListener(name, listener) {
      if (listeners.get(name) === listener) listeners.delete(name)
    },
    emit(name, event) { listeners.get(name)?.(event) },
    async insertCSS(value) { calls.css.push(value) },
    async executeJavaScript(value) { calls.scripts.push(value) },
    findInPage(query, options) {
      calls.finds.push({ query, options })
      return calls.finds.length
    },
    stopFindInPage(action) { calls.stops.push(action) },
    reload() { calls.reloads += 1 },
  }
}

function createController({ tab, content, tabs = [tab], desktop = true } = {}) {
  const activeContentTab = ref(tab)
  const workspaceTabs = ref(tabs)
  const find = { query: '', open: false, results: [], resets: 0, refreshes: 0 }
  const selections = []
  const timers = []
  const controller = useRemoteArticlePreviewController({
    activeContentTab,
    workspaceTabs: () => workspaceTabs.value,
    contentForTab: () => content,
    isWechatArticleTab: () => content?.source_provider === 'wechat',
    localHtmlOriginalPageUrl: () => content?.source_metadata?.original_source_url || '',
    readerTextForMetadata: () => '用于计算阅读进度的本地快照',
    clearSelectedTextAction: () => {},
    handleWechatRemoteSelection: (payload) => selections.push(payload),
    isDesktopAvailable: () => desktop,
    onPreviewFindResult: (result) => find.results.push(result),
    resetPreviewFindResult: () => { find.resets += 1 },
    onPreviewFindRefresh: () => { find.refreshes += 1 },
    isPreviewFindOpen: () => find.open,
    getPreviewFindQuery: () => find.query,
    remoteScrollbarCss: () => 'remote-scrollbar-css',
    scheduleTimeout: (callback, delay) => {
      const timer = { callback, delay, cancelled: false }
      timers.push(timer)
      return timer
    },
    cancelTimeout: (timer) => { timer.cancelled = true },
  })
  return { activeContentTab, workspaceTabs, controller, find, selections, timers }
}

test('opens only a desktop WeChat original page and upgrades it after its matching webview loads', async () => {
  const tab = { id: 'content:wechat-1', content_item_id: 'wechat-1' }
  const content = { id: 'wechat-1', source_provider: 'wechat', source_url: 'https://mp.weixin.qq.com/s/example' }
  const { controller, timers } = createController({ tab, content })
  await nextTick()

  assert.equal(controller.canOpenWechatRemotePage.value, true)
  assert.deepEqual(controller.openedWechatRemotePages.value, [{
    contentItemId: 'wechat-1',
    sourceUrl: content.source_url,
    status: 'loading',
    visible: true,
    loadAttempt: 0,
  }])
  assert.equal(timers[0].delay, 15_000)

  const webview = makeWebview(content.source_url)
  controller.setWechatRemoteWebview('wechat-1', webview)
  await controller.handleWechatRemotePageLoaded('wechat-1', { target: webview })

  assert.equal(controller.activeWechatRemotePage.value.status, 'ready')
  assert.equal(controller.isWechatRemoteVisible.value, true)
  assert.equal(timers[0].cancelled, true)
  assert.equal(webview.calls.css[0], 'remote-scrollbar-css')
  assert.equal(webview.calls.scripts.length, 3)
})

test('never creates a guest page outside the desktop canonical WeChat origin', async () => {
  const tab = { id: 'content:wechat-1', content_item_id: 'wechat-1' }
  const content = { id: 'wechat-1', source_provider: 'wechat', source_url: 'https://example.com/article' }
  const invalidOrigin = createController({ tab, content, desktop: true })
  const browser = createController({
    tab,
    content: { ...content, source_url: 'https://mp.weixin.qq.com/s/example' },
    desktop: false,
  })
  await nextTick()

  assert.equal(invalidOrigin.controller.canOpenWechatRemotePage.value, false)
  assert.deepEqual(invalidOrigin.controller.openedWechatRemotePages.value, [])
  assert.equal(browser.controller.canOpenWechatRemotePage.value, false)
  assert.deepEqual(browser.controller.openedWechatRemotePages.value, [])
})

test('falls back to the local snapshot after the original page fails or times out', async () => {
  const tab = { id: 'content:wechat-1', content_item_id: 'wechat-1' }
  const content = { id: 'wechat-1', source_provider: 'wechat', source_url: 'https://mp.weixin.qq.com/s/example' }
  const { controller, timers } = createController({ tab, content })
  await nextTick()

  timers[0].callback()
  assert.equal(controller.activeWechatRemotePage.value.status, 'failed')
  assert.equal(controller.isWechatRemoteVisible.value, false)

  controller.toggleWechatRemotePage()
  assert.equal(controller.activeWechatRemotePage.value.status, 'loading')
  controller.handleWechatRemotePageFailed('wechat-1', { errorCode: -2 })
  assert.equal(controller.activeWechatRemotePage.value.visible, false)
})

test('keeps local HTML originals desktop-only and permanently falls back after a load failure', async () => {
  const tab = { id: 'content:local-1', content_item_id: 'local-1' }
  const content = {
    id: 'local-1',
    source_provider: 'local_file',
    source_metadata: { original_source_url: 'https://example.com/article' },
  }
  const desktop = createController({ tab, content, desktop: true })
  const browser = createController({ tab, content, desktop: false })
  await nextTick()

  assert.equal(desktop.controller.isLocalHtmlRemoteVisible.value, true)
  assert.equal(browser.controller.isLocalHtmlRemoteVisible.value, false)
  desktop.controller.handleLocalHtmlRemotePageFailed('content:local-1', { errorCode: -3 })
  assert.equal(desktop.controller.isLocalHtmlRemoteVisible.value, true)
  desktop.controller.handleLocalHtmlRemotePageFailed('content:local-1', { errorCode: -2 })
  assert.equal(desktop.controller.isLocalHtmlRemoteVisible.value, false)
})

test('routes remote find, outlines and selection through the active matching webview only', async () => {
  const tab = { id: 'content:wechat-1', content_item_id: 'wechat-1' }
  const content = { id: 'wechat-1', source_provider: 'wechat', source_url: 'https://mp.weixin.qq.com/s/example' }
  const { controller, find, selections } = createController({ tab, content })
  await nextTick()
  const webview = makeWebview(content.source_url)
  controller.setWechatRemoteWebview('wechat-1', webview)
  await controller.handleWechatRemotePageLoaded('wechat-1', { target: webview })

  find.query = '关键字'
  controller.refreshRemotePreviewFind()
  assert.equal(find.resets, 1)
  assert.deepEqual(webview.calls.finds[0], {
    query: '关键字', options: { forward: true, findNext: true, matchCase: false },
  })
  webview.emit('found-in-page', { result: { requestId: 1, matches: 3, activeMatchOrdinal: 2 } })
  assert.deepEqual(find.results, [{ matchCount: 3, activeMatchOrdinal: 2 }])

  controller.navigateRemotePreviewFind('wechat', '关键字', -1)
  assert.deepEqual(webview.calls.finds[1], {
    query: '关键字', options: { forward: false, findNext: false, matchCase: false },
  })
  controller.clearRemotePreviewFind({ clearSelection: true })
  assert.deepEqual(webview.calls.stops, ['clearSelection'])

  controller.handleWechatRemoteConsoleMessage('wechat-1', {
    target: webview,
    message: `${REMOTE_OUTLINE_PREFIX}${JSON.stringify({
      kind: 'outline',
      entries: [{ id: 'first', text: '第一节', level: 2 }],
      activeId: 'first',
    })}`,
  })
  assert.equal(controller.activeRemoteOutline.value.entries[0].text, '第一节')
  controller.handleWechatRemoteConsoleMessage('wechat-1', {
    target: webview,
    message: '__knowledgehub_wechat_selection__:' + JSON.stringify({
      kind: 'selection', text: '选中的文本', rect: { left: 1, top: 2, right: 3, bottom: 4 },
    }),
  })
  assert.equal(selections[0].selection.text, '选中的文本')
})

test('removes guest listeners and cancelled timers when the controller is disposed', async () => {
  const tab = { id: 'content:wechat-1', content_item_id: 'wechat-1' }
  const content = { id: 'wechat-1', source_provider: 'wechat', source_url: 'https://mp.weixin.qq.com/s/example' }
  const { controller, timers } = createController({ tab, content })
  await nextTick()
  const webview = makeWebview(content.source_url)
  controller.setWechatRemoteWebview('wechat-1', webview)
  controller.disposeRemoteArticlePreviewController()

  assert.equal(timers[0].cancelled, true)
  webview.emit('found-in-page', { result: { requestId: 1, matches: 1, activeMatchOrdinal: 1 } })
  assert.equal(controller.wechatRemoteWebviews.size, 0)
})
