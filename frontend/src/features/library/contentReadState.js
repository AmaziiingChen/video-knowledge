export function normalizeContentReadState(data) {
  const viewedContentIds = uniqueIds(data?.viewed_content_ids)
  const explicitlyUnreadContentIds = uniqueIds(data?.explicitly_unread_content_ids)
    .filter((id) => !viewedContentIds.includes(id))
  const viewedBefore = normalizeTimestamp(data?.viewed_before)

  return {
    initialized: Boolean(data?.initialized),
    viewedContentIds,
    explicitlyUnreadContentIds,
    viewedBefore,
    needsBaselineMigration: Boolean(data?.initialized) && !viewedBefore,
  }
}

export function contentIsUnread(item, {
  viewedContentIds = new Set(),
  explicitlyUnreadContentIds = new Set(),
  viewedBefore = '',
} = {}) {
  const id = String(item?.id || '')
  if (!id) return false
  if (explicitlyUnreadContentIds.has(id)) return true
  if (viewedContentIds.has(id)) return false

  const baseline = Date.parse(viewedBefore)
  const createdAt = Date.parse(item?.created_at || '')
  if (Number.isFinite(baseline) && Number.isFinite(createdAt) && createdAt <= baseline) {
    return false
  }
  return true
}

export function uniqueIds(ids) {
  return [...new Set((Array.isArray(ids) ? ids : []).map(String).filter(Boolean))]
}

function normalizeTimestamp(value) {
  const timestamp = Date.parse(value || '')
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : ''
}
