const STORAGE_KEY = 'knowledgehub.article-preview-cache.v1'
const MAX_ENTRIES = 30
const MAX_BYTES = 8 * 1024 * 1024

function safeStorage(storage) {
  return storage || globalThis.localStorage
}

function loadEntries(storage) {
  try {
    const parsed = JSON.parse(safeStorage(storage).getItem(STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter((entry) => entry && entry.contentItemId && entry.preview) : []
  } catch {
    return []
  }
}

function saveEntries(entries, storage) {
  try {
    safeStorage(storage).setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // The in-memory preview remains usable when the browser storage quota is full.
  }
}

function entrySize(entry) {
  return JSON.stringify(entry).length
}

export function readArticlePreviewCache(contentItemId, updatedAt, storage) {
  if (!contentItemId) return null
  const entry = loadEntries(storage).find((candidate) => (
    candidate.contentItemId === contentItemId
    && candidate.updatedAt === (updatedAt || '')
  ))
  return entry?.preview || null
}

export function writeArticlePreviewCache(contentItem, preview, storage) {
  if (!contentItem?.id || !preview?.html) return
  const entry = {
    contentItemId: contentItem.id,
    updatedAt: contentItem.updated_at || '',
    savedAt: Date.now(),
    preview,
  }
  const entries = [
    entry,
    ...loadEntries(storage).filter((candidate) => candidate.contentItemId !== contentItem.id),
  ]
  let retained = entries.slice(0, MAX_ENTRIES)
  while (retained.length > 1 && retained.reduce((total, candidate) => total + entrySize(candidate), 0) > MAX_BYTES) {
    retained = retained.slice(0, -1)
  }
  saveEntries(retained, storage)
}

export function removeArticlePreviewCache(contentItemId, storage) {
  if (!contentItemId) return
  saveEntries(loadEntries(storage).filter((entry) => entry.contentItemId !== contentItemId), storage)
}
