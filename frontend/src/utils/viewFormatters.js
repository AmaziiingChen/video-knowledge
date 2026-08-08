import { marked } from 'marked'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import {
  compactFootnoteDefinition,
  footnoteDefinitionMetadata,
  footnotePreviewMetadata,
  moveMarkdownCitationsBeforePunctuation,
} from './markdownFootnotes.js'
import { isExternalLinkHref, normalizeBareExternalLinks } from './markdownLinks.js'
import { stripMarkdownMetadata } from './markdownMetadata.js'

export { stripMarkdownMetadata } from './markdownMetadata.js'

const MARKDOWN_RENDER_CACHE_LIMIT = 80
const markdownRenderCache = new Map()
const SAFE_HTML_TAGS = new Set([
  'a', 'b', 'blockquote', 'br', 'code', 'del', 'details', 'div', 'em', 'figcaption',
  'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'kbd', 'li',
  'mark', 'math', 'mfrac', 'mi', 'mn', 'mo', 'mrow', 'msqrt', 'mstyle', 'msub',
  'msubsup', 'msup', 'mtext', 'ol', 'p', 'pre', 's', 'section', 'semantics', 'span',
  'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
])
const DROP_HTML_TAGS = new Set(['embed', 'form', 'iframe', 'input', 'link', 'meta', 'object', 'script', 'style', 'svg'])
const SAFE_GLOBAL_ATTRIBUTES = new Set(['aria-describedby', 'aria-hidden', 'aria-label', 'class', 'id', 'role', 'title'])
const SAFE_MATH_ATTRIBUTES = new Set(['accent', 'columnalign', 'columnspacing', 'display', 'displaystyle', 'encoding', 'fence', 'form', 'lspace', 'mathvariant', 'minsize', 'movablelimits', 'rspace', 'rowalign', 'rowspacing', 'scriptlevel', 'separator', 'stretchy', 'symmetric', 'xmlns'])

function renderLatex(expression, displayMode) {
  return katex.renderToString(String(expression || '').trim(), {
    displayMode,
    throwOnError: false,
    strict: 'warn',
    trust: false,
    maxExpand: 1000,
    maxSize: 20,
    output: 'htmlAndMathml'
  })
}

function mathToken(raw, text, displayMode) {
  return { type: displayMode ? 'latexBlock' : 'latexInline', raw, text, displayMode }
}

const latexBlockExtension = {
  name: 'latexBlock',
  level: 'block',
  start(source) {
    const dollarIndex = source.indexOf('$$')
    const bracketIndex = source.indexOf('\\[')
    const candidates = [dollarIndex, bracketIndex].filter((index) => index >= 0)
    return candidates.length ? Math.min(...candidates) : undefined
  },
  tokenizer(source) {
    const dollarMatch = /^ {0,3}\$\$[ \t]*\n?([\s\S]+?)\n?[ \t]*\$\$(?:[ \t]*(?:\n|$))/.exec(source)
    if (dollarMatch) return mathToken(dollarMatch[0], dollarMatch[1], true)
    const bracketMatch = /^ {0,3}\\\[[ \t]*\n?([\s\S]+?)\n?[ \t]*\\\](?:[ \t]*(?:\n|$))/.exec(source)
    if (bracketMatch) return mathToken(bracketMatch[0], bracketMatch[1], true)
    return undefined
  },
  renderer(token) {
    return renderLatex(token.text, true)
  }
}

const latexInlineExtension = {
  name: 'latexInline',
  level: 'inline',
  start(source) {
    const dollarIndex = source.indexOf('$')
    const parenthesisIndex = source.indexOf('\\(')
    const candidates = [dollarIndex, parenthesisIndex].filter((index) => index >= 0)
    return candidates.length ? Math.min(...candidates) : undefined
  },
  tokenizer(source) {
    const dollarMatch = /^\$(?!\$|\s)((?:\\[\s\S]|[^\\$\n])*?[^\\\s])\$(?!\$)/.exec(source)
    if (dollarMatch) return mathToken(dollarMatch[0], dollarMatch[1], false)
    const parenthesisMatch = /^\\\(([\s\S]*?)\\\)/.exec(source)
    if (parenthesisMatch && parenthesisMatch[1].trim() && !parenthesisMatch[1].includes('\n')) {
      return mathToken(parenthesisMatch[0], parenthesisMatch[1], false)
    }
    return undefined
  },
  renderer(token) {
    return renderLatex(token.text, false)
  }
}

