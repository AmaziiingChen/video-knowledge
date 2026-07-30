export function mergeUniqueContentItems(currentItems, incomingItems) {
  const merged = [...currentItems]
  const knownIds = new Set(currentItems.map((item) => item.id))
  for (const item of incomingItems) {
    if (knownIds.has(item.id)) continue
    knownIds.add(item.id)
    merged.push(item)
  }
  return merged
}

export function taskContentSnapshot(task) {
  return `${task?.status || ''}|${task?.content_item_id || ''}`
}

export function shouldRefreshContentForTask(task, previousSnapshot, queueInitialized, terminalStatuses) {
  if (!queueInitialized || !task?.content_item_id) return false
  if (!terminalStatuses.has(task.status)) return false
  return previousSnapshot !== taskContentSnapshot(task)
}
