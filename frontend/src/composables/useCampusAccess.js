import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { enqueueSourceSyncTask, observeSourceSyncTask } from '../utils/sourceSyncTask'

const CAMPUS_API = 'http://127.0.0.1:8000/api/campus-sources'
const CAMPUS_SCHEDULER_TICK_MS = 60_000
const CAMPUS_HISTORY_MAX = 300
const GWT_IMPORT_BATCH_SIZE = 50

const DEFAULT_STATUS = {
  available: Boolean(window.knowledgeHubDesktop?.campusAuthStatus),
  state: window.knowledgeHubDesktop?.campusAuthStatus ? 'disconnected' : 'direct_only',
  label: window.knowledgeHubDesktop?.campusAuthStatus ? '正在检查' : '仅支持校内直连',
  detail: window.knowledgeHubDesktop?.campusAuthStatus
    ? '正在读取本机校园认证状态。'
    : '浏览器版本不会保存学校登录态；连接校园网后仍可直接同步。',
  connected: false,
}

export function useCampusAccess({ refreshContent, refreshFolders, revealContentItems } = {}) {
  const campusAccess = ref({ ...DEFAULT_STATUS })
  const campusConnecting = ref(false)
  const campusBulkSyncing = ref(false)
  const campusSyncingSources = ref([])
  const campusSyncing = computed(() => campusBulkSyncing.value || campusSyncingSources.value.length > 0)
  const campusLastSync = ref(null)
  const campusSources = ref([])
  const campusSourcesLoading = ref(false)
  const campusSyncingSource = ref('')
  let campusSourceLoadCount = 0
  let schedulerTimer = null
  let schedulerRunning = false

  async function loadCampusSources({ silent = false } = {}) {
    campusSourceLoadCount += 1
    campusSourcesLoading.value = true
    try {
      const response = await axios.get(`${CAMPUS_API}/settings`, { timeout: 10000 })
      campusSources.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
      if (!silent) ElMessage.error(error?.response?.data?.detail || '无法读取校园来源设置')
    } finally {
      campusSourceLoadCount = Math.max(0, campusSourceLoadCount - 1)
      campusSourcesLoading.value = campusSourceLoadCount > 0
    }
    return campusSources.value
  }

  async function updateCampusSource(source, payload) {
    const previous = { ...source }
    Object.assign(source, payload)
    try {
      const response = await axios.patch(`${CAMPUS_API}/settings/${source.slug}`, payload, { timeout: 10000 })
      Object.assign(source, response.data || {})
      return true
    } catch (error) {
      Object.assign(source, previous)
      ElMessage.error(error?.response?.data?.detail || '校园来源设置保存失败')
      return false
    }
  }

  async function loadCampusAccessStatus({ silent = false } = {}) {
    const api = window.knowledgeHubDesktop?.campusAuthStatus
    if (!api) {
      campusAccess.value = { ...DEFAULT_STATUS }
      return campusAccess.value
    }
    try {
      campusAccess.value = await api()
    } catch (error) {
      campusAccess.value = {
        ...DEFAULT_STATUS,
        state: 'error',
        label: '状态不可用',
        detail: error?.message || '无法读取校园认证状态。',
      }
      if (!silent) ElMessage.error(campusAccess.value.detail)
    }
    return campusAccess.value
  }

  async function connectCampusWebVpn() {
    const api = window.knowledgeHubDesktop?.connectCampusWebVpn
    if (!api) {
      ElMessage.warning('请使用桌面版连接学校 WebVPN，或先连接校园网后直接同步。')
      return
    }
    campusConnecting.value = true
    try {
      campusAccess.value = await api()
      if (campusAccess.value.connected) {
        ElMessage.success('校园访问已连接，可以同步公文通')
      } else {
        ElMessage.warning(campusAccess.value.detail || '请在登录窗口中打开一次公文通列表')
      }
    } catch (error) {
      ElMessage.error(error?.message || '校园登录窗口未能打开')
    } finally {
      campusConnecting.value = false
    }
  }

  async function disconnectCampusWebVpn() {
    const api = window.knowledgeHubDesktop?.disconnectCampusWebVpn
    if (!api) return
    campusConnecting.value = true
    try {
      campusAccess.value = await api()
      campusLastSync.value = null
      ElMessage.success('校园登录态已从本机移除')
    } catch (error) {
      ElMessage.error(error?.message || '无法移除校园登录态')
    } finally {
      campusConnecting.value = false
    }
  }

  function beginCampusSourceSync(slug, { allowDuringBulk = false } = {}) {
    if (!slug || (campusBulkSyncing.value && !allowDuringBulk) || campusSyncingSources.value.includes(slug)) return false
    campusSyncingSources.value = [...campusSyncingSources.value, slug]
    campusSyncingSource.value = slug
    return true
  }

  function finishCampusSourceSync(slug) {
    campusSyncingSources.value = campusSyncingSources.value.filter((sourceSlug) => sourceSlug !== slug)
    if (!campusBulkSyncing.value && campusSyncingSource.value === slug) {
      campusSyncingSource.value = campusSyncingSources.value.at(-1) || ''
    }
  }

  async function syncCampusGwt({ silent = false, history = null, source = null, allowDuringBulk = false } = {}) {
    if (!beginCampusSourceSync('gwt', { allowDuringBulk })) return false
    try {
      let response
      let transport = 'direct'
      const request = campusSyncRequest({ history, source })
      const limit = request.mode === 'all' ? CAMPUS_HISTORY_MAX : Number(request.max_items || 10)
      const publishedAfter = request.mode === 'date_range' ? request.published_after : ''
      try {
        // GWT direct sync can wait on a campus gateway. The desktop fallback
        // must only run after a real response failure, not after a fixed UI
        // timer while the backend is still writing articles.
        response = await axios.post(`${CAMPUS_API}/gwt/sync`, request, { timeout: 0 })
        if (Number(response.data?.discovered || 0) === 0 && window.knowledgeHubDesktop?.syncCampusGwt) {
          throw new Error('校内直连未发现公文通内容，改用 WebVPN')
        }
      } catch (directError) {
        const captureApi = window.knowledgeHubDesktop?.syncCampusGwt
        if (!captureApi) throw directError
        transport = 'webvpn'
        const capture = await captureApi({ limit, publishedAfter })
        if (!capture?.ok) {
          if (capture?.error === 'authorization_required') await loadCampusAccessStatus({ silent: true })
          throw new Error(capture?.message || 'WebVPN 公文通同步失败')
        }
        const importedArticles = []
        let created = 0
        const capturedArticles = filterCampusHistoryArticles(capture.articles || [], request)
        for (let index = 0; index < capturedArticles.length; index += GWT_IMPORT_BATCH_SIZE) {
          const batch = capturedArticles.slice(index, index + GWT_IMPORT_BATCH_SIZE)
          const imported = await axios.post(
            `${CAMPUS_API}/gwt/import-snapshot`,
            { articles: batch },
            { timeout: 0 },
          )
          created += Number(imported.data?.created || 0)
          importedArticles.push(...(imported.data?.articles || []))
        }
        response = {
          data: {
            source_slug: 'gwt',
            source_name: '公文通',
            discovered: capturedArticles.length,
            created,
            duplicates: capturedArticles.length - created,
            articles: importedArticles,
          },
        }
        response.capture = capture
      }

      const result = response.data || {}
      campusLastSync.value = {
        at: new Date().toISOString(),
        transport,
        discovered: Number(result.discovered || 0),
        created: Number(result.created || 0),
        failed: Number(response.capture?.failed || 0),
      }
      await Promise.all([refreshContent?.(), refreshFolders?.()])
      await revealContentItems?.(result.articles
        ?.filter((article) => article?.created && article?.content_item_id)
        .map((article) => article.content_item_id) || [])
      const via = transport === 'webvpn' ? '通过 WebVPN ' : ''
      const failed = campusLastSync.value.failed ? `，${campusLastSync.value.failed} 篇正文未取得` : ''
      if (!silent) ElMessage.success(`${via}${campusSyncVerb(request)} ${campusLastSync.value.discovered} 篇，新增 ${campusLastSync.value.created} 篇${failed}`)
      await loadCampusSources({ silent: true })
      return true
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || '公文通同步失败'
      if (!silent) ElMessage.error(detail)
      return false
    } finally {
      finishCampusSourceSync('gwt')
    }
  }

  async function syncCampusSource(sourceOrSlug, { silent = false, history = null, allowDuringBulk = false } = {}) {
    const slug = typeof sourceOrSlug === 'string' ? sourceOrSlug : sourceOrSlug?.slug
    if (!slug) return false
    if (slug === 'gwt') {
      return syncCampusGwt({
        silent,
        history,
        source: typeof sourceOrSlug === 'string' ? null : sourceOrSlug,
        allowDuringBulk,
      })
    }
    if (!beginCampusSourceSync(slug, { allowDuringBulk })) return false
    try {
      const request = campusSyncRequest({ history, source: typeof sourceOrSlug === 'string' ? null : sourceOrSlug })
      const source = typeof sourceOrSlug === 'string' ? campusSources.value.find((item) => item.slug === slug) : sourceOrSlug
      const task = await enqueueSourceSyncTask({
        kind: 'campus',
        source_title: source?.name || '校园来源检查',
        source_slug: slug,
        ...request,
      })
      if (!silent) ElMessage.success(`已开始${source?.name || '校园来源'}检查`)
      observeSourceSyncTask(task.task_id, {
        onSucceeded: async (result) => {
          campusLastSync.value = {
            at: new Date().toISOString(),
            source_slug: slug,
            source_name: result.source_name || '',
            transport: 'public',
            discovered: Number(result.discovered || 0),
            created: Number(result.created || 0),
            failed: 0,
          }
          await Promise.all([refreshContent?.(), refreshFolders?.(), loadCampusSources({ silent: true })])
          await revealContentItems?.(result.articles
            ?.filter((article) => article?.created && article?.content_item_id)
            .map((article) => article.content_item_id) || [])
          if (!silent) ElMessage.success(`${result.source_name || '校园来源'}${campusSyncVerb(request)} ${result.discovered || 0} 篇，新增 ${result.created || 0} 篇`)
        },
        onFailed: async (message) => {
          if (!silent) ElMessage.error(message || `${slug} 检查失败`)
          await loadCampusSources({ silent: true })
        },
      })
      return true
    } catch (error) {
      if (!silent) ElMessage.error(error?.response?.data?.detail || `${slug} 检查失败`)
      await loadCampusSources({ silent: true })
      return false
    } finally {
      finishCampusSourceSync(slug)
    }
  }

  async function syncAllCampusSources({ silent = false } = {}) {
    if (campusSyncing.value) return { total: 0, succeeded: 0, failed: 0 }
    const enabledSourceSlugs = campusSources.value
      .filter((source) => source.enabled)
      .map((source) => source.slug)

    if (!enabledSourceSlugs.length) {
      if (!silent) ElMessage.warning('当前没有启用自动检查的校园来源')
      return { total: 0, succeeded: 0, failed: 0 }
    }

    campusBulkSyncing.value = true
    let succeeded = 0
    try {
      for (const slug of enabledSourceSlugs) {
        const source = campusSources.value.find((item) => item.slug === slug) || slug
        if (await syncCampusSource(source, { silent: true, allowDuringBulk: true })) succeeded += 1
      }
    } finally {
      campusBulkSyncing.value = false
      campusSyncingSource.value = ''
    }

    const failed = enabledSourceSlugs.length - succeeded
    if (!silent) {
      if (failed > 0) {
        ElMessage.warning(`已开始检查 ${enabledSourceSlugs.length} 个校园来源，${failed} 个未能入队`)
      } else {
        ElMessage.success(`已开始检查 ${succeeded} 个校园来源`)
      }
    }
    return { total: enabledSourceSlugs.length, succeeded, failed }
  }

  async function syncCampusHistory(sourceOrSlug, options = {}) {
    return syncCampusSource(sourceOrSlug, { silent: Boolean(options.silent), history: options })
  }

  function sourceIsDue(source, now = Date.now()) {
    if (!source?.enabled) return false
    const last = Date.parse(source.last_sync_at || '')
    if (!Number.isFinite(last)) return true
    return now - last >= Number(source.interval_minutes || 360) * 60_000
  }

  async function runCampusSchedule() {
    if (schedulerRunning || campusSyncing.value) return
    schedulerRunning = true
    try {
      await loadCampusSources({ silent: true })
      const due = campusSources.value.find((source) => sourceIsDue(source))
      if (due) await syncCampusSource(due, { silent: true })
    } finally {
      schedulerRunning = false
    }
  }

  onMounted(() => {
    loadCampusSources({ silent: true })
    schedulerTimer = window.setInterval(runCampusSchedule, CAMPUS_SCHEDULER_TICK_MS)
  })

  onBeforeUnmount(() => {
    if (schedulerTimer) window.clearInterval(schedulerTimer)
    schedulerTimer = null
  })

  return {
    campusAccess,
    campusConnecting,
    campusSyncing,
    campusBulkSyncing,
    campusSources,
    campusSourcesLoading,
    campusSyncingSource,
    campusSyncingSources,
    loadCampusSources,
    updateCampusSource,
    loadCampusAccessStatus,
    connectCampusWebVpn,
    disconnectCampusWebVpn,
    syncCampusGwt,
    syncCampusSource,
    syncCampusHistory,
    syncAllCampusSources,
  }
}

function campusSyncRequest({ history = null, source = null } = {}) {
  if (history?.mode === 'date_range') {
    return {
      mode: 'date_range',
      max_items: CAMPUS_HISTORY_MAX,
      published_after: history.published_after,
      published_before: history.published_before,
    }
  }
  if (history?.mode === 'all') return { mode: 'all', max_items: CAMPUS_HISTORY_MAX }
  if (history?.mode === 'count') return { mode: 'count', max_items: Math.min(CAMPUS_HISTORY_MAX, Math.max(1, Number(history.max_items) || 50)) }
  return { mode: 'latest', max_items: 300 }
}

function campusSyncVerb(request) {
  return request?.mode === 'latest' ? '检查' : '回溯'
}

function filterCampusHistoryArticles(articles, request) {
  if (request?.mode !== 'date_range') return articles
  const after = Date.parse(request.published_after || '')
  const before = Date.parse(request.published_before || '')
  return articles.filter((article) => {
    const published = Date.parse(article?.published_at || '')
    if (!Number.isFinite(published)) return false
    return published >= after && published <= before + 86_399_999
  })
}
