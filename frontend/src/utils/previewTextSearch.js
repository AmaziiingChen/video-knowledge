const HIGHLIGHT_SELECTOR = 'mark[data-preview-find-highlight]'

function normalizedQuery(value) {
  return String(value || '').trim().toLocaleLowerCase()
}

export function clearPreviewTextHighlights(root) {
  if (!root?.querySelectorAll) return
  for (const mark of root.querySelectorAll(HIGHLIGHT_SELECTOR)) {
    mark.replaceWith(root.ownerDocument.createTextNode(mark.textContent || ''))
  }
  root.normalize?.()
}

export function highlightPreviewText(root, value, { limit = 500 } = {}) {
  if (!root?.ownerDocument) return { matches: [], truncated: false }

  clearPreviewTextHighlights(root)
  const query = normalizedQuery(value)
  if (!query) return { matches: [], truncated: false }

  const nodeFilter = root.ownerDocument.defaultView?.NodeFilter || globalThis.NodeFilter
  if (!nodeFilter) return { matches: [], truncated: false }

  const walker = root.ownerDocument.createTreeWalker(root, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement
      if (!node.nodeValue?.trim() || !parent) return nodeFilter.FILTER_REJECT
      if (parent.closest('script, style, noscript, textarea, input, select, option, mark[data-preview-find-highlight]')) {
        return nodeFilter.FILTER_REJECT
      }
      return nodeFilter.FILTER_ACCEPT
    },
  })
  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)

  const matches = []
  let truncated = false
  for (const node of nodes) {
    const text = node.nodeValue || ''
    const lowerText = text.toLocaleLowerCase()
    const positions = []
    let index = lowerText.indexOf(query)
    while (index >= 0) {
      positions.push(index)
      if (matches.length + positions.length >= limit) {
        truncated = lowerText.indexOf(query, index + query.length) >= 0 || nodes.indexOf(node) < nodes.length - 1
        break
      }
      index = lowerText.indexOf(query, index + query.length)
    }
    if (!positions.length) continue

    const fragment = root.ownerDocument.createDocumentFragment()
    let cursor = 0
    for (const position of positions) {
      if (position > cursor) fragment.append(root.ownerDocument.createTextNode(text.slice(cursor, position)))
      const mark = root.ownerDocument.createElement('mark')
      mark.dataset.previewFindHighlight = ''
      mark.className = 'preview-find-highlight'
      mark.textContent = text.slice(position, position + query.length)
      fragment.append(mark)
      matches.push(mark)
      cursor = position + query.length
    }
    if (cursor < text.length) fragment.append(root.ownerDocument.createTextNode(text.slice(cursor)))
    node.replaceWith(fragment)
    if (matches.length >= limit) break
  }

  return { matches, truncated }
}
