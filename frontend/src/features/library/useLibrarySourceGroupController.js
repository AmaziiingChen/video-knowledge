import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

export function useLibrarySourceGroupController({
  apiBase,
  loadWeChatSubscriptions,
  loadCampusSources,
  confirmDestructive,
  request = axios,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const librarySourceGroups = ref([])
  const sourceGroupEditor = ref(null)
  const showSourceGroupEditor = ref(false)
  const removingSourceGroupKey = ref('')

  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  async function loadLibrarySourceGroups() {
    try {
      const response = await request.get(apiBase, { timeout: 10000 })
      librarySourceGroups.value = Array.isArray(response.data) ? response.data : []
    } catch {
      // Source groups enrich the library and must not block its primary content view.
    }
  }

  async function openSourceGroupEditor(group) {
    if (!group?.id) return
    await loadLibrarySourceGroups()
    sourceGroupEditor.value = librarySourceGroups.value.find((item) => String(item.id) === String(group.id)) || {
      ...group,
      sources: [],
    }
    showSourceGroupEditor.value = true
  }

  async function removeSourceFromGroup(source) {
    const group = sourceGroupEditor.value
    const sourceId = String(source?.source_id || '').trim()
    const sourceKind = String(source?.kind || '').trim()
    if (!group?.id || !sourceId || !sourceKind || removingSourceGroupKey.value) return

    const sourceLabel = source.label || '这个来源'
    const confirmed = await confirmDestructive({
      title: '移出分组',
      message: `将“${sourceLabel}”移出“${group.name}”？原来源与已收集内容会保留。`,
      confirmLabel: '移出分组',
      cancelLabel: '保留',
    })
    if (!confirmed) return

    const removalKey = `${sourceKind}:${sourceId}`
    removingSourceGroupKey.value = removalKey
    try {
      await request.delete(
        `${apiBase}/${encodeURIComponent(group.id)}/sources/${encodeURIComponent(sourceKind)}/${encodeURIComponent(sourceId)}`,
        { timeout: 10000 },
      )
      await Promise.all([loadLibrarySourceGroups(), loadWeChatSubscriptions(), loadCampusSources({ silent: true })])
      const refreshedGroup = librarySourceGroups.value.find((item) => String(item.id) === String(group.id)) || null
      if (refreshedGroup) {
        sourceGroupEditor.value = refreshedGroup
      } else {
        showSourceGroupEditor.value = false
        sourceGroupEditor.value = null
      }
      notify.success(`已将“${sourceLabel}”移出“${group.name}”`)
    } catch (error) {
      notifyError(error, '移出分组失败')
    } finally {
      if (removingSourceGroupKey.value === removalKey) removingSourceGroupKey.value = ''
    }
  }

  return {
    librarySourceGroups,
    sourceGroupEditor,
    showSourceGroupEditor,
    removingSourceGroupKey,
    loadLibrarySourceGroups,
    openSourceGroupEditor,
    removeSourceFromGroup,
  }
}
