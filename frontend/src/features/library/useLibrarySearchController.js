import { ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function searchResultCountBucket(count) {
  if (count <= 0) return '0'
  if (count <= 5) return '1_5'
  if (count <= 20) return '6_20'
  if (count <= 100) return '21_100'
  return '101_plus'
}

export function useLibrarySearchController({
  apiBase = API,
  request = axios,
  notify = ElMessage,
  recordTelemetry = () => {},
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  debounceMs = 350,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const searchQuery = ref('')
  const librarySearchScope = ref('all')
  const searchResultContentItems = ref([])
  const searchingContent = ref(false)
  let searchTimer = null
  let searchRequestVersion = 0

  function clearSearchState() {
    searchResultContentItems.value = []
    searchingContent.value = false
  }

  async function searchContent(requestVersion = ++searchRequestVersion) {
    const query = searchQuery.value.trim()
    if (!query) {
      clearSearchState()
      return
    }

    searchingContent.value = true
    try {
      const response = await request.get(`${apiBase}/search`, {
        params: { q: query, scope: librarySearchScope.value, limit: 200 },
        timeout: 10000,
      })
      if (requestVersion !== searchRequestVersion) return
      const results = Array.isArray(response.data) ? response.data : []
      const contentItemIds = results.map((item) => item.content_key).filter(Boolean)
      const resolved = contentItemIds.length
        ? await request.post(`${apiBase}/content/items/resolve`, { content_item_ids: contentItemIds }, { timeout: 10000 })
        : { data: [] }
      if (requestVersion !== searchRequestVersion) return
      const itemsById = new Map((resolved.data || []).map((item) => [String(item.id), item]))
      searchResultContentItems.value = contentItemIds
        .map((id) => itemsById.get(String(id)))
        .filter(Boolean)
      const count = searchResultContentItems.value.length
      void recordTelemetry('search_completed', { result_count_bucket: searchResultCountBucket(count) })
    } catch (error) {
      if (requestVersion !== searchRequestVersion) return
      searchResultContentItems.value = []
      const message = errorMessage(error, '搜索失败')
      notify.error(typeof message === 'string' ? message : '搜索失败')
    } finally {
      if (requestVersion === searchRequestVersion) searchingContent.value = false
    }
  }

  const stopSearchWatch = watch([searchQuery, librarySearchScope], ([value]) => {
    const requestVersion = ++searchRequestVersion
    if (searchTimer) {
      cancelSchedule(searchTimer)
      searchTimer = null
    }
    const query = value.trim()
    if (!query || query.length < 2) {
      clearSearchState()
      return
    }
    searchTimer = schedule(() => {
      searchTimer = null
      return searchContent(requestVersion)
    }, debounceMs)
  }, { flush: 'sync' })

  function disposeLibrarySearchController() {
    stopSearchWatch()
    if (searchTimer) cancelSchedule(searchTimer)
    searchTimer = null
  }

  return {
    searchQuery,
    librarySearchScope,
    searchResultContentItems,
    searchingContent,
    searchContent,
    disposeLibrarySearchController,
  }
}
