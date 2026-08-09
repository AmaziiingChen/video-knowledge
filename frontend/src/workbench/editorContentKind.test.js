import assert from 'node:assert/strict'
import test from 'node:test'
import { createEditorContentKind } from './editorContentKind.js'

test('classifies local HTML, media, reports, and trusted source URLs without altering previews', () => {
  const rows = {
    html: { source_provider: 'local_file', content_type: 'document', source_metadata: { file_name: 'saved.html', original_source_url: 'https://example.com/original' } },
    video: { content_type: 'video', source_url: 'https://video.example.com/a' },
    report: { source_provider: 'wechat_report', content_type: 'report' },
    capture: { source_provider: 'wechat_miniprogram', content_type: 'report' },
    unsafe: { content_type: 'article', source_url: 'javascript:alert(1)', source_metadata: { original_source_url: 'file:///tmp/a' } },
  }
  const kinds = createEditorContentKind({ contentForTab: (id) => rows[id], articlePreviewForTab: (id) => id === 'html' ? { source_html: '<p>saved</p>' } : { html: '<p>body</p>' } })
  assert.equal(kinds.isArticleTab('html'), true)
  assert.equal(kinds.isTimedMediaTab('video'), true)
  assert.equal(kinds.isReportTab('report'), true)
  assert.equal(kinds.isReportTab('capture'), false)
  assert.equal(kinds.articlePreviewHtml('html'), '<p>saved</p>')
  assert.equal(kinds.sourceUrlForTab('html'), 'https://example.com/original')
  assert.equal(kinds.hasRemoteSource('unsafe'), false)
})
