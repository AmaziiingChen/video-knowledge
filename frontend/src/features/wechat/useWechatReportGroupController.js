import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

export function useWechatReportGroupController({
  reportGroupApi,
  loadSubscriptions,
  loadReportPrompts,
  selectedReportPromptGroupId,
  request = axios,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const wechatDeletingGroupId = ref('')
  const wechatSavingScheduleGroupId = ref('')

  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  async function createWeChatReportGroup(payload, done) {
    try {
      const response = await request.post(reportGroupApi, payload, { timeout: 10000 })
      done?.()
      await loadSubscriptions()
      selectedReportPromptGroupId.value = response.data?.id || selectedReportPromptGroupId.value
      await loadReportPrompts()
      notify.success('报告分组已添加；可前往“提示词 → 分组报告”完善区间报告写法')
    } catch (error) {
      notifyError(error, '添加公众号分组失败')
    }
  }

  async function deleteWeChatReportGroup(group) {
    if (!group?.id || wechatDeletingGroupId.value) return
    wechatDeletingGroupId.value = group.id
    try {
      const response = await request.delete(`${reportGroupApi}/${group.id}`, { timeout: 10000 })
      await loadSubscriptions()
      await loadReportPrompts()
      const affected = Number(response.data?.affected_subscription_count || 0)
      notify.success(`分组“${group.name}”已删除${affected ? `，已从 ${affected} 个公众号移除标签` : ''}`)
    } catch (error) {
      notifyError(error, '删除公众号分组失败')
    } finally {
      if (wechatDeletingGroupId.value === group.id) wechatDeletingGroupId.value = ''
    }
  }

  async function saveWeChatReportSchedule(groupId, payload, done) {
    if (!groupId || wechatSavingScheduleGroupId.value) return
    wechatSavingScheduleGroupId.value = groupId
    try {
      await request.put(
        `${reportGroupApi}/${encodeURIComponent(groupId)}/schedule`,
        payload,
        { timeout: 10000 },
      )
      await loadSubscriptions()
      done?.()
      notify.success(payload.enabled ? '已开启定时生成' : '已关闭定时生成')
    } catch (error) {
      notifyError(error, '保存定时生成计划失败')
    } finally {
      if (wechatSavingScheduleGroupId.value === groupId) wechatSavingScheduleGroupId.value = ''
    }
  }

  return {
    wechatDeletingGroupId,
    wechatSavingScheduleGroupId,
    createWeChatReportGroup,
    deleteWeChatReportGroup,
    saveWeChatReportSchedule,
  }
}
