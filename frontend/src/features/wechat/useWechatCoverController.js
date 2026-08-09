import { ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useWechatCoverController({
  apiBase = `${API}/wechat-publishing`,
  taskApiBase = `${API}/tasks`,
  selectedContentItem,
  ensureCoverConfigured,
  refreshContentItems = async () => {},
  refreshContentAiCalls = async () => {},
  refreshAiTokenUsage = async () => {},
  draftState = {},
  request = axios,
  notify = ElMessage,
  timers = globalThis,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const wechatCoverPlanDialogVisible = ref(false)
  const planningWechatCover = ref(false)
  const submittingWechatCoverPlan = ref(false)
  const previewingWechatCoverPrompt = ref(false)
  const wechatCoverPlanContentItemId = ref('')
  const wechatCoverPlanTitle = ref('')
  const wechatCoverPlan = ref({})
  const wechatCoverResolvedPrompt = ref('')
  const wechatCoverStyle = ref('minimal_zine')
  const wechatCoverGeneratingContentIds = ref([])
  const wechatCoverSwitchingContentIds = ref([])
  const wechatCoverHistories = ref({})
  const pollTimers = new Map()
  let disposed = false

  const stopSelectedContentWatch = selectedContentItem
    ? watch(
      () => {
        const item = selectedContentItem.value
        const isReport = item?.source_provider === 'wechat_report' || item?.content_type === 'report'
        return isReport ? String(item?.id || '') : ''
      },
      (contentItemId) => {
        if (contentItemId) void loadWechatCoverHistory(contentItemId)
      },
      { immediate: true },
    )
    : () => {}

  async function openWechatCoverPlan(contentItem) {
    const contentItemId = contentItem?.id
    if (!contentItemId || !(await ensureCoverConfigured?.())) return
    wechatCoverPlanContentItemId.value = contentItemId
    wechatCoverPlanTitle.value = String(contentItem?.title || '')
    wechatCoverPlan.value = {}
    wechatCoverResolvedPrompt.value = ''
    wechatCoverStyle.value = 'minimal_zine'
    wechatCoverPlanDialogVisible.value = true
  }

  async function planWechatCover(coverStyle) {
    const contentItemId = wechatCoverPlanContentItemId.value
    if (!contentItemId) return
    wechatCoverStyle.value = String(coverStyle || 'minimal_zine')
    wechatCoverPlan.value = {}
    wechatCoverResolvedPrompt.value = ''
    planningWechatCover.value = true
    try {
      const response = await request.post(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}/cover-plan`,
        { title: wechatCoverPlanTitle.value.trim(), cover_style: wechatCoverStyle.value },
        { timeout: 120000 },
      )
      if (wechatCoverPlanContentItemId.value !== contentItemId) return
      wechatCoverPlan.value = response.data?.visual_brief || {}
      wechatCoverResolvedPrompt.value = response.data?.resolved_image_prompt || ''
    } catch (error) {
      notify.error(errorMessage(error, '公众号封面主题策划失败'))
    } finally {
      planningWechatCover.value = false
    }
  }

  async function previewWechatCoverPrompt(visualBrief) {
    const contentItemId = wechatCoverPlanContentItemId.value
    if (!contentItemId) return
    previewingWechatCoverPrompt.value = true
    try {
      const response = await request.post(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}/cover-prompt`,
        { title: wechatCoverPlanTitle.value.trim(), visual_brief: visualBrief },
        { timeout: 15000 },
      )
      wechatCoverResolvedPrompt.value = response.data?.resolved_image_prompt || ''
    } catch (error) {
      notify.error(errorMessage(error, '无法解析完整生图提示词'))
    } finally {
      previewingWechatCoverPrompt.value = false
    }
  }

  async function confirmWechatCoverPlan(visualBrief) {
    const contentItemId = wechatCoverPlanContentItemId.value
    if (!contentItemId || !(await ensureCoverConfigured?.())) return
    submittingWechatCoverPlan.value = true
    try {
      const response = await request.post(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}/cover`,
        { title: wechatCoverPlanTitle.value.trim(), visual_brief: visualBrief },
        { timeout: 20000 },
      )
      wechatCoverPlanDialogVisible.value = false
      monitorWechatCoverTask(response.data, contentItemId)
      notify.success('封面已进入生成队列')
    } catch (error) {
      notify.error(errorMessage(error, '无法开始生成公众号封面'))
    } finally {
      submittingWechatCoverPlan.value = false
    }
  }

  async function regenerateWechatReportCover(contentItem) {
    const contentItemId = contentItem?.id
    if (!contentItemId || wechatCoverGeneratingContentIds.value.includes(contentItemId)) return
    if (!(await ensureCoverConfigured?.())) return
    try {
      const response = await request.post(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}/cover`,
        { title: String(contentItem?.title || '').trim() },
        { timeout: 20000 },
      )
      monitorWechatCoverTask(response.data, contentItemId)
      notify.success('正在使用当前视觉策划重新生成封面')
    } catch (error) {
      const message = errorMessage(error, '无法重新生成公众号封面')
      if (message.includes('视觉策划')) {
        await openWechatCoverPlan(contentItem)
        return
      }
      notify.error(message)
    }
  }

  function wechatCoverHistoryForContent(contentItemId) {
    return wechatCoverHistories.value[String(contentItemId || '')] || {
      active_cover_id: '',
      covers: [],
    }
  }

  async function loadWechatCoverHistory(contentItemId, { showError = false } = {}) {
    const normalizedId = String(contentItemId || '')
    if (!normalizedId) return
    try {
      const response = await request.get(
        `${apiBase}/reports/${encodeURIComponent(normalizedId)}/covers`,
        { timeout: 10000 },
      )
      wechatCoverHistories.value = {
        ...wechatCoverHistories.value,
        [normalizedId]: {
          active_cover_id: String(response.data?.active_cover_id || ''),
          covers: Array.isArray(response.data?.covers) ? response.data.covers : [],
        },
      }
    } catch (error) {
      if (showError) notify.error(errorMessage(error, '无法读取封面历史'))
    }
  }

  async function selectWechatReportCover({ contentItemId, coverId }) {
    const normalizedId = String(contentItemId || '')
    const normalizedCoverId = String(coverId || '')
    if (!normalizedId || !normalizedCoverId || wechatCoverSwitchingContentIds.value.includes(normalizedId)) return
    wechatCoverSwitchingContentIds.value = [...wechatCoverSwitchingContentIds.value, normalizedId]
    try {
      const response = await request.post(
        `${apiBase}/reports/${encodeURIComponent(normalizedId)}/covers/${encodeURIComponent(normalizedCoverId)}/select`,
        {},
        { timeout: 10000 },
      )
      wechatCoverHistories.value = {
        ...wechatCoverHistories.value,
        [normalizedId]: {
          active_cover_id: String(response.data?.active_cover_id || ''),
          covers: Array.isArray(response.data?.covers) ? response.data.covers : [],
        },
      }
      if (draftState.dialogVisible?.value && draftState.contentItemId?.value === normalizedId) {
        draftState.coverUrl.value = String(response.data?.cover_url || '')
        draftState.coverStatus.value = 'qwen_generated'
      }
      await refreshContentItems()
      notify.success('已选择此封面，发布草稿时会使用它')
    } catch (error) {
      notify.error(errorMessage(error, '无法切换公众号封面'))
    } finally {
      wechatCoverSwitchingContentIds.value = wechatCoverSwitchingContentIds.value
        .filter((item) => item !== normalizedId)
    }
  }

  function setWechatCoverGenerating(contentItemId, generating) {
    const next = new Set(wechatCoverGeneratingContentIds.value)
    if (generating) next.add(contentItemId)
    else next.delete(contentItemId)
    wechatCoverGeneratingContentIds.value = [...next]
  }

  function monitorWechatCoverTask(task, contentItemId) {
    const taskId = String(task?.task_id || '')
    if (!taskId || !contentItemId || disposed) return
    const previousTimer = pollTimers.get(contentItemId)
    if (previousTimer) timers.clearTimeout(previousTimer)
    setWechatCoverGenerating(contentItemId, true)

    const poll = async () => {
      if (disposed) return
      try {
        const response = await request.get(
          `${taskApiBase}/${encodeURIComponent(taskId)}`,
          { timeout: 10000 },
        )
        const state = response.data || {}
        if (state.status === 'succeeded') {
          pollTimers.delete(contentItemId)
          setWechatCoverGenerating(contentItemId, false)
          await refreshContentItems()
          await loadWechatCoverHistory(contentItemId)
          await Promise.all([
            refreshContentAiCalls(contentItemId),
            refreshAiTokenUsage(),
          ])
          if (draftState.dialogVisible?.value && draftState.contentItemId?.value === contentItemId) {
            const defaults = await request.get(
              `${apiBase}/reports/${encodeURIComponent(contentItemId)}`,
              { timeout: 15000 },
            )
            draftState.coverUrl.value = defaults.data?.cover_url || ''
            draftState.coverStatus.value = defaults.data?.cover_status || ''
          }
          notify.success('新封面已生成，旧封面仍可切换')
          return
        }
        if (['failed', 'cancelled'].includes(state.status)) {
          pollTimers.delete(contentItemId)
          setWechatCoverGenerating(contentItemId, false)
          notify.error(state.error || '公众号封面生成失败，原封面已保留')
          return
        }
        pollTimers.set(contentItemId, timers.setTimeout(poll, 1500))
      } catch {
        pollTimers.set(contentItemId, timers.setTimeout(poll, 3000))
      }
    }
    void poll()
  }

  function disposeWechatCoverController() {
    disposed = true
    stopSelectedContentWatch()
    for (const timer of pollTimers.values()) timers.clearTimeout(timer)
    pollTimers.clear()
  }

  return {
    confirmWechatCoverPlan,
    disposeWechatCoverController,
    loadWechatCoverHistory,
    openWechatCoverPlan,
    planWechatCover,
    planningWechatCover,
    previewWechatCoverPrompt,
    previewingWechatCoverPrompt,
    regenerateWechatReportCover,
    selectWechatReportCover,
    submittingWechatCoverPlan,
    wechatCoverGeneratingContentIds,
    wechatCoverHistories,
    wechatCoverHistoryForContent,
    wechatCoverPlan,
    wechatCoverPlanContentItemId,
    wechatCoverPlanDialogVisible,
    wechatCoverPlanTitle,
    wechatCoverResolvedPrompt,
    wechatCoverStyle,
    wechatCoverSwitchingContentIds,
  }
}
