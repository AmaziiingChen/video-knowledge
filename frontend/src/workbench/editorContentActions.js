export function dispatchEditorContentAction({ id, payload, tabId, content, sourceUrl, emit, toggleRemotePage, exportTranscript, requestCover }) {
  const actions = {
    'copy-source': () => emit('copy-text', sourceUrl, '链接已复制'),
    'open-source': () => emit('open-external-link', sourceUrl),
    'toggle-remote-page': toggleRemotePage,
    'retry-source-text': () => emit('retry-source-text', content),
    'retry-processing': () => emit('retry-content-processing', content),
    'reprocess-local-source': () => emit('reprocess-local-source', content),
    'open-original-file': () => emit('open-original-file', content?.original_file_path || ''),
    'retranscribe-media': () => emit('retranscribe-video', content),
    'fetch-external-subtitle': () => emit('fetch-external-subtitle', content),
    'refresh-source-context': () => emit('refresh-source-context', content),
    'download-video': () => emit('redownload-video', content),
    'export-transcript': () => exportTranscript(tabId),
    'generate-cover': () => requestCover(tabId),
    'replan-cover': () => emit('replan-wechat-cover', content),
    'create-wechat-draft': () => emit('create-wechat-draft', content),
    'delete-content': () => emit('delete-content', content),
    'reveal-detail-path': () => emit('reveal-path', payload),
    'open-detail-url': () => emit('open-external-link', payload),
  }
  actions[id]?.()
}
