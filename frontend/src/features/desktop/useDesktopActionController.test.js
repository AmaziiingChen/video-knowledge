import assert from 'node:assert/strict'
import test from 'node:test'

import { useDesktopActionController } from './useDesktopActionController.js'

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function createController({ request = {}, bridge = {}, confirm = async () => {} } = {}) {
  const messages = []
  const requests = []
  const copied = []
  const opened = []
  const revealed = []
  const windows = []
  const desktopBridge = {
    copyText: async (value) => copied.push(value),
    openExternal: async (value) => opened.push(value),
    revealPath: async (value) => revealed.push(value),
    ...bridge,
  }
  const controller = useDesktopActionController({
    request: {
      get: async (...args) => {
        requests.push(['get', ...args])
        return { data: {} }
      },
      post: async (...args) => {
        requests.push(['post', ...args])
        return { data: {} }
      },
      ...request,
    },
    apiBase: 'http://api.test',
    notify: {
      success: (message) => messages.push(['success', message]),
      warning: (message) => messages.push(['warning', message]),
      error: (message) => messages.push(['error', message]),
    },
    confirm,
    getDesktopBridge: () => desktopBridge,
    writeClipboard: async (value) => copied.push(`browser:${value}`),
    openWindow: (...args) => windows.push(args),
  })
  return { controller, messages, requests, copied, opened, revealed, windows, desktopBridge }
}

test('copies through the desktop bridge and preserves browser fallback and failure feedback', async () => {
  const desktop = createController()
  await desktop.controller.copyText('hello', '已复制')
  assert.deepEqual(desktop.copied, ['hello'])
  assert.deepEqual(desktop.messages, [['success', '已复制']])

  const browser = createController({ bridge: { copyText: undefined } })
  await browser.controller.copyText('hello', '已复制')
  assert.deepEqual(browser.copied, ['browser:hello'])

  const failure = createController({ bridge: { copyText: async () => { throw new Error('denied') } } })
  await failure.controller.copyText('hello', '已复制')
  assert.deepEqual(failure.messages, [['error', '复制失败']])
})

test('opens external links through the trusted desktop bridge or isolated browser target', async () => {
  const desktop = createController()
  desktop.controller.openExternalLink('https://example.test')
  await flushPromises()
  assert.deepEqual(desktop.opened, ['https://example.test'])

  const browser = createController({ bridge: { openExternal: undefined } })
  browser.controller.openExternalLink('https://example.test')
  assert.deepEqual(browser.windows, [[
    'https://example.test',
    '_blank',
    'noopener,noreferrer',
  ]])

  const failure = createController({ bridge: { openExternal: async () => { throw new Error('failed') } } })
  failure.controller.openExternalLink('https://example.test')
  await flushPromises()
  assert.deepEqual(failure.messages, [['error', '无法使用默认浏览器打开链接']])
})

test('resolves folder and Markdown locations before revealing them', async () => {
  const state = createController({
    request: {
      get: async (...args) => {
        state.requests.push(['get', ...args])
        return args[0].includes('/content/folders/')
          ? { data: { path: '/library/folder' } }
          : { data: { markdown_draft_path: '/library/item.md' } }
      },
    },
  })
  await state.controller.revealLibraryNodeLocation({ type: 'folder', id: 'folder/a' })
  await state.controller.revealLibraryNodeLocation({ type: 'content', raw: { id: 'item/a' } })

  assert.deepEqual(state.requests, [
    ['get', 'http://api.test/content/folders/folder%2Fa/location', { timeout: 10000 }],
    ['get', 'http://api.test/markdown/content/item%2Fa', { timeout: 10000 }],
  ])
  assert.deepEqual(state.revealed, ['/library/folder', '/library/item.md'])

  await state.controller.revealLocalPath('/library/direct.md')
  assert.deepEqual(state.revealed, ['/library/folder', '/library/item.md', '/library/direct.md'])
})

test('keeps Finder actions desktop-only and reports missing generated files', async () => {
  const browser = createController({ bridge: { revealPath: undefined } })
  await browser.controller.revealLibraryNodeLocation({ type: 'folder', id: 'folder-1' })
  await browser.controller.revealLocalPath('/library/item.md')
  assert.deepEqual(browser.messages, [
    ['warning', '请在桌面版中使用“在 Finder 中显示”'],
    ['warning', '请在桌面版中使用“在 Finder 中显示”'],
  ])

  const missing = createController()
  await missing.controller.revealLibraryNodeLocation({ type: 'content', id: 'item-1' })
  assert.deepEqual(missing.messages, [['error', '本地 Markdown 文件尚未生成']])
})

test('checks optional updates, opens the confirmed page, and records bounded telemetry', async () => {
  const confirmations = []
  const state = createController({
    request: {
      get: async (...args) => {
        state.requests.push(['get', ...args])
        return { data: {
          state: 'available',
          latest_version: '0.2.0',
          download_page_url: 'https://example.test/releases',
          release_notes: '安全与结构改进',
        } }
      },
      post: async (...args) => {
        state.requests.push(['post', ...args])
        return { data: {} }
      },
    },
    confirm: async (...args) => { confirmations.push(args) },
  })

  await state.controller.checkManualUpdate()
  await flushPromises()

  assert.deepEqual(confirmations, [[
    '发现 KnowledgeHub 0.2.0。\n\n安全与结构改进',
    '有可用更新',
    {
      confirmButtonText: '打开下载页',
      cancelButtonText: '稍后再说',
      type: 'info',
      closeOnClickModal: true,
    },
  ]])
  assert.deepEqual(state.opened, ['https://example.test/releases'])
  assert.deepEqual(state.requests, [
    ['get', 'http://api.test/updates/check', { timeout: 6000 }],
    [
      'post',
      'http://api.test/telemetry/events',
      { event_name: 'update_download_page_opened', properties: {} },
      { timeout: 2000 },
    ],
  ])
})
