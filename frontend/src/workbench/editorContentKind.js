export function createEditorContentKind({ contentForTab, articlePreviewForTab }) {
  function content(tabId) { return contentForTab(tabId) }
  function isLocalHtmlArticleTab(tabId) {
    const item = content(tabId)
    if (item?.source_provider !== 'local_file' || item?.content_type !== 'document') return false
    const format = String(item?.source_metadata?.file_format || '').toUpperCase()
    const filename = String(item?.source_metadata?.file_name || '')
    return ['HTML', 'HTM', 'XHTML'].includes(format) || /\.x?html?$/i.test(filename)
  }
  function isArticleTab(tabId) { return ['article', 'forum_post'].includes(content(tabId)?.content_type) || isLocalHtmlArticleTab(tabId) }
  function isVideoTab(tabId) { return content(tabId)?.content_type === 'video' }
  function isAudioTab(tabId) { return content(tabId)?.content_type === 'audio' }
  function isTimedMediaTab(tabId) { return isVideoTab(tabId) || isAudioTab(tabId) }
  function isExternalPdfTab(tabId) {
    const item = content(tabId)
    if (item?.source_provider !== 'local_file' || item?.content_type !== 'document') return false
    return String(item?.source_name || '').includes('PDF')
      || /\.pdf$/iu.test(String(item?.original_file_path || ''))
  }
  function isExternalImageTab(tabId) {
    const item = content(tabId)
    return item?.source_provider === 'local_file' && item?.content_type === 'image'
  }
  function isExternalMarkdownTab(tabId) {
    const item = content(tabId)
    return ['local_markdown', 'local_file'].includes(item?.source_provider)
      && item?.content_type === 'document'
      && !isLocalHtmlArticleTab(tabId)
      && !isExternalPdfTab(tabId)
  }
  function isMiniProgramCaptureTab(tabId) {
    const item = content(tabId)
    return item?.source_provider === 'wechat_miniprogram'
      && ['forum_capture', 'report'].includes(item?.content_type)
  }
  function isReportTab(tabId) {
    const item = content(tabId)
    return !(item?.source_provider === 'wechat_miniprogram' && ['forum_capture', 'report'].includes(item?.content_type))
      && (item?.source_provider === 'wechat_report' || item?.content_type === 'report')
  }
  function readerKindForTab(tabId) {
    if (!content(tabId)) return ''
    if (isTimedMediaTab(tabId)) return 'timed-media'
    if (isExternalImageTab(tabId)) return 'external-image'
    if (isArticleTab(tabId)) return 'article'
    if (isReportTab(tabId)) return 'report'
    if (isExternalMarkdownTab(tabId)) return 'external-markdown'
    if (isMiniProgramCaptureTab(tabId)) return 'mini-program-capture'
    return 'source'
  }
  function sourceUrlForTab(tabId) {
    const item = content(tabId)
    for (const value of [item?.source_url, item?.source_metadata?.original_source_url]) {
      const url = String(value || '')
      if (/^https?:\/\//iu.test(url)) return url
    }
    return ''
  }
  function hasRemoteSource(tabId) { return /^https?:\/\//iu.test(sourceUrlForTab(tabId)) }
  function articlePreviewHtml(tabId) {
    const preview = articlePreviewForTab(tabId)
    return isLocalHtmlArticleTab(tabId) ? preview?.html || preview?.source_html || '' : preview?.html || ''
  }
  return {
    articlePreviewHtml,
    hasRemoteSource,
    isArticleTab,
    isAudioTab,
    isExternalImageTab,
    isExternalMarkdownTab,
    isExternalPdfTab,
    isLocalHtmlArticleTab,
    isMiniProgramCaptureTab,
    isReportTab,
    isTimedMediaTab,
    isVideoTab,
    readerKindForTab,
    sourceUrlForTab,
  }
}
