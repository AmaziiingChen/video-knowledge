import { computed } from 'vue'

import { assistantSummaryFromMarkdown } from './assistantMarkdown.js'

function normalizedSummaryText(value) {
  return String(value || '').replace(/\s+/gu, ' ').trim()
}

function taskSummaryContainsCurrentSummary(taskSummary, currentSummary) {
  const taskText = normalizedSummaryText(taskSummary)
  const currentText = normalizedSummaryText(currentSummary)
  return Boolean(taskText && currentText && (taskText === currentText || taskText.endsWith(currentText)))
}

export function useAssistantWorkspaceProjectionController({
  activeWorkspaceTab,
  activeWorkspaceContent,
  activeWorkspaceResult,
  activeWorkspaceTranscript,
  selectedContentItem,
  markdownState,
  result,
  aiCallsByContentId,
  renderMarkdown,
  isGeneratedReportDocument,
} = {}) {
  const activeContentAiCalls = computed(() => {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id
    if (contentItemId && Array.isArray(aiCallsByContentId[contentItemId])) {
      return aiCallsByContentId[contentItemId]
    }
    return activeWorkspaceResult.value?.ai_calls || result.ai_calls || []
  })

  const isPipelineSummaryGenerating = computed(() => {
    const task = activeWorkspaceResult.value
    if (!task || !['queued', 'running'].includes(task.status)) return false
    const progress = task.progress || {}
    const summaryProgress = Number(progress.summarize || 0)
    if (summaryProgress >= 100) return false
    return task.step === 'summarize' || summaryProgress > 0
  })

  const pipelineGeneratingSummaryText = computed(() => (
    isPipelineSummaryGenerating.value
      ? String(activeWorkspaceResult.value?.summary || '')
      : ''
  ))

  const pipelineGeneratingSummaryReasoning = computed(() => (
    isPipelineSummaryGenerating.value
      ? String(activeWorkspaceResult.value?.reasoning_content || '')
      : ''
  ))

  const pipelineGeneratingSummaryReasoningTruncated = computed(() => Boolean(
    isPipelineSummaryGenerating.value && activeWorkspaceResult.value?.reasoning_truncated
  ))

  const currentSummaryText = computed(() => {
    if (activeWorkspaceTab.value) {
      if (isGeneratedReportDocument(activeWorkspaceContent.value)) return ''
      return assistantSummaryFromMarkdown(markdownState.markdown)
        || activeWorkspaceResult.value?.summary
        || ''
    }
    if (isGeneratedReportDocument(selectedContentItem.value)) return ''
    return result.summary || assistantSummaryFromMarkdown(markdownState.markdown)
  })

  const currentInsightHtml = computed(() => {
    // A running pipeline is already streamed into the assistant bubble; do
    // not render a second static copy above it.
    if (isPipelineSummaryGenerating.value) return ''
    if (activeWorkspaceTab.value) {
      const summary = currentSummaryText.value
      return summary ? renderMarkdown(summary) : ''
    }
    return result.summary ? renderMarkdown(result.summary) : ''
  })

  const currentInsightReasoning = computed(() => {
    if (isPipelineSummaryGenerating.value) return ''
    if (activeWorkspaceTab.value) {
      const taskSummary = String(activeWorkspaceResult.value?.summary || '')
      // The Markdown writer may intentionally omit a leading transcript note
      // from the canonical AI summary. Keep the task reasoning attached when
      // the visible summary is the normalized final portion of that result.
      if (!taskSummaryContainsCurrentSummary(taskSummary, currentSummaryText.value)) return ''
      return String(activeWorkspaceResult.value?.reasoning_content || '')
    }
    if (!taskSummaryContainsCurrentSummary(result.summary, currentSummaryText.value)) return ''
    return String(result.reasoning_content || '')
  })

  const currentInsightReasoningTruncated = computed(() => Boolean(
    currentInsightReasoning.value && (
      activeWorkspaceTab.value
        ? activeWorkspaceResult.value?.reasoning_truncated
        : result.reasoning_truncated
    )
  ))

  const pipelineSummaryTaskId = computed(() => String(
    activeWorkspaceResult.value?.task_id || result.task_id || ''
  ))

  const currentInsightTitle = computed(() => String(
    activeWorkspaceResult.value?.display_title
      || result.display_title
      || activeWorkspaceContent.value?.title
      || activeWorkspaceTab.value?.title
      || selectedContentItem.value?.title
      || result.source_title
      || ''
  ).replace(/\s+/gu, ' ').trim())

  const currentQaEnabled = computed(() => {
    const hasExistingContext = Boolean(
      activeWorkspaceTranscript.value
      || activeWorkspaceResult.value?.transcript
      || result.transcript
      || currentSummaryText.value
    )
    const readiness = activeWorkspaceContent.value?.text_readiness
    if (readiness && readiness.can_ask_ai === false) return hasExistingContext
    return Boolean(activeWorkspaceContent.value?.id || result.content_item_id || hasExistingContext)
  })

  const currentQaHint = computed(() => {
    const readiness = activeWorkspaceContent.value?.text_readiness
    if (activeWorkspaceContent.value && readiness?.can_ask_ai === false) {
      return readiness.detail || readiness.label || '当前内容暂时没有可供追问的文本'
    }
    return currentQaEnabled.value ? '追问当前内容…' : '选择内容后追问'
  })

  const activeRegenerableContent = computed(() => {
    const item = activeWorkspaceContent.value || selectedContentItem.value
    return item?.id ? item : null
  })

  const canGenerateAiSummary = computed(() => Boolean(
    activeRegenerableContent.value?.id
      && currentQaEnabled.value
      && !isGeneratedReportDocument(activeRegenerableContent.value)
      && !String(currentSummaryText.value || '').trim()
  ))

  const currentObsidianPath = computed(() => {
    if (activeWorkspaceTab.value) return markdownState.obsidian_path || result.obsidian_path || ''
    return result.obsidian_path || markdownState.obsidian_path || ''
  })

  return {
    activeContentAiCalls,
    currentInsightHtml,
    currentInsightTitle,
    isPipelineSummaryGenerating,
    pipelineGeneratingSummaryText,
    pipelineGeneratingSummaryReasoning,
    pipelineGeneratingSummaryReasoningTruncated,
    pipelineSummaryTaskId,
    currentInsightReasoning,
    currentInsightReasoningTruncated,
    currentQaEnabled,
    currentQaHint,
    activeRegenerableContent,
    canGenerateAiSummary,
    currentObsidianPath,
    currentSummaryText,
  }
}
