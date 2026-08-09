import { ref } from 'vue'
import axios from 'axios'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const EMPTY = { status: 'unavailable', has_images: false, priority: false }
const INITIAL = { active_content_item_id: '', active_count: 0, queued_count: 0, pending_count: 0, capture_active_count: 0, capture_queued_count: 0, web_capture_active_count: 0, web_capture_queued_count: 0, wechat_capture_active_count: 0, wechat_capture_queued_count: 0, ocr_active_count: 0, ocr_queued_count: 0, completed_count: 0, failed_count: 0, next_wechat_slot_in_seconds: 0 }

export function useArticlePreparationController({ currentContent, notifyError }) {
  const articlePreparationStatus = ref({ ...INITIAL })
  const currentArticleOcrStatus = ref({ ...EMPTY })
  const prioritizingArticleOcr = ref(false)
  let timer = null
  const contentId = () => currentContent()?.content_type === 'article' ? String(currentContent()?.id || '') : ''
  async function loadCurrentArticleOcrStatus() {
    const id = contentId()
    if (!id) { currentArticleOcrStatus.value = { ...EMPTY }; return currentArticleOcrStatus.value }
    try {
      const res = await axios.get(`${API}/content/${id}/article-ocr-status`, { timeout: 5000 })
      if (contentId() === id) currentArticleOcrStatus.value = { ...currentArticleOcrStatus.value, ...(res.data || {}) }
    } catch { if (contentId() === id) currentArticleOcrStatus.value = { ...EMPTY } }
    return currentArticleOcrStatus.value
  }
  async function loadArticlePreparationStatus() {
    try {
      const res = await axios.get(`${API}/content/article-preparation-status`, { timeout: 5000 })
      articlePreparationStatus.value = { ...articlePreparationStatus.value, ...(res.data || {}) }
      void loadCurrentArticleOcrStatus()
    } catch {}
    return articlePreparationStatus.value
  }
  async function prioritizeCurrentArticleOcr() {
    const id = contentId()
    if (!id || prioritizingArticleOcr.value) return
    prioritizingArticleOcr.value = true
    try {
      const res = await axios.post(`${API}/content/${id}/prioritize-article-ocr`, {}, { timeout: 10000 })
      currentArticleOcrStatus.value = { ...currentArticleOcrStatus.value, ...(res.data || {}) }
    } catch (error) { notifyError(error.response?.data?.detail || error.message || 'OCR 优先解析失败') }
    finally { prioritizingArticleOcr.value = false }
  }
  function stopArticlePreparationStatusPolling() { if (timer) window.clearTimeout(timer); timer = null }
  function startArticlePreparationStatusPolling() {
    stopArticlePreparationStatusPolling()
    const refresh = async () => { const status = await loadArticlePreparationStatus(); timer = window.setTimeout(refresh, Number(status.pending_count || 0) > 0 ? 3000 : 15000) }
    void refresh()
  }
  return { articlePreparationStatus, currentArticleOcrStatus, prioritizingArticleOcr, loadCurrentArticleOcrStatus, prioritizeCurrentArticleOcr, startArticlePreparationStatusPolling, stopArticlePreparationStatusPolling }
}
