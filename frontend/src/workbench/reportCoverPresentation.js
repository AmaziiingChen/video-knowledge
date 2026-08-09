export function reportCoverVersions(history) {
  return Array.isArray(history?.covers) ? history.covers : []
}

export function reportCoverIndex(history) {
  const covers = reportCoverVersions(history)
  const activeId = String(history?.active_cover_id || '')
  const index = covers.findIndex((cover) => String(cover?.id || '') === activeId)
  return index >= 0 ? index : Math.max(0, covers.length - 1)
}

export function reportCoverUrl(history, fallbackUrl = '') {
  return reportCoverVersions(history)[reportCoverIndex(history)]?.url || fallbackUrl
}

export function adjacentReportCover(history, direction, { busy = false } = {}) {
  if (busy) return null
  const covers = reportCoverVersions(history)
  const nextIndex = reportCoverIndex(history) + Number(direction || 0)
  return nextIndex >= 0 && nextIndex < covers.length ? covers[nextIndex] : null
}
