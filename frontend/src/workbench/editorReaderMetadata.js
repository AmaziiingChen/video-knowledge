import {
  readableCharacterCount,
  reportBodyHtmlForCharacterCount,
} from '../utils/reportReadingStats.js'

export function sourceBodyForCharacterCount(markdown, headings) {
  const source = String(markdown || '').replace(/^---\s*\n[\s\S]*?\n---\s*\n?/u, '')
  const section = headings
    .map((heading) => heading.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'))
    .join('|')
  if (!section) return source
  const matched = new RegExp(`^##\\s+(?:${section})\\s*$\\n([\\s\\S]*?)(?=^##\\s+|(?![\\s\\S]))`, 'imu').exec(source)
  return (matched?.[1] || source)
    .replace(/^>\s*外部导入.*$/gmu, '')
    .replace(/^\[打开原始文件\]\([^\n]+\)$/gmu, '')
    .trim()
}

export function readerMetadataText({
  content,
  kind,
  timelineSegments = [],
  transcript = '',
  selectedMarkdownPreview = '',
  articlePreviewText = '',
  captureText = '',
  htmlToText,
}) {
  if (!content) return ''

  if (kind === 'timed-media') {
    return sourceBodyForCharacterCount(
      timelineSegments.map((segment) => segment.text).join('\n') || transcript,
      ['视频字幕或转写', '原始转写文本', '字幕', '转写'],
    )
  }

  if (kind === 'external-image') {
    return sourceBodyForCharacterCount(transcript, ['原文内容', 'OCR 正文'])
  }

  if (kind === 'article') {
    const parsedBody = sourceBodyForCharacterCount(
      transcript,
      ['原文内容', '文章正文', '正文内容'],
    )
    return parsedBody || articlePreviewText
  }

  if (kind === 'report' || kind === 'external-markdown') {
    return htmlToText(reportBodyHtmlForCharacterCount(selectedMarkdownPreview))
  }

  if (kind === 'mini-program-capture') {
    return captureText || htmlToText(selectedMarkdownPreview)
  }

  return transcript
}

export function formatReadableCharacterCount(value) {
  const count = readableCharacterCount(value)
  return count ? `${count.toLocaleString('zh-CN')} 字` : '—'
}

export function formatReaderDocumentSize(content, {
  selectedContentId,
  selectedMarkdownSizeBytes,
  formatBytes,
}) {
  const isCurrentDocument = String(content?.id || '') === String(selectedContentId || '')
  const liveMarkdownSize = isCurrentDocument ? Number(selectedMarkdownSizeBytes || 0) : 0
  const storedMarkdownSize = Number(content?.markdown_size_bytes || 0)
  const markdownSize = liveMarkdownSize || storedMarkdownSize
  return markdownSize > 0 ? formatBytes(markdownSize) : '—'
}
