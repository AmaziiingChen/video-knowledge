export function defaultCustomReportWindow(now = new Date()) {
  const end = new Date(now)
  const start = new Date(end)
  start.setHours(0, 0, 0, 0)
  return [start.getTime(), end.getTime()]
}


export function normalizeReportWindow(value) {
  if (!Array.isArray(value) || value.length !== 2) return []
  return value.map((item) => {
    if (item === null || item === undefined || item === '') return Number.NaN
    if (item instanceof Date) return item.getTime()
    const timestamp = Number(item)
    return Number.isFinite(timestamp) ? timestamp : Number.NaN
  })
}


export function reportWindowDates(value) {
  const timestamps = normalizeReportWindow(value)
  if (timestamps.length !== 2 || timestamps.some((item) => !Number.isFinite(item))) return []
  const dates = timestamps.map((item) => new Date(item))
  return dates.every((item) => !Number.isNaN(item.getTime())) ? dates : []
}


export function validateCustomReportWindow(value) {
  const dates = reportWindowDates(value)
  if (dates.length !== 2) return '请选择完整的开始和结束时间'
  const [start, end] = dates
  if (end <= start) return '结束时间必须晚于开始时间'
  return ''
}
