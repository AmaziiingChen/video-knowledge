import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useContentReadinessController({
  allContentItems,
  selectedContentItem,
  applyContentFilter,
  request = axios,
  apiBase = API,
}) {
  async function getContentItemDetail(contentItemId) {
    if (!contentItemId) return null
    try {
      const res = await request.get(`${apiBase}/content/item/${contentItemId}`, { timeout: 10000 })
      const detail = res.data
      if (!detail?.id) return null
      const existing = allContentItems.value.some((entry) => String(entry.id) === String(detail.id))
      allContentItems.value = existing
        ? allContentItems.value.map((entry) => (String(entry.id) === String(detail.id) ? detail : entry))
        : [...allContentItems.value, detail]
      // Detail hydration is also how a just-enqueued link enters the lazy
      // file tree. Keep the presentation list in sync immediately instead of
      // waiting for a terminal task refresh.
      applyContentFilter()
      return detail
    } catch {
      // A stale persisted tab or a backend restart must not prevent the rest
      // of the workbench from opening.
      return null
    }
  }

  function mergeContentTextReadiness(contentItemId, readiness) {
    if (!contentItemId || !readiness) return
    allContentItems.value = allContentItems.value.map((item) => (
      item.id === contentItemId ? { ...item, text_readiness: readiness } : item
    ))
    applyContentFilter()
    if (selectedContentItem.value?.id === contentItemId) {
      selectedContentItem.value = allContentItems.value.find((item) => item.id === contentItemId)
        || { ...selectedContentItem.value, text_readiness: readiness }
    }
  }

  async function refreshContentTextReadiness(contentItemId) {
    if (!contentItemId) return null
    try {
      const res = await request.get(`${apiBase}/content/${contentItemId}/text-readiness`, { timeout: 10000 })
      mergeContentTextReadiness(contentItemId, res.data)
      return res.data
    } catch {
      return null
    }
  }

  return { getContentItemDetail, mergeContentTextReadiness, refreshContentTextReadiness }
}
