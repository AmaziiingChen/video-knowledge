import axios from 'axios'

const API = 'http://127.0.0.1:8000/api'
const ACTIVE_STATUSES = new Set(['queued', 'running', 'paused'])

export async function enqueueSourceSyncTask(payload) {
  const response = await axios.post(`${API}/source-sync-tasks`, payload, { timeout: 10000 })
  return response.data
}

export function observeSourceSyncTask(taskId, { onUpdate, onSucceeded, onFailed, intervalMs = 1200 } = {}) {
  let stopped = false
  let timer = null

  const poll = async () => {
    if (stopped) return
    try {
      const response = await axios.get(`${API}/tasks/${encodeURIComponent(taskId)}`, { timeout: 10000 })
      const task = response.data || {}
      onUpdate?.(task)
      if (ACTIVE_STATUSES.has(task.status)) {
        timer = setTimeout(poll, intervalMs)
        return
      }
      if (task.status === 'succeeded') onSucceeded?.(task.source_sync_result || {}, task)
      else onFailed?.(task.error || '来源同步失败', task)
    } catch (error) {
      onFailed?.(error.response?.data?.detail || error.message || '无法读取同步状态')
    }
  }

  void poll()
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}
