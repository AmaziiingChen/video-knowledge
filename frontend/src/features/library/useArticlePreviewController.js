import { reactive } from 'vue'
import axios from 'axios'
import { API_BASE as API } from '../../utils/localApiAuth.js'
import {
  readArticlePreviewCache,
  removeArticlePreviewCache,
  writeArticlePreviewCache,
} from './articlePreviewCache.js'
import {
  pendingArticlePreview,
  revealArticlePreviewLoader,
} from './articlePreviewLoadState.js'

export function useArticlePreviewController({
  refreshContentTextReadiness,
  request = axios,
  apiBase = API,
  timers = globalThis,
  storage,
} = {}) {
  const articlePreviews = reactive({})
  const formattingTimers = new Map()
  const loadingTimers = new Map()
  let disposed = false

  function cancelLoader(contentItemId) {
    const timer = loadingTimers.get(contentItemId)
    if (timer !== undefined) timers.clearTimeout(timer)
    loadingTimers.delete(contentItemId)
  }

  function scheduleLoader(contentItemId) {
    cancelLoader(contentItemId)
    const timer = timers.setTimeout(() => {
      loadingTimers.delete(contentItemId)
      const preview = articlePreviews[contentItemId]
      if (preview?.loading) articlePreviews[contentItemId] = revealArticlePreviewLoader(preview)
    }, 180)
    loadingTimers.set(contentItemId, timer)
  }

  function cancelFormattingRefresh(contentItemId) {
    const timer = formattingTimers.get(contentItemId)
    if (timer !== undefined) timers.clearTimeout(timer)
    formattingTimers.delete(contentItemId)
  }

  function scheduleFormattingRefresh(contentItemId, attempt = 0) {
    const preview = articlePreviews[contentItemId]
    if (
      disposed
      || !['queued', 'running'].includes(preview?.formatting_status)
      || formattingTimers.has(contentItemId)
    ) return

    const timer = timers.setTimeout(async () => {
      formattingTimers.delete(contentItemId)
      if (disposed) return
      try {
        const res = await request.get(`${apiBase}/content/${contentItemId}/article-preview`, {
          timeout: 30000,
        })
        if (disposed) return
        articlePreviews[contentItemId] = res.data
        if (attempt < 39) scheduleFormattingRefresh(contentItemId, attempt + 1)
      } catch {
        // The OCR original remains readable. Reopening the item can request
        // the formatting state again without replacing it with a transient error.
      }
    }, 1500)
    formattingTimers.set(contentItemId, timer)
  }

  async function loadArticlePreview(item, { force = false } = {}) {
    if (!item?.id || disposed) return
    const currentPreview = articlePreviews[item.id]
    if (!force && currentPreview !== undefined) return
    const cachedPreview = force ? null : readArticlePreviewCache(item.id, item.updated_at, storage)
    if (cachedPreview) {
      // Render the durable local snapshot before revalidating it. This keeps a
      // known article readable across app restarts instead of flashing a loader.
      articlePreviews[item.id] = cachedPreview
    } else {
      articlePreviews[item.id] = pendingArticlePreview(currentPreview, item.text_readiness)
      scheduleLoader(item.id)
    }
    try {
      const res = await request.get(`${apiBase}/content/${item.id}/article-preview`, {
        timeout: 30000,
      })
      if (disposed) return
      articlePreviews[item.id] = res.data
      cancelLoader(item.id)
      writeArticlePreviewCache(item, res.data, storage)
      scheduleFormattingRefresh(item.id)
      void refreshContentTextReadiness?.(item.id)
    } catch (error) {
      cancelLoader(item.id)
      if (cachedPreview || disposed) return
      articlePreviews[item.id] = {
        error: error.response?.data?.detail || '文章版式预览暂不可用',
      }
      await refreshContentTextReadiness?.(item.id)
    }
  }

  function updatePendingArticlePreviewReadiness(item) {
    if (!item?.id || !articlePreviews[item.id]?.loading) return
    articlePreviews[item.id] = pendingArticlePreview(articlePreviews[item.id], item.text_readiness)
  }

  function resetArticlePreview(contentItemId) {
    if (!contentItemId) return
    cancelFormattingRefresh(contentItemId)
    cancelLoader(contentItemId)
    delete articlePreviews[contentItemId]
    removeArticlePreviewCache(contentItemId, storage)
  }

  function disposeArticlePreviews() {
    disposed = true
    for (const timer of loadingTimers.values()) timers.clearTimeout(timer)
    for (const timer of formattingTimers.values()) timers.clearTimeout(timer)
    loadingTimers.clear()
    formattingTimers.clear()
  }

  return {
    articlePreviews,
    disposeArticlePreviews,
    loadArticlePreview,
    resetArticlePreview,
    updatePendingArticlePreviewReadiness,
  }
}
