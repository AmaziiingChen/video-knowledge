import assert from 'node:assert/strict'
import test from 'node:test'

import { useMarkdownOutputSettingsController } from './useMarkdownOutputSettingsController.js'

function createController({ request = {}, refreshLibrary = async () => {} } = {}) {
  const messages = []
  const requests = []
  const controller = useMarkdownOutputSettingsController({
    notify: {
      warning: (message) => messages.push(['warning', message]),
      error: (message) => messages.push(['error', message]),
      success: (message) => messages.push(['success', message]),
      info: (message) => messages.push(['info', message]),
    },
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
    refreshLibrary,
  })
  return { controller, messages, requests }
}

test('loads the vault as the export fallback without blocking a failed startup read', async () => {
  const { controller, requests } = createController({
    request: { get: async (...args) => {
      requests.push(['get', ...args])
      return { data: { vault_path: '/vault', auto_write: true } }
    } },
  })
  await controller.loadObsidianSettings()
  assert.equal(controller.obsidianVaultPath.value, '/vault')
  assert.equal(controller.markdownExportPath.value, '/vault')
  assert.equal(controller.obsidianAutoWrite.value, true)
  assert.deepEqual(requests, [['get', 'http://api.test/obsidian/settings', { timeout: 10000 }]])

  const unavailable = createController({ request: { get: async () => { throw new Error('offline') } } })
  await unavailable.controller.loadObsidianSettings()
  assert.equal(unavailable.controller.obsidianVaultPath.value, '')
})

test('validates and saves canonical Markdown output paths', async () => {
  const { controller, messages, requests } = createController({
    request: { post: async (...args) => {
      requests.push(['post', ...args])
      return { data: { vault_path: '/canonical/vault', export_path: '/canonical/export', auto_write: false } }
    } },
  })
  assert.equal(await controller.saveObsidianSettings(), false)
  assert.deepEqual(messages, [['warning', '请填写 Markdown 写入目录和默认导出目录']])

  controller.obsidianVaultPath.value = ' /vault '
  controller.markdownExportPath.value = ' /export '
  controller.obsidianAutoWrite.value = true
  assert.equal(await controller.saveObsidianSettings(), true)
  assert.deepEqual(requests, [[
    'post',
    'http://api.test/obsidian/settings',
    { vault_path: '/vault', export_path: '/export', auto_write: true, recover_existing: true },
    { timeout: 30000 },
  ]])
  assert.equal(controller.obsidianVaultPath.value, '/canonical/vault')
  assert.equal(controller.markdownExportPath.value, '/canonical/export')
  assert.equal(controller.obsidianAutoWrite.value, false)
})

test('restores an existing library after selecting a different directory and refreshes the tree', async () => {
  const refreshes = []
  const { controller, messages, requests } = createController({
    refreshLibrary: async () => refreshes.push(true),
    request: {
      get: async (...args) => {
        requests.push(['get', ...args])
        return { data: { vault_path: '/old', export_path: '/exports', auto_write: true } }
      },
      post: async (...args) => {
        requests.push(['post', ...args])
        return {
          data: {
            vault_path: '/learning',
            export_path: '/exports',
            auto_write: true,
            recognized_documents: 120,
            restored_documents: 117,
            conflicted_documents: 3,
          },
        }
      },
    },
  })

  await controller.loadObsidianSettings()
  controller.obsidianVaultPath.value = '/learning'
  assert.equal(await controller.saveObsidianSettings(), true)

  assert.deepEqual(requests.at(-1), [
    'post',
    'http://api.test/obsidian/settings',
    { vault_path: '/learning', export_path: '/exports', auto_write: true, recover_existing: true },
    { timeout: 30000 },
  ])
  assert.deepEqual(refreshes, [true])
  assert.deepEqual(messages, [
    ['success', '已恢复 117 条旧资料，正在刷新侧边栏'],
    ['warning', '3 条重复或冲突资料已安全跳过'],
  ])
})
