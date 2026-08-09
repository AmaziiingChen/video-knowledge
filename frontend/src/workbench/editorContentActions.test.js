import assert from 'node:assert/strict'
import test from 'node:test'
import { dispatchEditorContentAction } from './editorContentActions.js'
test('preserves menu action IDs and their event payloads', () => {
  const calls = []
  const content = { id: 'c1', original_file_path: '/managed/original.pdf' }
  const common = { tabId: 'content:c1', content, sourceUrl: 'https://example.com', emit: (...args) => calls.push(args), toggleRemotePage: () => calls.push(['toggle']), exportTranscript: (id) => calls.push(['export', id]), requestCover: (id) => calls.push(['cover', id]) }
  dispatchEditorContentAction({ ...common, id: 'open-original-file' })
  dispatchEditorContentAction({ ...common, id: 'export-transcript' })
  dispatchEditorContentAction({ ...common, id: 'open-detail-url', payload: 'https://detail.example.com' })
  assert.deepEqual(calls, [['open-original-file', '/managed/original.pdf'], ['export', 'content:c1'], ['open-external-link', 'https://detail.example.com']])
})