marked.use({ extensions: [latexBlockExtension, latexInlineExtension] })

function expandMarkdownFootnotes(markdown) {
  const scope = markdownFootnoteScope(markdown)
  const definitions = new Map()
  const previews = new Map()
  const bodyWithDefinitionsRemoved = String(markdown || '').replace(
    /(?:^|\n)\[\^([A-Za-z0-9_-]+)\]:[ \t]*([\s\S]*?)(?=\n\[\^[A-Za-z0-9_-]+\]:|\n{2,}(?=#{1,6}\s)|$)/g,
    (_match, id, definition) => {
      const normalizedDefinition = compactFootnoteDefinition(definition)
      const metadata = footnoteDefinitionMetadata(definition)
      definitions.set(id, { markdown: normalizedDefinition, metadata })
      previews.set(id, footnotePreviewMetadata(definition))
      return ''
    }
  )
  if (!definitions.size) return bodyWithDefinitionsRemoved
  const body = bodyWithDefinitionsRemoved.replace(
    /\n*#{1,6}\s*(?:参考来源|来源文章|AI 摘要|追问记录)\s*[\s\S]*$/i,
    ''
  )

  const orderedIds = []
  const occurrenceCounts = new Map()
  const withReferences = moveMarkdownCitationsBeforePunctuation(body).replace(
    /\[\^[A-Za-z0-9_-]+\](?:\s*\[\^[A-Za-z0-9_-]+\])*/g,
    (citationGroup) => {
      const ids = Array.from(citationGroup.matchAll(/\[\^([A-Za-z0-9_-]+)\]/g), (match) => match[1])
        .filter((id) => definitions.has(id))
      if (!ids.length) return citationGroup

      const references = ids.map((id) => {
        if (!orderedIds.includes(id)) orderedIds.push(id)
        const number = orderedIds.indexOf(id) + 1
        const occurrence = (occurrenceCounts.get(id) || 0) + 1
        occurrenceCounts.set(id, occurrence)
        const preview = previews.get(id) || { title: '未命名文章', metadata: '来源未知' }
        const previewId = `fnpreview-${scope}-${id}-${occurrence}`
        return `<a id="fnref-${scope}-${id}-${occurrence}" href="#fn-${scope}-${id}" aria-label="查看来源 ${number}" aria-describedby="${previewId}">${number}<span id="${previewId}" class="markdown-footnote-preview" role="tooltip"><span class="markdown-footnote-preview-title">${escapeHtml(preview.title)}</span><span class="markdown-footnote-preview-source">${escapeHtml(preview.metadata)}</span></span></a>`
      })
      return `<sup class="markdown-footnote-ref">${references.join('<span class="markdown-footnote-separator" aria-hidden="true">, </span>')}</sup>`
    }
  )
  if (!orderedIds.length) return withReferences

  const items = orderedIds.map((id) => {
    const definition = definitions.get(id)
    const metadata = definition?.metadata
    const label = [
      metadata?.title || '未命名文章',
      metadata?.detail || metadata?.source || '来源未知',
      metadata?.date || '日期未知',
    ].join(' · ')
    const href = String(metadata?.href || '')
    const content = isExternalLinkHref(href)
      ? `<a href="${escapeHtml(href)}">${escapeHtml(label)}</a>`
      : `<span>${escapeHtml(label)}</span>`
    return `<li id="fn-${scope}-${id}">${content}</li>`
  }).join('')
  return `${withReferences.trim()}\n\n<section class="markdown-footnotes" aria-label="参考来源"><ol>${items}</ol></section>`
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function markdownFootnoteScope(markdown) {
  let hash = 5381
  for (const character of String(markdown || '')) {
    hash = ((hash << 5) + hash) ^ character.charCodeAt(0)
  }
  return (hash >>> 0).toString(36)
}

export function statusLabel(status) {
  const labels = {
    idle: '未开始',
    inbox: '待处理',
    processing: '处理中',
    to_read: '待阅读',
    distilled: '已沉淀',
    archived: '归档',
    queued: '排队中',
    running: '处理中',
    paused: '已暂停',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }
  return labels[status] || status
}

export function statusTagType(status) {
  if (status === 'succeeded') return 'success'
  if (status === 'distilled') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'warning'
  if (status === 'paused') return 'warning'
  if (status === 'archived') return 'info'
  if (status === 'to_read') return 'primary'
  if (status === 'inbox') return 'info'
  if (status === 'queued') return 'info'
  return 'primary'
}

export function roundedProgress(value) {
  const number = Number(value || 0)
  if (Number.isNaN(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

export function cacheHitLabel(hit) {
  const labels = {
    video_info: '信息缓存',
    video: '视频缓存',
    transcript: '转写缓存',
    subtitle: '字幕缓存'
  }
  return labels[hit] || hit
}

export function textSourceKindLabel(kind) {
  const labels = {
    subtitle: '字幕',
    asr: '语音识别',
    transcript: '转写文本',
    text: '文本'
  }
  return labels[kind] || kind || '未知'
}

export function textSourceProviderLabel(source) {
  const labels = {
    manual: '手动导入',
    cache: '缓存',
    bilibili_subtitle: 'B站字幕',
    bilibili: 'B站',
    'faster-whisper': '本地 Whisper'
  }
  return labels[source] || source || '未知'
}

export function aiCallTypeLabel(type) {
  const labels = {
    summary: '总结',
    article_summary_prepare: '长文材料压缩',
    qa: '追问',
    article_regeneration: '全文重新总结',
    article_regeneration_prepare: '全文材料整理',
    document_formatting: 'OCR 文档排版',
    content_analysis: '自定义按钮',
    wechat_report: '公众号报告',
    group_report_source_summary: '材料短摘要',
    group_report_section_plan: '栏目规划',
    group_report_plan_repair: '规划局部归属修正',
    group_report_event_ledger: '事件事实账本整理',
    group_report_section_writer: '栏目正文撰写',
    group_report_overview: '本期概览撰写',
    campus_report: '校园报告',
    campus_embedding: '校园语义向量'
  }
  return labels[type] || type || '未知'
}

export function errorCategoryLabel(category) {
  const labels = {
    configuration: '配置问题',
    input: '输入问题',
    network_or_download: '下载问题',
    media_processing: '音频处理',
    asr: '语音识别',
    llm: 'AI 总结',
    filesystem: '保存文件',
    cancelled: '用户取消',
    queue_executor: '队列执行',
    unknown: '未知问题'
  }
  return labels[category] || category || '未知问题'
}

export function retryScopeLabel(scope) {
  const labels = {
    none: '需先修正后再提交',
    full: '可整条任务重试',
    download: '可从下载阶段重试',
    audio: '可从音频阶段重试',
    transcribe: '可从转写阶段重试',
    summarize: '可从总结阶段重试',
    save: '可从保存阶段重试'
  }
  return labels[scope] || scope || '可重试'
}

export function sourceProviderLabel(provider) {
  const labels = {
    douyin: '抖音',
    bilibili: 'B站',
    wechat: '微信公众号',
    campus: '校园官网',
    rss: 'RSS 订阅',
    xiaohongshu: '小红书',
    wechat_miniprogram: '微信小程序',
    local_file: '本地文件'
  }
  return labels[provider] || provider || '未知来源'
}

export function markdownSyncLabel(status) {
  const labels = {
    synced: '已同步',
    dirty: '未同步',
    unknown: '未知'
  }
  return labels[status] || status || '未知'
}

export function formatSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return ''
  const seconds = Number(value)
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes} 分 ${rest} 秒`
}

export function formatTokenCount(value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) return '未知'
  return Math.round(number).toLocaleString()
}

export function formatEstimatedCost(value) {
  if (value === null || value === undefined) return '未配置'
  const number = Number(value)
  if (!Number.isFinite(number)) return '未配置'
  if (number === 0) return '0'
  return number < 0.0001 ? '<0.0001' : number.toFixed(4)
}

export function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export function formatDuration(value) {
  const seconds = Number(value || 0)
  if (!seconds) return '未知时长'
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return minutes ? `${minutes} 分 ${rest} 秒` : `${rest} 秒`
}

export function formatDateTime(value) {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未知'
  return date.toLocaleString()
}

export function sanitizeHtml(html) {
  const template = document.createElement('template')
  template.innerHTML = html
  for (const node of [...template.content.querySelectorAll('*')].reverse()) {
    const tagName = node.tagName.toLowerCase()
    if (!SAFE_HTML_TAGS.has(tagName)) {
      if (DROP_HTML_TAGS.has(tagName)) node.remove()
      else node.replaceWith(...node.childNodes)
      continue
    }
    for (const attr of [...node.attributes]) {
      const name = attr.name.toLowerCase()
      const allowed = SAFE_GLOBAL_ATTRIBUTES.has(name)
        || (tagName === 'a' && name === 'href')
        || (tagName === 'img' && ['alt', 'decoding', 'height', 'loading', 'src', 'width'].includes(name))
        || (tagName === 'math' || tagName.startsWith('m')) && SAFE_MATH_ATTRIBUTES.has(name)
        || name === 'data-external-link'
      if (!allowed) node.removeAttribute(attr.name)
    }
    if (node.tagName === 'A') {
      const href = node.getAttribute('href') || ''
      if (isExternalLinkHref(href)) {
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noopener noreferrer')
        node.setAttribute('data-external-link', '')
      } else if (href.startsWith('#')) {
        node.removeAttribute('target')
        node.removeAttribute('rel')
      } else {
        node.removeAttribute('href')
        node.removeAttribute('target')
        node.removeAttribute('rel')
      }
    }
    if (node.tagName === 'IMG' && !isSafeEmbeddedImage(node.getAttribute('src') || '')) {
      const alt = node.getAttribute('alt') || '外部图片'
      node.replaceWith(document.createTextNode(`[${alt}：为保护隐私未加载]`))
    }
  }
  return template.innerHTML
}

function isSafeEmbeddedImage(value) {
  const source = String(value || '').trim()
  if (/^data:image\/(?:avif|gif|jpe?g|png|webp);base64,/i.test(source) || source.startsWith('blob:')) return true
  try {
    const url = new URL(source, window.location.href)
    if (url.protocol === 'knowledgehub:') return true
    return ['http://127.0.0.1:8000', 'http://localhost:8000'].includes(url.origin)
      && url.pathname.startsWith('/api/media')
  } catch {
    return false
  }
}

export function renderMarkdown(markdown) {
  const source = String(markdown || '')
  if (!source) return ''
  const cached = markdownRenderCache.get(source)
  if (cached !== undefined) return cached
  const prepared = expandMarkdownFootnotes(normalizeBareExternalLinks(stripMarkdownMetadata(source)))
  const html = annotateMarkdownHeadings(wrapMarkdownTables(sanitizeHtml(marked.parse(prepared))))
  markdownRenderCache.set(source, html)
  if (markdownRenderCache.size > MARKDOWN_RENDER_CACHE_LIMIT) {
    markdownRenderCache.delete(markdownRenderCache.keys().next().value)
  }
  return html
}

function annotateMarkdownHeadings(html) {
  return String(html || '').replace(
    /<h([1-6])(?=\s|>)/g,
    (_match, level) => `<h${level} data-markdown-heading="H${level}"`
  )
}

function wrapMarkdownTables(html) {
  return String(html || '').replace(
    /<table>([\s\S]*?)<\/table>/g,
    '<div class="markdown-table-scroll"><table>$1</table></div>'
  )
}

export function stripReportMarkdownHeader(markdown) {
  let source = stripMarkdownMetadata(markdown)
  source = source.replace(/^\s*#\s+[^\n]+\n+/, '')
  source = source.replace(/^\s*>\s*分组：[^\n]+\n+/, '')
  source = source.replace(/^\s*#\s+[^\n]*(?:日报|周报)[^\n]*\n+/, '')
  return source.trimStart()
}
