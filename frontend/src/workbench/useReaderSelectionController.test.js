import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useReaderSelectionController } from './useReaderSelectionController.js'

function eventDocument() {
  const listeners = new Map()
  return {
    listeners,
    defaultView: { getSelection: () => null },
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: (name) => listeners.delete(name),
  }
}

function createController() {
  const documentRoot = eventDocument()
  const asked = []
  const remoteWebviews = new Map()
  const controller = useReaderSelectionController({
    activeContentTab: ref({ id: 'content:1', title: '标签标题' }),
    activeArticlePreviewFrame: ref(null),
    contentHero: ref(null),
    contentForTab: () => ({ id: '1', title: '内容标题' }),
    isWechatRemoteVisible: () => false,
    wechatRemoteWebviews: remoteWebviews,
    onAsk: (selection) => asked.push(selection),
    getDocument: () => documentRoot,
    getWindow: () => ({ innerWidth: 360, innerHeight: 240, getSelection: () => ({ removeAllRanges: () => {} }) }),
  })
  return { controller, documentRoot, asked, remoteWebviews }
}

test('shows only the active WeChat page selection and clears its action', () => {
  const { controller } = createController()
  const webview = { getBoundingClientRect: () => ({ left: 40, top: 50 }) }
  const selection = { text: '远程选中的句子', rect: { left: 5, top: 8, right: 85, bottom: 24 } }

  controller.handleWechatRemoteSelection({ contentItemId: 'other', webview, selection })
  assert.equal(controller.selectedTextAction.value, null)

  controller.handleWechatRemoteSelection({ contentItemId: '1', webview, selection })
  assert.deepEqual(controller.selectedTextAction.value, {
    text: '远程选中的句子',
    contentItemId: '1',
    contentTitle: '内容标题',
    source: 'wechat-remote',
    rect: { left: 45, top: 58, right: 125, bottom: 74, width: 80, height: 16 },
  })
  assert.equal(controller.selectedTextActionStyle.value.left, '61px')
  assert.equal(controller.selectedTextActionStyle.value.top, '18px')

  controller.handleWechatRemoteSelection({ contentItemId: '1', webview, selection: { kind: 'clear' } })
  assert.equal(controller.selectedTextAction.value, null)
})

test('forwards the quote and disposes root and iframe listeners', async () => {
  const { controller, documentRoot, asked, remoteWebviews } = createController()
  const remoteCalls = []
  const webview = {
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    executeJavaScript: (code) => {
      remoteCalls.push(code)
      return Promise.resolve()
    },
  }
  remoteWebviews.set('1', webview)
  controller.mountReaderSelectionController()
  assert.deepEqual([...documentRoot.listeners.keys()].sort(), ['pointercancel', 'pointerdown', 'pointerup', 'selectionchange'])

  const frameDocument = eventDocument()
  controller.attachArticlePreviewSelectionFrame(frameDocument)
  assert.deepEqual([...frameDocument.listeners.keys()].sort(), ['pointercancel', 'pointerdown', 'pointerup', 'selectionchange'])

  controller.handleWechatRemoteSelection({
    contentItemId: '1',
    webview,
    selection: { text: '可用于提问', rect: { left: 1, top: 1, right: 40, bottom: 20 } },
  })
  controller.askAboutSelectedText()
  await Promise.resolve()
  assert.deepEqual(asked, [{ contentItemId: '1', contentTitle: '内容标题', text: '可用于提问' }])
  assert.deepEqual(remoteCalls, ['window.getSelection?.().removeAllRanges()'])
  assert.equal(controller.selectedTextAction.value, null)

  controller.disposeReaderSelectionController()
  assert.equal(documentRoot.listeners.size, 0)
  assert.equal(frameDocument.listeners.size, 0)
})
