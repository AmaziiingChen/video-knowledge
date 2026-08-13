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

// The task-list endpoint intentionally omits large transcripts and summaries.
// These are the small, durable milestones that tell the renderer when it is
// worth hydrating one task in full: a content record became available, a
// playable video arrived, or readable subtitle/transcript text completed.
// Do not use ``updated_at`` here: download telemetry and log lines change it
// frequently and would turn every queue poll into a heavy detail request.
export function progressiveTaskSnapshot(task) {
  const progress = task?.progress || {}
  const transcriptReady = Number(progress.transcribe || 0) >= 100
  const summaryStarted = Number(progress.summarize || 0) > 0
  return [
    task?.content_item_id || '',
    task?.status || '',
    task?.step || '',
    task?.video_path || '',
    transcriptReady ? 'transcript-ready' : '',
    summaryStarted ? 'summary-started' : '',
    `summary-${Number(task?.summary_length || task?.summary?.length || 0)}`,
    `reasoning-${Number(task?.reasoning_length || task?.reasoning_content?.length || 0)}`,
  ].join('|')
}

export function shouldHydrateProgressiveTask(task, previousSnapshot) {
  return Boolean(task?.content_item_id)
    && progressiveTaskSnapshot(task) !== previousSnapshot
}

export function shouldRefreshContentForTask(task, previousSnapshot, queueInitialized, terminalStatuses) {
  // Source synchronization creates new content without a single owning
  // content_item_id.  Refresh its bounded recent page at completion so RSS
  // unread badges update before the user opens that source folder.
  const createsLibraryContent = Boolean(task?.content_item_id) || task?.task_type === 'source_sync'
  if (!queueInitialized || !createsLibraryContent) return false
  if (!terminalStatuses.has(task.status)) return false
  return previousSnapshot !== taskContentSnapshot(task)
}
