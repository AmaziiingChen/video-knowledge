function citationId(citation) {
  return String(citation?.evidence_id || citation?.citation_id || '').trim()
}

function escapeMarkdown(value) {
  return String(value || '未命名内容').replace(/\[/g, '\\[').replace(/\]/g, '\\]')
}

/** Convert the answer model's evidence IDs into the shared Markdown footnotes. */
export function knowledgeAnswerMarkdown(answer, citations = []) {
  const ids = new Set(citations.map(citationId).filter(Boolean))
  const body = String(answer || '').replace(/\[([A-Za-z0-9_-]+)\]/g, (reference, id) => (
    ids.has(id) ? `[^${id}]` : reference
  ))
  const definitions = citations.map((citation) => {
    const id = citationId(citation)
    if (!id) return ''
    const title = escapeMarkdown(citation.title)
    const link = citation.source_url ? `[${title}](<${citation.source_url}>)` : title
    return `[^${id}]: ${link} · ${citation.source_label || '本地内容'} · ${citation.published_at || '日期未知'}`
  }).filter(Boolean).join('\n')
  return definitions ? `${body}\n\n${definitions}` : body
}
