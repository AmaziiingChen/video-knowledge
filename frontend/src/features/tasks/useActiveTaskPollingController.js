import { ElMessage } from 'element-plus'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useActiveTaskPollingController({
  running,
  cancelling,
  openSections,
  progressiveTaskSnapshots,
  terminalStatuses,
  applyTaskData,
  startTaskEventStream,
  stopTaskEventStream,
  hydrateProgressiveTask,
  revealWechatArticleSnapshot,
  revealVideoSnapshot,
  revealTranscriptSnapshot,
  syncCompletedTaskContent,
  addLog,
  isPipelineSummaryGenerating = () => false,
  request = axios,
  apiBase = API,
  notify = ElMessage,
  schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
  cancel = (timer) => globalThis.clearTimeout(timer),
} = {}) {
  let pollTimer = null
  let pollFailureCount = 0

  function stopPolling() {
    if (pollTimer) {
      cancel(pollTimer)
      pollTimer = null
    }
    stopTaskEventStream()
    pollFailureCount = 0
  }

  async function pollTask(taskId) {
    try {
      const response = await request.get(`${apiBase}/tasks/${taskId}`, { timeout: 10000 })
      pollFailureCount = 0
      const data = response.data
      applyTaskData(data)
      if (!terminalStatuses.has(data.status)) startTaskEventStream(taskId)
      const previousSnapshot = progressiveTaskSnapshots.get(data.task_id)
      await hydrateProgressiveTask(data, previousSnapshot)
      await revealWechatArticleSnapshot(data)
      await revealVideoSnapshot(data)
      await revealTranscriptSnapshot(data)

      if (terminalStatuses.has(data.status)) {
        running.value = false
        cancelling.value = false
        stopPolling()
        if (data.status === 'succeeded' && data.persistence_error) {
          addLog('处理结果已生成，但任务状态未能保存；重启后任务记录可能不完整', 'error')
          openSections.value = ['logs']
          await syncCompletedTaskContent(data.content_item_id)
          notify.error('处理已完成，但任务状态未保存')
        } else if (data.status === 'succeeded') {
          addLog('全流程完成！', 'success')
          await syncCompletedTaskContent(data.content_item_id)
          notify.success('处理完成')
        } else if (data.status === 'cancelled') {
          addLog('任务已取消', 'warn')
          openSections.value = ['logs']
          notify.warning('任务已取消')
        } else {
          addLog(`失败: ${data.error || '任务失败'}`, 'error')
          openSections.value = ['logs']
          notify.error(data.error || '任务失败')
        }
        return
      }

      pollTimer = schedule(pollTask.bind(null, taskId), isPipelineSummaryGenerating() ? 220 : 1500)
    } catch (error) {
      pollFailureCount += 1
      const message = error.message || '查询任务状态失败'
      const retryDelay = Math.min(10000, 1500 * pollFailureCount)
      if (pollFailureCount === 1 || pollFailureCount % 5 === 0) {
        addLog(`任务状态暂时不可达：${message}；${Math.round(retryDelay / 1000)} 秒后重试`, 'warn')
        openSections.value = ['logs']
      }
      pollTimer = schedule(pollTask.bind(null, taskId), retryDelay)
    }
  }

  return {
    stopPolling,
    pollTask,
  }
}
