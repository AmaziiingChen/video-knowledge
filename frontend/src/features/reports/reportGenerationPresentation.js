const integerFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 })

export function formatReportCount(value) {
  const count = Number(value)
  return integerFormatter.format(Number.isFinite(count) ? Math.max(0, count) : 0)
}

export function formatReportDateRange(windowStart, windowEnd) {
  const start = new Date(windowStart || '')
  const end = new Date(windowEnd || '')
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return '时间范围待确认'

  const startParts = dateTimeParts(start)
  const endParts = dateTimeParts(end)
  const startLabel = `${startParts.year}年${startParts.month}月${startParts.day}日 ${startParts.time}`
  const endLabel = startParts.year === endParts.year
    ? `${endParts.month}月${endParts.day}日 ${endParts.time}`
    : `${endParts.year}年${endParts.month}月${endParts.day}日 ${endParts.time}`
  return `${startLabel} — ${endLabel}`
}

export function formatReportTaskWindow(windowStart, windowEnd) {
  const start = new Date(windowStart || '')
  const end = new Date(windowEnd || '')
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return ''

  const startParts = dateTimeParts(start)
  const endParts = dateTimeParts(end)
  const sameDate = startParts.year === endParts.year
    && startParts.month === endParts.month
    && startParts.day === endParts.day
  if (sameDate) {
    return `${startParts.month}/${startParts.day} ${startParts.time}–${endParts.time}`
  }
  const endDate = startParts.year === endParts.year
    ? `${endParts.month}/${endParts.day}`
    : `${endParts.year}/${endParts.month}/${endParts.day}`
  return `${startParts.month}/${startParts.day} ${startParts.time}–${endDate} ${endParts.time}`
}

export function reportCallPlan(preflight = {}) {
  const calls = preflight?.expected_calls || {}
  const summaryCalls = Number(calls.summary_calls)
  const hasSummaryCallEstimate = calls.summary_calls !== null
    && calls.summary_calls !== undefined
    && Number.isFinite(summaryCalls)
    && summaryCalls >= 0
  return [
    {
      label: '单篇摘要',
      detail: hasSummaryCallEstimate
        ? `${formatReportCount(summaryCalls)} 次 · Flash Thinking`
        : '将在任务启动后按缓存状态决定 · Flash Thinking',
    },
    {
      label: '栏目规划',
      detail: `${calls.planner_calls || '固定 1 次；结构问题由代码局部规范化'} · Pro Thinking`,
    },
    {
      label: '分栏写作',
      detail: `${calls.section_writer_calls || '由栏目数决定，每栏 1 次'} · Flash Thinking`,
    },
    {
      label: '概览与校对',
      detail: `概览 ${formatReportCount(calls.overview_calls ?? 1)} 次，引用局部校对最多 ${formatReportCount(calls.max_citation_repair_calls ?? 1)} 次 · Flash Thinking`,
    },
  ]
}

function dateTimeParts(value) {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(value)
  const read = (type) => parts.find((part) => part.type === type)?.value || ''
  return {
    year: read('year'),
    month: read('month'),
    day: read('day'),
    time: `${read('hour')}:${read('minute')}`,
  }
}
