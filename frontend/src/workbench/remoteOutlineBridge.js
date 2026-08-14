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
    let collectTimer = 0
    const text = (value, maximum) => String(value || '').replace(/\\s+/gu, ' ').trim().slice(0, maximum)
    const visible = (element) => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
    }
    const richHeadingCandidates = (root) => {
      const bodyFontSize = Number.parseFloat(window.getComputedStyle(root).fontSize) || 16
      const seen = new Set()
      return [...root.querySelectorAll('[role="heading"], p, strong, b')].filter((element) => {
        if (!visible(element)) return false
        const value = text(element.innerText, 120)
        const length = Array.from(value).length
        if (length < 2 || length > 80 || seen.has(value)) return false
        const style = window.getComputedStyle(element)
        const tag = element.tagName
        const parentText = text(element.parentElement?.innerText, 120)
        const isExplicitHeading = element.getAttribute('role') === 'heading'
        const isStandaloneStrong = ['STRONG', 'B'].includes(tag) && parentText === value
        const hasOnlyStrongChild = tag === 'P'
          && element.children.length === 1
          && ['STRONG', 'B'].includes(element.firstElementChild?.tagName)
        const isNumberedSection = /^(?:\\d{1,2}[.、]|[一二三四五六七八九十]{1,3}[、.：:]|第.{1,12}[章节部分]|[（(][一二三四五六七八九十\\d]{1,3}[）)])/u.test(value)
        const fontSize = Number.parseFloat(style.fontSize) || bodyFontSize
        const fontWeight = Number.parseInt(style.fontWeight, 10) || 400
        const isVisuallyProminent = fontWeight >= 600 && fontSize >= bodyFontSize * 1.05
        if (!isExplicitHeading && !isStandaloneStrong && !hasOnlyStrongChild && !isNumberedSection && !isVisuallyProminent) return false
        seen.add(value)
        return true
      })
    }
    const collect = () => {
      const articleRoot = document.querySelector('#js_content, article, main') || document.body
      let candidates = [...articleRoot.querySelectorAll('h1, h2, h3, h4')]
      if (candidates.length < 2 && articleRoot !== document.body) candidates = [...document.querySelectorAll('h1, h2, h3, h4')]
      candidates = candidates.filter((element) => visible(element) && Boolean(text(element.innerText, 120)))
      if (candidates.length < 2) candidates = richHeadingCandidates(articleRoot)
      headings = candidates.slice(0, 80)
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
          level: Number(element.getAttribute('aria-level')) || Number(element.tagName.slice(1)) || 2,
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
    const scheduleOutline = () => {
      if (collectTimer) window.clearTimeout(collectTimer)
      collectTimer = window.setTimeout(() => { collectTimer = 0; publishOutline() }, 240)
    }
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
    if (window.MutationObserver && document.body) {
      new MutationObserver(scheduleOutline).observe(document.body, { childList: true, subtree: true })
    }
    publishOutline()
    window.setTimeout(publishOutline, 900)
  })()`
}
