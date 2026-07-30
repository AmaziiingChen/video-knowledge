export function tabIdForContent(itemId) {
  return `content:${itemId}`
}

export function makeContentTab(item) {
  return {
    id: tabIdForContent(item.id),
    type: 'content',
    content_item_id: item.id,
    title: item.title || item.canonical_source_id || '未命名内容',
    source_provider: item.source_provider,
    status: item.status,
    opened_at: new Date().toISOString()
  }
}

export function clampPaneWidth(value, min, max, fallback) {
  if (!Number.isFinite(value)) return fallback
  return Math.max(min, Math.min(max, Math.round(value)))
}

export function clampPanePercent(value, min, max, fallback) {
  if (!Number.isFinite(value)) return fallback
  return Math.max(min, Math.min(max, Number(value.toFixed(2))))
}
