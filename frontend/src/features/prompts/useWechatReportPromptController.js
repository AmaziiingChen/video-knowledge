import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useWechatReportPromptController({
  reportGroups,
  apiBase = API,
  request = axios,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const wechatReportPrompts = ref([])
  const selectedWechatReportPromptGroupId = ref('')
  const selectedWechatReportPromptType = ref('group_context')
  const wechatReportPromptText = ref('')
  const loadingWechatReportPrompts = ref(false)
  const savingWechatReportPrompt = ref(false)

  function syncWechatReportPromptEditor() {
    if (!reportGroups?.value?.some((group) => group.id === selectedWechatReportPromptGroupId.value)) {
      selectedWechatReportPromptGroupId.value = reportGroups?.value?.[0]?.id || ''
    }
    const hasSelectedAdapter = wechatReportPrompts.value.some((item) => (
      item.group_id === selectedWechatReportPromptGroupId.value
      && item.report_type === selectedWechatReportPromptType.value
    ))
    if (!hasSelectedAdapter) selectedWechatReportPromptType.value = 'group_context'
    const current = wechatReportPrompts.value.find((item) => (
      item.group_id === selectedWechatReportPromptGroupId.value
      && item.report_type === selectedWechatReportPromptType.value
    ))
    wechatReportPromptText.value = current?.template || ''
  }

  async function loadWechatReportPrompts() {
    loadingWechatReportPrompts.value = true
    try {
      const response = await request.get(`${apiBase}/wechat-report-prompts`, { timeout: 10000 })
      wechatReportPrompts.value = Array.isArray(response.data) ? response.data : []
      syncWechatReportPromptEditor()
    } catch (error) {
      notify.error(errorMessage(error, '无法读取分组报告提示词'))
    } finally {
      loadingWechatReportPrompts.value = false
    }
  }

  function selectWechatReportPromptGroup(groupId) {
    selectedWechatReportPromptGroupId.value = groupId
    syncWechatReportPromptEditor()
  }

  function selectWechatReportPromptType(reportType) {
    selectedWechatReportPromptType.value = reportType
    syncWechatReportPromptEditor()
  }

  async function saveWechatReportPrompt() {
    const groupId = selectedWechatReportPromptGroupId.value
    const reportType = selectedWechatReportPromptType.value
    const template = wechatReportPromptText.value.trim()
    if (!groupId || !template) {
      notify.warning('请选择分组并填写提示词')
      return false
    }
    savingWechatReportPrompt.value = true
    try {
      await request.put(
        `${apiBase}/wechat-report-groups/${encodeURIComponent(groupId)}/prompts/${encodeURIComponent(reportType)}`,
        { template },
        { timeout: 10000 },
      )
      await loadWechatReportPrompts()
      notify.success('区间报告提示词已保存')
      return true
    } catch (error) {
      notify.error(errorMessage(error, '保存报告提示词失败'))
      return false
    } finally {
      savingWechatReportPrompt.value = false
    }
  }

  return {
    loadWechatReportPrompts,
    loadingWechatReportPrompts,
    saveWechatReportPrompt,
    savingWechatReportPrompt,
    selectWechatReportPromptGroup,
    selectWechatReportPromptType,
    selectedWechatReportPromptGroupId,
    selectedWechatReportPromptType,
    syncWechatReportPromptEditor,
    wechatReportPromptText,
    wechatReportPrompts,
  }
}
