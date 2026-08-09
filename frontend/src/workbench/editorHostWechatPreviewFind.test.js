import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./EditorHost.vue', import.meta.url), 'utf8')
const controllerSource = await readFile(
  new URL('./useRemoteArticlePreviewController.js', import.meta.url),
  'utf8',
)

test('keeps the EditorHost surface wired to the dedicated remote reader controller', () => {
  assert.match(source, /useRemoteArticlePreviewController/)
  assert.match(source, /refreshRemote:\s*refreshRemotePreviewFind/)
  assert.match(source, /clearRemote:\s*clearRemotePreviewFind/)
  assert.match(controllerSource, /webview\.addEventListener\?\.\('found-in-page', listener\)/)
  assert.match(controllerSource, /findNext:\s*true/)
  assert.match(controllerSource, /findNext:\s*false/)
})

test('clears the WeChat webview search selection when the find bar closes', () => {
  assert.match(controllerSource, /clearWechatRemoteFind\(\{ clearSelection \}\)/)
  assert.match(controllerSource, /stopFindInPage\(clearSelection \? 'clearSelection' : 'keepSelection'\)/)
})

test('labels the remote WeChat find bar as an original-page search', () => {
  assert.match(source, /:search-label="isWechatArticleTab\(activeContentTab\.id\) \? '在原文中查找' : '在预览中查找'"/)
})
