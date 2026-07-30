const BARE_HTTP_URL_PATTERN = /https?:\/\/[^\s<>"'`]+/gi
const URL_TEXT_BOUNDARY_PATTERN = /[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u

export function normalizeBareExternalLinks(markdown) {
  const source = String(markdown || '')
  return source.replace(BARE_HTTP_URL_PATTERN, (candidate, offset) => {
    const previousCharacter = source[offset - 1] || ''
    const previousPair = source.slice(Math.max(0, offset - 2), offset)

    // Explicit Markdown links, autolinks and raw HTML already define their
    // own boundary and should be left to the Markdown parser.
    if (previousPair === '](' || /[<="']/.test(previousCharacter)) return candidate

    const boundaryIndex = candidate.search(URL_TEXT_BOUNDARY_PATTERN)
    if (boundaryIndex < 0) return candidate

    const href = candidate.slice(0, boundaryIndex)
    const trailingText = candidate.slice(boundaryIndex)
    return `<${href}>${trailingText}`
  })
}

export function isExternalLinkHref(href) {
  try {
    const url = new URL(String(href || ''))
    return ['http:', 'https:', 'mailto:'].includes(url.protocol)
  } catch {
    return false
  }
}
