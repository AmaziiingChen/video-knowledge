import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./EditorHost.vue', import.meta.url), 'utf8')

test('searches the in-app WeChat original page through its webview', () => {
  assert.match(source, /webview\.addEventListener\?\.\('found-in-page', listener\)/)
  assert.match(source, /previous\.removeEventListener\?\.\('found-in-page', previousListener\)/)
  assert.match(source, /function refreshWechatRemoteFind\(\)[\s\S]*?webview\.findInPage\(query, \{[\s\S]*?findNext:\s*true/)
  assert.match(source, /function navigatePreviewFind\(direction\)[\s\S]*?isWechatRemoteVisible\.value[\s\S]*?findNext:\s*false/)
  assert.match(source, /function updatePreviewFindQuery\(query\)[\s\S]*?isWechatRemoteVisible\.value[\s\S]*?refreshWechatRemoteFind\(\)/)
})

test('clears the WeChat webview search selection when the find bar closes', () => {
  assert.match(source, /function closePreviewFind\(\)[\s\S]*?clearWechatRemoteFind\(\{ clearSelection: true \}\)/)
  assert.match(source, /function handleWechatRemoteFoundInPage\(contentItemId, event\)[\s\S]*?previewFindMatchCount\.value = Number\(result\.matches\) \|\| 0/)
})

test('labels the remote WeChat find bar as an original-page search', () => {
  assert.match(source, /:search-label="isWechatArticleTab\(activeContentTab\.id\) \? '在原文中查找' : '在预览中查找'"/)
})
