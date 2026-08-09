import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./EditorHost.vue', import.meta.url), 'utf8')
const controllerSource = await readFile(
  new URL('./usePreviewFindController.js', import.meta.url),
  'utf8',
)

test('searches the in-app WeChat original page through its webview', () => {
  assert.match(source, /webview\.addEventListener\?\.\('found-in-page', listener\)/)
  assert.match(source, /previous\.removeEventListener\?\.\('found-in-page', previousListener\)/)
  assert.match(source, /function refreshWechatRemoteFind\(\)[\s\S]*?webview\.findInPage\(query, \{[\s\S]*?findNext:\s*true/)
  assert.match(source, /function navigateRemotePreviewFind\(mode, query, direction\)[\s\S]*?mode === 'wechat'[\s\S]*?findNext:\s*false/)
  assert.match(source, /function refreshRemotePreviewFind\(mode\)[\s\S]*?mode === 'wechat'[\s\S]*?refreshWechatRemoteFind\(\)/)
  assert.match(controllerSource, /function updatePreviewFindQuery\(query\)[\s\S]*?refreshRemote\(mode, previewFindQuery\.value\.trim\(\)\)/)
})

test('clears the WeChat webview search selection when the find bar closes', () => {
  assert.match(controllerSource, /function closePreviewFind\(\)[\s\S]*?clearRemote\(\{ clearSelection: true \}\)/)
  assert.match(source, /function clearRemotePreviewFind\(\{ clearSelection = false \} = \{\}\)[\s\S]*?clearWechatRemoteFind\(\{ clearSelection \}\)/)
  assert.match(source, /function handleWechatRemoteFoundInPage\(contentItemId, event\)[\s\S]*?setRemoteFindResult\(\{/)
})

test('labels the remote WeChat find bar as an original-page search', () => {
  assert.match(source, /:search-label="isWechatArticleTab\(activeContentTab\.id\) \? '在原文中查找' : '在预览中查找'"/)
})
