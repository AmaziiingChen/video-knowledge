export const REMOTE_OUTLINE_PREFIX = '__knowledgehub_remote_outline__:'

function cleanText(value, maximum = 180) {
  return String(value || '').replace(/\s+/gu, ' ').trim().slice(0, maximum)
}

function normalizeEntry(entry, index) {
  const id = String(entry?.id || '').trim()
  const text = cleanText(entry?.text, 120)
  const level = Math.min(4, Math.max(1, Math.round(Number(entry?.level) || 2)))
  if (!id || !text) return null
  return {
    id: id.slice(0, 96),
    text,
    preview: cleanText(entry?.preview, 180),
    level,
    order: index,
  }
}

export function parseRemoteOutlineMessage(message) {
  if (typeof message !== 'string' || !message.startsWith(REMOTE_OUTLINE_PREFIX)) return null
  try {
    const payload = JSON.parse(message.slice(REMOTE_OUTLINE_PREFIX.length))
    if (payload?.kind === 'outline') {
      const entries = Array.isArray(payload.entries)
        ? payload.entries.slice(0, 80).map(normalizeEntry).filter(Boolean)
        : []
      return { kind: 'outline', entries, activeId: String(payload.activeId || '') }
    }
    if (payload?.kind === 'active') return { kind: 'active', activeId: String(payload.activeId || '') }
    return null
  } catch {
    return null
  }
}

export function remoteOutlineBridgeScript() {
  const prefix = JSON.stringify(REMOTE_OUTLINE_PREFIX)
  return `(() => {
    if (window.__knowledgeHubRemoteOutlineBridgeInstalled) return
    window.__knowledgeHubRemoteOutlineBridgeInstalled = true
    const send = (payload) => console.debug(${prefix} + JSON.stringify(payload))
    let headings = []
    let entries = []
    let scheduled = false
    const text = (value, maximum) => String(value || '').replace(/\\s+/gu, ' ').trim().slice(0, maximum)
    const collect = () => {
      const articleRoot = document.querySelector('#js_content, article, main') || document.body
      let candidates = [...articleRoot.querySelectorAll('h1, h2, h3, h4')]
      if (candidates.length < 2 && articleRoot !== document.body) candidates = [...document.querySelectorAll('h1, h2, h3, h4')]
      headings = candidates.filter((element) => {
        const style = window.getComputedStyle(element)
        return style.display !== 'none' && style.visibility !== 'hidden' && Boolean(text(element.innerText, 120))
      }).slice(0, 80)
      entries = headings.map((element, index) => {
        let preview = ''
        let sibling = element.nextElementSibling
        while (sibling && !/^H[1-4]$/.test(sibling.tagName) && preview.length < 180) {
          preview = text(preview + ' ' + (sibling.innerText || ''), 180)
          sibling = sibling.nextElementSibling
        }
        return {
          id: 'remote-outline-' + (index + 1),
          text: text(element.innerText, 120),
          preview,
          level: Number(element.tagName.slice(1)) || 2,
        }
      })
    }
    const activeId = () => {
      if (!headings.length) return ''
      const readingLine = Math.min(window.innerHeight * 0.3, 160)
      let active = entries[0]?.id || ''
      headings.forEach((heading, index) => { if (heading.getBoundingClientRect().top <= readingLine) active = entries[index]?.id || active })
      return active
    }
    const publishOutline = () => { collect(); send({ kind: 'outline', entries, activeId: activeId() }) }
    const publishActive = () => send({ kind: 'active', activeId: activeId() })
    const scheduleActive = () => {
      if (scheduled) return
      scheduled = true
      window.requestAnimationFrame(() => { scheduled = false; publishActive() })
    }
    window.__knowledgeHubRemoteOutlineScrollTo = (id) => {
      const index = entries.findIndex((entry) => entry.id === id)
      const heading = headings[index]
      if (!heading) return false
      heading.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return true
    }
    window.addEventListener('scroll', scheduleActive, { passive: true })
    window.addEventListener('resize', scheduleActive, { passive: true })
    publishOutline()
    window.setTimeout(publishOutline, 900)
  })()`
}
