import { boundedTaskProgress } from './processLogTaskState.js'

export function finiteMetric(value) {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatLogMetrics(item, formatTokenCount, includeModel = true) {
  const parts = []
  if (includeModel && item.model) parts.push(item.model)
  const callCount = finiteMetric(item.call_count)
  if (callCount !== null && callCount > 0) {
    const prefix = String(item.task_id || '').startsWith('report:') ? '累计 ' : ''
    parts.push(`${prefix}${callCount} 次调用`)
  }
  const promptTokens = finiteMetric(item.prompt_tokens)
  const completionTokens = finiteMetric(item.completion_tokens)
  const totalTokens = finiteMetric(item.total_tokens) ?? (promptTokens !== null && completionTokens !== null ? promptTokens + completionTokens : null)
  if (promptTokens !== null || completionTokens !== null) {
    parts.push(`输入 ${promptTokens !== null ? formatTokenCount(promptTokens) : '—'} · 输出 ${completionTokens !== null ? formatTokenCount(completionTokens) : '—'}`)
  } else if (totalTokens !== null && totalTokens > 0) {
    parts.push(`${formatTokenCount(totalTokens)} token`)
  }
  if (!includeModel && !parts.length && item.model) return item.model
  return parts.join(' · ')
}

function formatLogCost(value) {
  const cost = finiteMetric(value)
  if (cost === null || cost <= 0) return '0.0000'
  return cost < 0.0001 ? '<0.0001' : cost.toFixed(4)
}

function summarizeUsage({ callCount, promptTokens, completionTokens, estimatedCost, unreportedCount = 0 }, formatTokenCount) {
  if (!callCount && !promptTokens && !completionTokens) return null
  const label = [callCount && `AI ${callCount} 次`, (promptTokens || completionTokens) && `输入 ${formatTokenCount(promptTokens || 0)}`, (promptTokens || completionTokens) && `输出 ${formatTokenCount(completionTokens || 0)}`, estimatedCost !== null && estimatedCost !== undefined && `¥${formatLogCost(estimatedCost)}`].filter(Boolean).join(' · ')
  const detail = [callCount && `${callCount} 次 AI 调用`, `输入 ${formatTokenCount(promptTokens || 0)}`, `输出 ${formatTokenCount(completionTokens || 0)}`, estimatedCost !== null && estimatedCost !== undefined && `本机估算 ¥${formatLogCost(estimatedCost)}`, unreportedCount && `${unreportedCount} 次未返回用量`].filter(Boolean).join(' · ')
  return { label, detail }
}

export function usageForTask(task, logs, formatTokenCount) {
  const taskCalls = Array.isArray(task?.ai_calls) ? task.ai_calls : []
  const reportedCalls = taskCalls.filter((call) => finiteMetric(call?.prompt_tokens) !== null || finiteMetric(call?.completion_tokens) !== null)
  if (taskCalls.length) return summarizeUsage({ callCount: taskCalls.length, promptTokens: reportedCalls.reduce((sum, call) => sum + (finiteMetric(call.prompt_tokens) || 0), 0), completionTokens: reportedCalls.reduce((sum, call) => sum + (finiteMetric(call.completion_tokens) || 0), 0), estimatedCost: taskCalls.reduce((sum, call) => sum + (finiteMetric(call.estimated_cost) || 0), 0), unreportedCount: taskCalls.length - reportedCalls.length }, formatTokenCount)
  const metricLogs = logs.filter((item) => finiteMetric(item.call_count) !== null || finiteMetric(item.prompt_tokens) !== null || finiteMetric(item.completion_tokens) !== null)
  if (!metricLogs.length) return null
  const latest = metricLogs.at(-1)
  const costLog = [...metricLogs].reverse().find((item) => finiteMetric(item.estimated_cost) !== null)
  return summarizeUsage({ callCount: finiteMetric(latest.call_count) || 0, promptTokens: finiteMetric(latest.prompt_tokens) || 0, completionTokens: finiteMetric(latest.completion_tokens) || 0, estimatedCost: finiteMetric(costLog?.estimated_cost) }, formatTokenCount)
}

export function logOutcomeLabel(item, index, logs, task) {
  if (item.type === 'error') return '失败'
  if (item.type === 'warn') return /重试|retry/i.test(String(item.msg || '')) ? '重试' : '警告'
  return index === logs.length - 1 && task?.status === 'succeeded' ? '完成' : ''
}

export function taskProgressLabel(task) {
  if (task?.persistence_error) return '本地保存失败'
  if (task?.status === 'succeeded') return '已完成'
  if (task?.status === 'failed') return '失败'
  if (task?.status === 'cancelled') return '已取消'
  if (task?.status === 'paused') return '已暂停'
  if (task?.status === 'queued') return '等待中'
  const percent = boundedTaskProgress(task)
  return percent !== null ? `${percent}%` : '处理中'
}

export function taskHeaderStatus(task, statusLabel) {
  const status = statusLabel(task?.status)
  const progress = taskProgressLabel(task)
  return status === progress ? status : `${status} · ${progress}`
}

export function taskStageLabel(task, stepLabel) {
  if (task?.status === 'succeeded' && (!task.step || task.step === 'queued')) return '完成'
  if (task?.status === 'failed' && (!task.step || task.step === 'queued')) return '失败'
  return stepLabel(task?.step || 'queued')
}
