const CITATION_GROUP_AFTER_PUNCTUATION = /([。！？；：，、.!?;:,])[ \t]*((?:\[\^[A-Za-z0-9_-]+\])(?:[ \t]*\[\^[A-Za-z0-9_-]+\])*)/g
const SOURCE_CHANNELS = new Set(['微信公众号', '公文通', '学院官网', '校园官网', '微信小程序', 'B站', '抖音', 'RSS订阅'])

export function moveMarkdownCitationsBeforePunctuation(markdown) {
  return String(markdown || '').replace(
    CITATION_GROUP_AFTER_PUNCTUATION,
    (_match, punctuation, citations) => `${citations.replace(/[ \t]+/g, '')}${punctuation}`
  )
}

export function footnotePreviewMetadata(definition) {
  const metadata = footnoteDefinitionMetadata(definition)
  return {
    title: limitPreviewText(metadata.title || '未命名文章', 120),
    metadata: limitPreviewText([
      metadata.source || '来源未知',
      metadata.detail,
      metadata.date,
    ].filter(Boolean).join(' · '), 120),
  }
}

export function footnoteDefinitionMetadata(definition) {
  const rawDefinition = String(definition || '').trim()
  const linkMatch = /\[([\s\S]*?)\]\((<[^>]+>|[^)]+)\)/.exec(rawDefinition)
  if (!linkMatch) {
    return {
      title: '未命名文章',
      source: '来源未知',
      detail: '',
      date: '',
      href: '',
      destination: '',
    }
  }

  const firstTitleLine = String(linkMatch[1] || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || ''
  const leadingMetadata = splitFootnoteParts(rawDefinition.slice(0, linkMatch.index))
  const trailingMetadata = splitFootnoteParts(rawDefinition.slice(linkMatch.index + linkMatch[0].length))
  const metadata = leadingMetadata.length || trailingMetadata.length
    // Canonical footnotes keep the complete article title inside the Markdown
    // link. A pipe in that title is prose, not provenance punctuation.
    ? footnoteLabelMetadata([firstTitleLine, ...leadingMetadata, ...trailingMetadata].join(' · '), linkMatch[2])
    // Older compact footnotes placed title and provenance together in the link
    // label. Only their explicit middot delimiter may separate those fields.
    : compactLinkLabelMetadata(firstTitleLine, linkMatch[2])
  return {
    ...metadata,
    href: String(linkMatch[2] || '').replace(/^<|>$/g, '').trim(),
    destination: String(linkMatch[2] || '').trim(),
  }
}

function limitPreviewText(value, limit) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text
}

export function compactFootnoteDefinition(definition) {
  const rawDefinition = String(definition || '').trim()
  const metadata = footnoteDefinitionMetadata(rawDefinition)
  if (!metadata.href) return rawDefinition.replace(/\s+/g, ' ').trim()
  const title = limitPreviewText(metadata.title, 120)
  const normalizedLabel = [title, metadata.source, metadata.detail, metadata.date]
    .filter(Boolean)
    .join(' · ')
  return `[${normalizedLabel || title}](${metadata.destination || metadata.href})`
}

function splitFootnoteParts(value) {
  const normalized = String(value || '')
    .replace(/[｜|]/g, ' · ')
    .replace(/^\s*[—–-]\s*(.+?)[，,]\s*(\d{4}-\d{2}-\d{2}|日期未知)\s*$/, '$1 · $2')
    .replace(/^[\s·]+|[\s·]+$/g, '')
  return normalized
    .split(/\s*·\s*/)
    .map((part) => part.replace(/\\([\[\]\\])/g, '$1').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
}

function footnoteLabelMetadata(label, destination) {
  const segments = String(label || '')
    .split(/\s+·\s+/)
    .map((segment) => segment.trim())
    .filter(Boolean)
  const title = segments.shift() || '未命名文章'
  const hasPublishedDate = /^(?:\d{4}-\d{2}-\d{2}|日期未知)$/.test(segments.at(-1) || '')
  const date = hasPublishedDate ? segments.pop() : ''
  const channelIndex = segments.findIndex((segment) => SOURCE_CHANNELS.has(segment))
  const url = String(destination || '').replace(/^<|>$/g, '')
  let source = ''
  let detail = ''
  if (channelIndex >= 0) {
    source = segments[channelIndex]
    detail = segments.filter((_segment, index) => index !== channelIndex).join(' · ')
  } else if (/^https?:\/\/(?:[^/]+\.)?mp\.weixin\.qq\.com\//i.test(url)) {
    source = '微信公众号'
    detail = segments.join(' · ')
  } else {
    source = segments.shift() || '来源未知'
    detail = segments.join(' · ')
  }
  return { title, source, detail, date }
}

function compactLinkLabelMetadata(label, destination) {
  const segments = String(label || '')
    .split(/\s+·\s+/)
    .map((segment) => segment.replace(/\\([\[\]\\])/g, '$1').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
  const channelIndex = segments.findIndex((segment) => SOURCE_CHANNELS.has(segment))
  if (channelIndex < 0) return footnoteLabelMetadata(label, destination)

  const title = segments.slice(0, channelIndex).join(' · ') || '未命名文章'
  const source = segments[channelIndex]
  const details = segments.slice(channelIndex + 1)
  const date = /^(?:\d{4}-\d{2}-\d{2}|日期未知)$/.test(details.at(-1) || '') ? details.pop() : ''
  return { title, source, detail: details.join(' · '), date }
}
