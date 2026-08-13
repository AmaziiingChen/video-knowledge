export function isLocalHtmlDocument(item) {
  if (item?.source_provider !== 'local_file' || item?.content_type !== 'document') return false
  const format = String(item?.source_metadata?.file_format || '').toUpperCase()
  const filename = String(item?.source_metadata?.file_name || '')
  return ['HTML', 'HTM', 'XHTML'].includes(format) || /\.x?html?$/i.test(filename)
}

export function useContentSelectionController({
  selectedContentItem,
  currentMarkdownItem,
  getContentItemDetail,
  updatePendingArticlePreviewReadiness,
  loadArticlePreview,
  activateQaSession,
  isQaSessionActive,
  loadContentQaHistory,
  scheduleContentViewed,
  loadCurrentArticleOcrStatus,
  loadContentAiCalls,
  loadMarkdownForItem,
}) {
  async function hydrateContentItem(item) {
    if (!item?.id) return item
    return (await getContentItemDetail(item.id)) || item
  }

  async function selectContentItem(item, { awaitPrimaryPreview = false } = {}) {
    const changed = String(selectedContentItem.value?.id || '') !== String(item.id || '')
    selectedContentItem.value = item
    currentMarkdownItem.value = item
    const hydrationPromise = hydrateContentItem(item).then((detail) => {
      if (String(selectedContentItem.value?.id || '') !== String(detail?.id || '')) return
      selectedContentItem.value = detail
      currentMarkdownItem.value = detail
      updatePendingArticlePreviewReadiness(detail)
      if (isLocalHtmlDocument(detail)) void loadArticlePreview(detail)
    })
    void hydrationPromise

    if (changed) {
      const session = activateQaSession(item.id)
      void loadContentQaHistory(item.id, session)
    } else if (!isQaSessionActive(item.id)) {
      activateQaSession(item.id)
    }

    scheduleContentViewed(item.id)
    let primaryPreviewPromise = Promise.resolve()
    if (
      (['article', 'forum_post'].includes(item.content_type)
        && ['wechat', 'campus', 'rss', 'wechat_miniprogram', 'xiaohongshu'].includes(item.source_provider))
      || isLocalHtmlDocument(item)
    ) {
      // Preview restoration is independent from the Markdown draft read below.
      primaryPreviewPromise = loadArticlePreview(item)
      void primaryPreviewPromise
    }
    void loadCurrentArticleOcrStatus()
    void loadContentAiCalls(item.id)
    await loadMarkdownForItem(item)
    if (awaitPrimaryPreview) {
      await Promise.all([hydrationPromise, primaryPreviewPromise])
    }
  }

  return { selectContentItem }
}
