import { stripMarkdownMetadata } from '../../utils/markdownMetadata.js'

const GENERATED_SUMMARY_PLACEHOLDER = '<!-- 由应用生成；人工编辑内容将被保留。 -->'

/** Return assistant-owned summary text from a canonical source document. */
export function assistantSummaryFromMarkdown(markdown) {
  const content = stripMarkdownMetadata(String(markdown || ''))
  const canonical = content.match(/^## AI 摘要\s*\r?\n([\s\S]*)$/mu)
  if (canonical) {
    return canonical[1]
      // With an empty summary the conversation heading starts at index zero
      // of this capture, so it must not be treated as a real summary.
      .replace(/(?:^|\n)## 追问记录\s*[\s\S]*$/mu, '')
      .replace(GENERATED_SUMMARY_PLACEHOLDER, '')
      .trim()
  }

  // Old drafts placed the generated summary between the title and a collapsed
  // source-text block. Keep that compatible path without treating arbitrary
  // Markdown source material as an assistant summary.
  const sourceDetails = content.search(/\n<details>\s*\r?\n<summary>(?:原文正文|原始转写文本)<\/summary>/iu)
  if (sourceDetails >= 0) {
    const legacySummary = content.slice(0, sourceDetails)
      .replace(/^# [^\r\n]+\r?\n(?:\r?\n)*/u, '')
      .replace(/\n## 追问记录[\s\S]*$/u, '')
      .trim()
    if (legacySummary) return legacySummary
  }

  return ''
}

/** Remove the durable sidebar conversation, leaving document content intact. */
export function documentMarkdownWithoutConversation(markdown) {
  return stripMarkdownMetadata(String(markdown || ''))
    .replace(/\n## 追问记录\s*[\s\S]*$/mu, '')
    .trim()
}

/**
 * Return source material for the center reader.  AI summaries and the durable
 * conversation remain available to the assistant, search, and saved Markdown,
 * but are not part of the reader's original document.
 */
export function sourceMarkdownForCenter(markdown) {
  return documentMarkdownWithoutConversation(markdown)
    .replace(/\n## AI 摘要\s*[\s\S]*$/mu, '')
    .trim()
}

/**
 * Return a generated report's center-document content.
 *
 * Older reports stored their body under `AI 摘要`; that was a storage label,
 * not a request to render the report in the assistant sidebar.  Keep the body
 * in the center while transparently accepting that historical format.
 */
export function reportMarkdownForCenter(markdown) {
  return documentMarkdownWithoutConversation(markdown)
    .replace(/^## AI 摘要\s*\r?\n/mu, '')
    .replace(/^## 报告正文\s*\r?\n/mu, '')
    .trim()
}
