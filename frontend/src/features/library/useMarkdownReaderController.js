import { computed } from 'vue'

import { extractReportSourceStats } from '../../utils/reportSourceStats.js'
import { stripMarkdownMetadata } from '../../utils/markdownMetadata.js'

export function isForumCaptureDocument(item) {
  return Boolean(item && item.source_provider === 'wechat_miniprogram' && (
    item.content_type === 'forum_capture' || item.content_type === 'report'
  ))
}

export function isGeneratedReportDocument(item) {
  return Boolean(item && !isForumCaptureDocument(item) && (
    item.content_type === 'report' || item.source_provider === 'wechat_report'
  ))
}

export function isExternalMarkdownDocument(item) {
  if (!item) return false
  if (item.source_provider === 'local_markdown') return item.content_type === 'document'
  // Every retained local import writes its source into the canonical Markdown
  // document, including OCR and audio/video transcript results.
  return item.source_provider === 'local_file'
    && ['document', 'image', 'audio', 'video'].includes(item.content_type)
}

function stripForumCaptureMarkdownHeader(markdown) {
  return String(markdown || '').replace(/^\s*#\s+[^\n]+\r?\n+/u, '')
}

function extractSourceTextFromMarkdown(markdown) {
  const text = stripMarkdownMetadata(markdown || '')
  const detailsMatch = text.match(/<details>\s*<summary>(?:原文正文|原始转写文本)<\/summary>\s*([\s\S]*?)\s*<\/details>/iu)
  return detailsMatch ? detailsMatch[1].trim() : ''
}

export function useMarkdownReaderController({
  selectedContentItem,
  markdownState,
  render,
  stripReportHeader,
  documentWithoutConversation,
  reportForCenter,
  sourceForCenter,
} = {}) {
  function stripAssistantMarkdown(markdown) {
    return documentWithoutConversation(markdown)
      .replace(/\n## AI 摘要[\s\S]*$/u, '')
      .replace(/\n<details>[\s\S]*?<\/details>\s*$/iu, '')
      .trim()
  }

  const selectedMarkdownPreview = computed(() => {
    const item = selectedContentItem.value
    if (!item || !markdownState.markdown) return ''
    const isReport = isGeneratedReportDocument(item)
    const isForumCapture = isForumCaptureDocument(item)
    const isExternalMarkdown = isExternalMarkdownDocument(item)
    const markdown = isReport
      ? reportForCenter(markdownState.markdown)
      : isExternalMarkdown
        ? sourceForCenter(markdownState.markdown)
        : stripAssistantMarkdown(markdownState.markdown)
    return render(
      isReport
        ? stripReportHeader(markdown)
        : isForumCapture
          ? stripForumCaptureMarkdownHeader(markdown)
          : markdown,
    )
  })

  const selectedMarkdownSizeBytes = computed(() => {
    const persistedSize = Number(markdownState.markdown_size_bytes || 0)
    if (persistedSize > 0) return persistedSize
    const markdown = String(markdownState.markdown || '')
    return markdown ? new TextEncoder().encode(markdown).length : 0
  })

  const selectedReportSourceStats = computed(() => {
    const item = selectedContentItem.value
    if (!item || !markdownState.markdown || !isGeneratedReportDocument(item)) {
      return { analyzed: 0, referenced: 0 }
    }
    return extractReportSourceStats(markdownState.markdown)
  })

  const selectedMarkdownSourceText = computed(() => {
    const item = selectedContentItem.value
    if (!item || !markdownState.markdown) return ''
    if (isForumCaptureDocument(item)) return stripAssistantMarkdown(markdownState.markdown)
    if (isExternalMarkdownDocument(item)) return sourceForCenter(markdownState.markdown)
    return extractSourceTextFromMarkdown(markdownState.markdown)
  })

  return {
    selectedMarkdownPreview,
    selectedMarkdownSizeBytes,
    selectedReportSourceStats,
    selectedMarkdownSourceText,
  }
}
