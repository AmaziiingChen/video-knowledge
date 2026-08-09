import { starterPromptsForContent } from './starterPrompts.js'

const DEFAULT_MODELS = [
  { value: 'deepseek-v4-flash:enabled', label: 'V4 Flash Thinking' },
  { value: 'deepseek-v4-pro:enabled', label: 'V4 Pro Thinking' },
]

function normalizeAiModelOption(option) {
  const rawValue = typeof option === 'string' ? option : option?.value
  if (!rawValue) return null
  let value = rawValue
  if (value === 'deepseek-chat' || value === 'deepseek-reasoner') value = 'deepseek-v4-flash:enabled'
  if (value === 'deepseek-v4-flash' || value === 'deepseek-v4-pro') value = `${value}:enabled`
  if (value.endsWith(':disabled')) value = value.replace(':disabled', ':enabled')
  const defaultLabel = DEFAULT_MODELS.find((model) => model.value === value)?.label
  return {
    value,
    label: (typeof option === 'object' && option?.label) || defaultLabel || value,
  }
}

export function assistantAiModelOptions(selectedModel, availableModels) {
  const seen = new Set()
  const options = []
  for (const candidate of [selectedModel, ...(availableModels || []), ...DEFAULT_MODELS]) {
    const model = normalizeAiModelOption(candidate)
    if (!model || seen.has(model.value)) continue
    seen.add(model.value)
    options.push(model)
  }
  return options
}

export function assistantSelectedModelLabel(selectedModel, options) {
  return options.find((model) => model.value === selectedModel)?.label
    || normalizeAiModelOption(selectedModel)?.label
    || 'V4 Flash'
}

export function summaryTitleMarkdown(title) {
  const safeTitle = String(title || '')
    .replace(/\r?\n/gu, ' ')
    .replace(/([\\`*_{}\[\]<>()#+.!|])/gu, '\\$1')
    .trim()
  return safeTitle ? `# ${safeTitle}` : ''
}

export function customContentActionLabel(templates) {
  const items = templates || []
  return items.find((template) => template?.is_active)?.name?.trim()
    || items[0]?.name?.trim()
    || '自定义按钮'
}

export function externalImportCitation(content) {
  if (!['local_file', 'local_markdown'].includes(String(content?.source_provider || ''))) return null
  const imported = new Date(content?.created_at || '')
  const importedAt = Number.isNaN(imported.getTime())
    ? '时间未知'
    : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' }).format(imported)
  return { title: String(content?.title || '外部资料').trim() || '外部资料', importedAt }
}

export function qaShortcutButtons(templates) {
  return (templates || [])
    .filter((template) => template?.template?.trim())
    .map((template) => ({ id: template.id, name: template.name || '快捷', template: template.template }))
}

export function shortcutSuggestions(questionInput, shortcuts) {
  const match = String(questionInput || '').match(/(?:^|\s)@([^\s@]*)$/u)
  if (!match) return []
  const query = match[1].trim().toLocaleLowerCase()
  return shortcuts
    .filter((shortcut) => !query || shortcut.name.toLocaleLowerCase().includes(query))
    .slice(0, 5)
}

export function hasExportableConversation(currentInsightHtml, qaHistory) {
  return Boolean(currentInsightHtml || (qaHistory || []).some((item) => item?.question || item?.answer))
}

export function conversationEmptyState({
  conversationKey,
  currentQaEnabled,
  currentQaHint,
  currentInsightHtml,
  generatingAiSummary,
  generatingSummaryText,
  qaHistory,
  qaHistoryLoading,
  qaHistoryLoadingMore,
  qaHistoryError,
  contentContext,
  emptyDocumentIcon,
  emptyConversationIcon,
}) {
  const hasConversationContent = Boolean(
    currentInsightHtml || generatingAiSummary || generatingSummaryText || (qaHistory || []).length
  )
  const show = !hasConversationContent && !qaHistoryLoading && !qaHistoryLoadingMore && !qaHistoryError
  const hasSelectedContent = Boolean(conversationKey)
  const ready = hasSelectedContent && currentQaEnabled
  return {
    show,
    ready,
    icon: ready ? emptyConversationIcon : emptyDocumentIcon,
    heading: !hasSelectedContent ? '选择一条资料' : ready ? '从这里开始提问' : '正在准备这条资料',
    detail: !hasSelectedContent
      ? '选择资料后，可在这里基于原文提问。'
      : ready
        ? '选择一个问题即可开始，也可以直接输入你的问题。'
        : currentQaHint || '正在加载正文、字幕或转写内容。',
    starterPrompts: starterPromptsForContent(contentContext),
  }
}

export function ocrAssistantPresentation(articleOcrStatus, prioritizingArticleOcr) {
  const status = String(articleOcrStatus?.status || 'unavailable')
  const isPending = ['capture_pending', 'capturing', 'pending', 'queued', 'running'].includes(status)
  const canPrioritize = ['capture_pending', 'pending', 'queued'].includes(status)
    && !prioritizingArticleOcr
    && !articleOcrStatus?.priority
  let label = 'OCR'
  if (prioritizingArticleOcr || (articleOcrStatus?.priority && ['capture_pending', 'queued'].includes(status))) label = '优先解析中'
  else if (status === 'capturing' || status === 'running') label = '解析中'
  else if (status === 'completed') label = 'OCR 已完成'
  let tooltip = '优先解析当前文章中的图片文字'
  if (status === 'completed') tooltip = '当前文章的图片文字已解析'
  else if (status === 'capturing') tooltip = '正在优先获取正文，随后解析图片文字'
  else if (status === 'running') tooltip = '正在解析当前文章的图片文字'
  else if (articleOcrStatus?.priority) tooltip = '当前文章已移至 OCR 队列前列'
  const inputHint = isPending
    ? '图片文字仍在解析；现在生成仅包含正文。'
    : status === 'completed' && Number(articleOcrStatus?.image_count || 0) > 0
      ? '图片文字已解析；后续摘要和快捷命令将使用完整内容。'
      : ''
  return { status, show: isPending, canPrioritize, label, tooltip, inputHint }
}

export function assistantQuestionPlaceholder({ ocrInputHint, selectedTextContext, currentQaHint, currentQaEnabled }) {
  if (ocrInputHint) return ocrInputHint
  if (selectedTextContext) return '围绕选中文本提问…'
  if (currentQaHint) return currentQaHint
  return currentQaEnabled ? '追问当前内容…' : '选择内容后追问'
}

export function selectedTextPreview(value) {
  const text = String(value || '').replace(/\s+/gu, ' ').trim()
  return text.length > 68 ? `${text.slice(0, 67)}…` : text
}
