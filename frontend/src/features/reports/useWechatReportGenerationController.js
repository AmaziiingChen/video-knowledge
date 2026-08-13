import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { consumeReportEventStream } from './reportEventStream.js'
import { formatReportTaskWindow } from './reportGenerationPresentation.js'

const REPORT_LABELS = Object.freeze({ daily: '日报', weekly: '周报', range: '区间报告' })

function reportPayload(reportType, options) {
  const payload = { report_type: reportType }
  if (options?.windowStart && options?.windowEnd) {
    payload.window_start = options.windowStart
    payload.window_end = options.windowEnd
    payload.include_history_context = options.includeHistoryContext !== false
  }
  payload.include_external_imports = options?.includeExternalImports === true
  if (options?.fileName) payload.file_name = options.fileName
  return payload
}

export function useWechatReportGenerationController({
  reportGroups,
  reportGroupApi,
  request = axios,
  consumeStream = consumeReportEventStream,
  formatTaskWindow = formatReportTaskWindow,
  notify = ElMessage,
  addLog,
  processLogOpen,
  refreshContentItems,
  refreshLibraryFolders,
  refreshAiTokenUsage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const wechatGeneratingGroupId = ref('')
  const wechatPreparingGroupId = ref('')
  const reportGenerationDialog = ref({
    visible: false,
    phase: 'checking',
    requestId: '',
    reportKey: '',
    reportLabel: '报告',
    groupName: '',
    preflight: null,
  })
  let requestSequence = 0
  let confirmationResolver = null
  let preflightRequest = null
  let preparingRequestId = ''

  function resolveConfirmation(value) {
    const resolve = confirmationResolver
    confirmationResolver = null
    resolve?.(value)
  }

  function openReportGenerationDialog({ requestId, reportKey, reportLabel, groupName }) {
    resolveConfirmation(false)
    reportGenerationDialog.value = {
      visible: true,
      phase: 'checking',
      requestId,
      reportKey,
      reportLabel,
      groupName,
      preflight: null,
    }
    return new Promise((resolve) => {
      confirmationResolver = resolve
    })
  }

  function confirmReportGenerationDialog() {
    if (!reportGenerationDialog.value.visible || reportGenerationDialog.value.phase !== 'ready') return
    reportGenerationDialog.value = { ...reportGenerationDialog.value, phase: 'submitting' }
    resolveConfirmation(true)
  }

  function cancelReportGenerationDialog() {
    const state = reportGenerationDialog.value
    if (!state.visible || state.phase === 'submitting') return
    if (preflightRequest?.requestId === state.requestId) preflightRequest.controller.abort()
    resolveConfirmation(false)
    reportGenerationDialog.value = { ...state, visible: false }
    if (preparingRequestId === state.requestId) {
      preparingRequestId = ''
      wechatPreparingGroupId.value = ''
    }
  }

  function dismissReportGenerationDialog(requestId) {
    if (reportGenerationDialog.value.requestId !== requestId) return
    resolveConfirmation(false)
    reportGenerationDialog.value = { ...reportGenerationDialog.value, visible: false }
  }

  function closeReportGenerationDialog(requestId) {
    if (reportGenerationDialog.value.requestId !== requestId) return
    reportGenerationDialog.value = { ...reportGenerationDialog.value, visible: false }
  }

  async function generateWeChatReport(groupId, reportType, options = {}) {
    if (wechatGeneratingGroupId.value || wechatPreparingGroupId.value) return
    const reportKey = `${groupId}:${reportType}`
    const reportLabel = REPORT_LABELS[reportType] || '汇总'
    const groupName = reportGroups.value.find((group) => group.id === groupId)?.name || '校园生活'
    const requestId = `report-confirm-${++requestSequence}`
    const payload = reportPayload(reportType, options)
    const preflightController = new AbortController()
    preflightRequest = { requestId, controller: preflightController }
    preparingRequestId = requestId
    wechatPreparingGroupId.value = reportKey
    const confirmation = openReportGenerationDialog({ requestId, reportKey, reportLabel, groupName })
    let preflight
    try {
      const response = await request.post(
        `${reportGroupApi}/${groupId}/preflight`,
        payload,
        { timeout: 30000, signal: preflightController.signal }
      )
      preflight = response.data || {}
      if (reportGenerationDialog.value.requestId !== requestId) return
      reportGenerationDialog.value = {
        ...reportGenerationDialog.value,
        phase: 'ready',
        groupName: preflight.group_name || groupName,
        preflight,
      }
      if (!(await confirmation)) return
    } catch (error) {
      dismissReportGenerationDialog(requestId)
      const canceled = axios.isCancel(error) || error?.code === 'ERR_CANCELED'
      if (!canceled) notify.error(errorMessage(error, '报告预检失败'))
      return
    } finally {
      if (preflightRequest?.requestId === requestId) preflightRequest = null
      if (preparingRequestId === requestId) {
        preparingRequestId = ''
        wechatPreparingGroupId.value = ''
      }
    }

    const taskId = `report:${reportType}:${Date.now()}`
    const windowLabel = formatTaskWindow(options.windowStart, options.windowEnd)
    const taskName = `${groupName} · ${windowLabel ? `${windowLabel} ${reportLabel}` : reportLabel}`
    wechatGeneratingGroupId.value = reportKey
    processLogOpen.value = true
    addLog(`开始生成${reportLabel}`, 'info', 'report_prepare', null, {
      task_id: taskId,
      task_name: taskName,
      task_status: 'running',
      task_progress: 0,
    })
    try {
      let receivedProgress = false
      const result = await consumeStream(`${reportGroupApi}/${groupId}/generate-stream`, payload, (event) => {
        if (!receivedProgress) {
          receivedProgress = true
          closeReportGenerationDialog(requestId)
        }
        addLog(event.message || '报告生成中', event.level || 'info', event.stage || 'report_prepare', event.elapsed_seconds ?? null, {
          task_id: taskId,
          task_name: taskName,
          task_status: event.level === 'error' ? 'failed' : 'running',
          task_progress: Number(event.progress || 0),
          model: event.model || null,
          call_count: Number(event.call_count || 0),
          prompt_tokens: event.prompt_tokens ?? null,
          completion_tokens: event.completion_tokens ?? null,
          total_tokens: event.total_tokens ?? null,
          input_chars: event.input_chars ?? null,
          output_chars: event.output_chars ?? null,
          estimated_cost: event.estimated_cost ?? null,
        })
      })
      closeReportGenerationDialog(requestId)
      const modeLabel = result?.generation_mode === 'campus_clustered' ? '，已完成事件聚类与引用审校' : ''
      addLog(`生成完成，共汇总 ${result?.source_count || 0} 篇文章${modeLabel}`, 'success', 'report_save', null, {
        task_id: taskId,
        task_name: taskName,
        task_status: 'succeeded',
        task_progress: 100,
        call_count: Number(result?.ai_token_usage?.call_count || 0),
        prompt_tokens: result?.ai_token_usage?.prompt_tokens ?? null,
        completion_tokens: result?.ai_token_usage?.completion_tokens ?? null,
        total_tokens: result?.ai_token_usage?.total_tokens ?? null,
        estimated_cost: result?.ai_token_usage?.estimated_cost ?? null,
      })
      notify.success(`已生成${reportLabel}，共汇总 ${result?.source_count || 0} 篇文章${modeLabel}`)
      await refreshContentItems()
      await refreshLibraryFolders()
    } catch (error) {
      closeReportGenerationDialog(requestId)
      const message = errorMessage(error, '生成报告失败')
      addLog(message, 'error', 'report_prepare', null, {
        task_id: taskId,
        task_name: taskName,
        task_status: 'failed',
        task_progress: 100,
      })
      notify.error(message)
    } finally {
      closeReportGenerationDialog(requestId)
      if (wechatGeneratingGroupId.value === reportKey) wechatGeneratingGroupId.value = ''
      void refreshAiTokenUsage()
    }
  }

  function disposeWechatReportGenerationController() {
    preflightRequest?.controller.abort()
    preflightRequest = null
    resolveConfirmation(false)
  }

  return {
    wechatGeneratingGroupId,
    wechatPreparingGroupId,
    reportGenerationDialog,
    generateWeChatReport,
    confirmReportGenerationDialog,
    cancelReportGenerationDialog,
    disposeWechatReportGenerationController,
  }
}
