import { computed, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLibraryContentController({
  selectedContentItem,
  mergeContentItems,
  reconcileContentViewState,
  loadLibraryFolders,
  syncActiveWorkspaceTabSelection,
  request = axios,
  apiBase = API,
  notify = ElMessage,
  schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
  cancel = (timer) => globalThis.clearTimeout(timer),
} = {}) {
  const libraryFolderHistoryStates = ref({})
  const libraryFolderRevealIds = ref([])
  const contentItems = ref([])
  const allContentItems = ref([])
  const contentPageLoadStatus = reactive({ state: 'idle', loaded: 0, total: 0 })
  const startupPhase = ref('connecting')
  const startupBlocking = computed(() => startupPhase.value !== 'ready')
  const startupCanRetry = computed(() => startupPhase.value === 'retrying')
  const startupStatus = computed(() => {
    if (startupPhase.value === 'library') {
      return { title: '正在读取资料库', detail: '正在整理文件树，完成后即可开始操作。' }
    }
    if (startupPhase.value === 'workspace') {
      return { title: '正在恢复工作台', detail: '正在打开上次查看的资料。' }
    }
    if (startupPhase.value === 'retrying') {
      return { title: '资料库暂未响应', detail: '正在自动重新连接；也可以立即再试一次。' }
    }
    return { title: '正在连接本机服务', detail: '资料库与后台任务正在准备中。' }
  })

  let contentPageLoadVersion = 0
  let startupRetryTimer = null
  let startupRetryCount = 0

  function applyContentFilter() {
    contentItems.value = allContentItems.value
  }

  function mergeExplicitHistoryItems(items) {
    const historyItems = Array.isArray(items) ? items.filter(Boolean) : []
    if (!historyItems.length) return
    allContentItems.value = mergeContentItems(allContentItems.value, historyItems)
    reconcileContentViewState(allContentItems.value)
    applyContentFilter()
  }

  function expandLibraryFolders(folderIds) {
    const ids = [...new Set((folderIds || []).map(String).filter(Boolean))]
    if (ids.length) libraryFolderRevealIds.value = ids
  }

  async function revealContentItems(contentItemIds) {
    const ids = [...new Set((contentItemIds || []).map(String).filter(Boolean))].slice(0, 300)
    if (!ids.length) return []
    try {
      const response = await request.post(`${apiBase}/content/items/resolve`, {
        content_item_ids: ids,
      }, { timeout: 15000 })
      const items = Array.isArray(response.data) ? response.data : []
      mergeExplicitHistoryItems(items)
      expandLibraryFolders(items.map((item) => item.library_folder_id))
      return items
    } catch {
      // The durable refresh already succeeded; resolving tree locations is an
      // optional bounded enhancement and must not fail the source sync.
      notify.warning('历史资料已保存；展开左侧对应文件夹可重新加载')
      return []
    }
  }

  async function loadLibraryFolderHistory({ folderId, append = false } = {}) {
    const id = String(folderId || '')
    if (!id) return
    const previous = libraryFolderHistoryStates.value[id] || {
      offset: 0,
      hasMore: true,
      loaded: false,
    }
    if (previous.loading || (append && !previous.hasMore)) return
    const offset = append ? Number(previous.offset || 0) : 0
    libraryFolderHistoryStates.value = {
      ...libraryFolderHistoryStates.value,
      [id]: { ...previous, loading: true },
    }
    try {
      const response = await request.get(`${apiBase}/content/folders/${encodeURIComponent(id)}/items`, {
        params: { limit: 80, offset },
        timeout: 15000,
      })
      const page = response.data || {}
      const items = Array.isArray(page.items) ? page.items : []
      mergeExplicitHistoryItems(items)
      libraryFolderHistoryStates.value = {
        ...libraryFolderHistoryStates.value,
        [id]: {
          offset: offset + items.length,
          hasMore: Boolean(page.has_more),
          loaded: true,
          loading: false,
        },
      }
    } catch (error) {
      libraryFolderHistoryStates.value = {
        ...libraryFolderHistoryStates.value,
        [id]: { ...previous, loading: false },
      }
      const detail = error?.response?.data?.detail || error?.message || '加载文件夹资料失败'
      notify.error(typeof detail === 'string' ? detail : '加载文件夹资料失败')
    }
  }

  function scheduleStartupRetry() {
    startupPhase.value = 'retrying'
    if (startupRetryTimer || startupRetryCount >= 3) return
    startupRetryCount += 1
    const delay = 600 * startupRetryCount
    startupRetryTimer = schedule(() => {
      startupRetryTimer = null
      void loadContentItems({ startup: true })
    }, delay)
  }

  async function loadContentItems({ startup = false } = {}) {
    if (startup) startupPhase.value = 'library'
    const loadVersion = ++contentPageLoadVersion
    Object.assign(contentPageLoadStatus, {
      state: 'loading',
      loaded: allContentItems.value.length,
      total: allContentItems.value.length,
    })
    try {
      await loadLibraryFolders({ throwOnError: startup })
      if (loadVersion !== contentPageLoadVersion) return
      // Keep one bounded recent window in memory.  The tree stays lazy for
      // historical rows, while unread state can immediately reflect new RSS
      // and source-sync items before their folder is manually expanded.
      const response = await request.get(`${apiBase}/content/page`, {
        params: { limit: 200 },
        timeout: 15000,
      })
      if (loadVersion !== contentPageLoadVersion) return
      const page = response.data || {}
      const recentItems = Array.isArray(page.items) ? page.items : []
      allContentItems.value = mergeContentItems(allContentItems.value, recentItems)
      reconcileContentViewState(allContentItems.value, { initialWindowComplete: true })
      applyContentFilter()
      Object.assign(contentPageLoadStatus, {
        state: Boolean(page.has_more) ? 'partial' : 'ready',
        loaded: allContentItems.value.length,
        total: Number.isFinite(Number(page.total)) ? Number(page.total) : allContentItems.value.length,
      })
      startupRetryCount = 0
      if (startup) startupPhase.value = 'workspace'
      void syncActiveWorkspaceTabSelection()
      if (startup) startupPhase.value = 'ready'
    } catch (error) {
      const timedOut = error?.code === 'ECONNABORTED' || /timeout/i.test(String(error?.message || ''))
      if (startup && timedOut) {
        scheduleStartupRetry()
        notify.warning('资料库暂未响应，正在重新连接')
      } else {
        if (startup) startupPhase.value = 'retrying'
        const detail = error?.response?.data?.detail || error?.message || '读取内容库失败'
        notify.error(typeof detail === 'string' ? detail : '读取内容库失败')
      }
    }
  }

  function retryStartupHydration() {
    if (startupPhase.value !== 'retrying') return
    if (startupRetryTimer) {
      cancel(startupRetryTimer)
      startupRetryTimer = null
    }
    startupRetryCount = 0
    void loadContentItems({ startup: true })
  }

  function updateLocalContentItem(id, updater) {
    allContentItems.value = allContentItems.value.map((item) => (
      item.id === id ? updater({ ...item }) : item
    ))
    applyContentFilter()
    if (selectedContentItem.value?.id === id) {
      selectedContentItem.value = allContentItems.value.find((item) => item.id === id)
        || selectedContentItem.value
    }
  }

  function dispose() {
    if (!startupRetryTimer) return
    cancel(startupRetryTimer)
    startupRetryTimer = null
  }

  return {
    libraryFolderHistoryStates,
    libraryFolderRevealIds,
    contentItems,
    allContentItems,
    contentPageLoadStatus,
    startupBlocking,
    startupCanRetry,
    startupStatus,
    loadContentItems,
    retryStartupHydration,
    revealContentItems,
    expandLibraryFolders,
    loadLibraryFolderHistory,
    applyContentFilter,
    updateLocalContentItem,
    dispose,
  }
}
