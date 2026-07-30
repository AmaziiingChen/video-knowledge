export const REMOTE_READING_PROGRESS_PREFIX = '__knowledgehub_remote_reading_progress__:'

function finiteBoundedNumber(value, maximum) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > maximum) return null
  return numeric
}

export function parseRemoteReadingProgressMessage(message) {
  if (typeof message !== 'string' || !message.startsWith(REMOTE_READING_PROGRESS_PREFIX)) return null
  try {
    const payload = JSON.parse(message.slice(REMOTE_READING_PROGRESS_PREFIX.length))
    if (payload?.kind !== 'progress') return null
    const progress = finiteBoundedNumber(payload.progress, 100)
    const characterCount = finiteBoundedNumber(payload.characterCount, 10_000_000)
    if (progress === null || characterCount === null) return null
    return { progress: Math.round(progress), characterCount: Math.round(characterCount) }
  } catch {
    return null
  }
}

export function remoteReadingProgressBridgeScript(preferredCharacterCount = 0) {
  const prefix = JSON.stringify(REMOTE_READING_PROGRESS_PREFIX)
  const count = Math.max(0, Math.round(Number(preferredCharacterCount) || 0))
  return `(() => {
    if (window.__knowledgeHubRemoteReadingProgressBridgeInstalled) return
    window.__knowledgeHubRemoteReadingProgressBridgeInstalled = true
    const publish = () => {
      const root = document.scrollingElement || document.documentElement
      const range = Math.max(0, root.scrollHeight - root.clientHeight)
      const progress = range <= 1 ? 100 : Math.max(0, Math.min(100, Math.round((root.scrollTop / range) * 100)))
      const characterCount = ${count} || Array.from(String(document.body?.innerText || '').replace(/\\s+/gu, '')).length
      console.debug(${prefix} + JSON.stringify({ kind: 'progress', progress, characterCount }))
    }
    let scheduled = false
    const schedule = () => {
      if (scheduled) return
      scheduled = true
      window.requestAnimationFrame(() => { scheduled = false; publish() })
    }
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule, { passive: true })
    document.addEventListener('scroll', schedule, true)
    if (window.ResizeObserver && document.body) new ResizeObserver(schedule).observe(document.body)
    schedule()
  })()`
}
