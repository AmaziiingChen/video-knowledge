export function normalizeTranscriptSegments(segments, fallbackTranscript = '') {
  const normalized = (Array.isArray(segments) ? segments : [])
    .map((segment, index) => ({
      position: segment.position ?? index,
      start_seconds: segment.start_seconds,
      text: segment.text || '',
      approximate: Boolean(segment.approximate),
    }))
    .filter((segment) => segment.text)
  if (normalized.length) return normalized
  const transcript = String(fallbackTranscript || '').trim()
  return transcript ? [{ position: 0, start_seconds: 0, text: transcript, approximate: true }] : []
}

export function mediaTranscriptState({ isTimedMedia, contentStatus, segments, fallbackTranscript, taskStatus, taskStep } = {}) {
  const timelineSegments = normalizeTranscriptSegments(segments, fallbackTranscript)
  const hasTimeline = Boolean(isTimedMedia) && timelineSegments.length > 0
  const processing = ['queued', 'running', 'processing'].includes(String(taskStatus || '').toLowerCase())
    || String(contentStatus || '').toLowerCase() === 'processing'
  const showGeneration = Boolean(isTimedMedia) && !hasTimeline && processing
  const step = String(taskStep || '').toLowerCase()
  const label = ['info', 'parse', 'subtitle', 'fetch_subtitle'].includes(step) ? '正在获取字幕'
    : step === 'download' ? '正在准备字幕'
      : step === 'extract_audio' ? '正在提取音频'
        : step === 'transcribe' ? '正在转写音频'
          : ['summarize', 'save'].includes(step) ? '正在整理字幕文本'
            : '正在准备字幕'
  const description = step === 'download' ? '下载与字幕获取会并行进行，首段文本就绪后会立即显示。'
    : step === 'extract_audio' ? '音频准备完成后将立刻开始转写。'
      : step === 'transcribe' ? '字幕会按片段出现，无需等待整段音频完成。'
        : '首段文本就绪后会立即显示。'
  return { timelineSegments, hasTimeline, showGeneration, hasWorkspace: hasTimeline || showGeneration, label, description }
}

export function timelineSegmentKey(tabId, segment) {
  return `${tabId}:${segment.position}`
}

export function activeTimelineSegmentKey({ tabId, activeTabId, segments, playbackTime } = {}) {
  if (!tabId || tabId !== activeTabId) return ''
  const current = Number(playbackTime)
  if (!Number.isFinite(current)) return ''
  const active = (segments || []).find((segment, index) => {
    const start = Number(segment.start_seconds)
    if (!Number.isFinite(start) || current < start) return false
    const next = Number(segments[index + 1]?.start_seconds)
    return !Number.isFinite(next) || current < next
  })
  return active ? timelineSegmentKey(tabId, active) : ''
}

export function formatTimelineTime(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value)) return '--:--'
  const total = Math.max(0, Math.floor(value))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
