import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'

import { useAssistantWorkspaceProjectionController } from './useAssistantWorkspaceProjectionController.js'

function createController(overrides = {}) {
  const refs = {
    activeWorkspaceTab: ref(overrides.activeWorkspaceTab ?? null),
    activeWorkspaceContent: ref(overrides.activeWorkspaceContent ?? null),
    activeWorkspaceResult: ref(overrides.activeWorkspaceResult ?? null),
    activeWorkspaceTranscript: ref(overrides.activeWorkspaceTranscript ?? ''),
    selectedContentItem: ref(overrides.selectedContentItem ?? null),
  }
  const markdownState = reactive({
    markdown: overrides.markdown ?? '',
    obsidian_path: overrides.markdownObsidianPath ?? null,
  })
  const result = reactive({
    content_item_id: null,
    ai_calls: [],
    summary: '',
    transcript: '',
    obsidian_path: null,
    ...overrides.result,
  })
  const aiCallsByContentId = reactive(overrides.aiCallsByContentId || {})
  const controller = useAssistantWorkspaceProjectionController({
    ...refs,
    markdownState,
    result,
    aiCallsByContentId,
    renderMarkdown: (value) => `<render>${value}</render>`,
    isGeneratedReportDocument: (item) => item?.content_type === 'report',
  })
  return { ...refs, markdownState, result, aiCallsByContentId, controller }
}

test('prefers content-scoped AI call history before task and global fallbacks', () => {
  const state = createController({
    activeWorkspaceContent: { id: 'content-1' },
    activeWorkspaceResult: { ai_calls: [{ id: 'task-call' }] },
    aiCallsByContentId: { 'content-1': [{ id: 'saved-call' }] },
    result: { ai_calls: [{ id: 'global-call' }] },
  })
  assert.deepEqual(state.controller.activeContentAiCalls.value, [{ id: 'saved-call' }])
  delete state.aiCallsByContentId['content-1']
  assert.deepEqual(state.controller.activeContentAiCalls.value, [{ id: 'task-call' }])
})

test('projects active Markdown summaries but keeps generated reports out of the assistant summary', () => {
  const state = createController({
    activeWorkspaceTab: { id: 'content:1' },
    activeWorkspaceContent: { id: 'content-1', content_type: 'article' },
    markdown: '# 标题\n\n## AI 摘要\n\n已保存摘要。',
  })
  assert.equal(state.controller.currentSummaryText.value, '已保存摘要。')
  assert.equal(state.controller.currentInsightHtml.value, '<render>已保存摘要。</render>')

  state.activeWorkspaceContent.value = { id: 'report-1', content_type: 'report' }
  assert.equal(state.controller.currentSummaryText.value, '')
  assert.equal(state.controller.canGenerateAiSummary.value, false)
})

test('mirrors a running pipeline summary once and restores the static insight after completion', () => {
  const state = createController({
    activeWorkspaceTab: { id: 'content:1' },
    activeWorkspaceContent: { id: 'content-1', content_type: 'article' },
    activeWorkspaceResult: {
      status: 'running',
      step: 'summarize',
      progress: { summarize: 40 },
      summary: '正在生成',
      reasoning_content: '正在核对来源',
      reasoning_truncated: true,
      task_id: 'task-1',
    },
  })
  assert.equal(state.controller.isPipelineSummaryGenerating.value, true)
  assert.equal(state.controller.pipelineGeneratingSummaryText.value, '正在生成')
  assert.equal(state.controller.pipelineGeneratingSummaryReasoning.value, '正在核对来源')
  assert.equal(state.controller.pipelineGeneratingSummaryReasoningTruncated.value, true)
  assert.equal(state.controller.currentInsightReasoning.value, '')
  assert.equal(state.controller.pipelineSummaryTaskId.value, 'task-1')
  assert.equal(state.controller.currentInsightHtml.value, '')

  state.markdownState.markdown = '# 标题\n\n## AI 摘要\n\n最终摘要'
  state.activeWorkspaceResult.value = {
    status: 'succeeded',
    summary: '> 转写说明：已核对术语。\n\n最终摘要',
    reasoning_content: '最终思考',
  }
  assert.equal(state.controller.isPipelineSummaryGenerating.value, false)
  assert.equal(state.controller.currentInsightHtml.value, '<render>最终摘要</render>')
  assert.equal(state.controller.currentInsightReasoning.value, '最终思考')

  state.markdownState.markdown = '# 标题\n\n## AI 摘要\n\n用户后来生成的摘要。'
  assert.equal(state.controller.currentInsightReasoning.value, '')
})

test('requires real text context when readiness blocks QA and preserves the backend hint', () => {
  const state = createController({
    activeWorkspaceContent: {
      id: 'content-1',
      text_readiness: { can_ask_ai: false, detail: '等待 OCR 完成' },
    },
  })
  assert.equal(state.controller.currentQaEnabled.value, false)
  assert.equal(state.controller.currentQaHint.value, '等待 OCR 完成')
  assert.equal(state.controller.canGenerateAiSummary.value, false)

  state.activeWorkspaceTranscript.value = '已有正文'
  assert.equal(state.controller.currentQaEnabled.value, true)
  assert.equal(state.controller.canGenerateAiSummary.value, true)
})

test('normalizes the insight title and follows active versus fallback output paths', () => {
  const state = createController({
    activeWorkspaceTab: { id: 'content:1', title: '标签标题' },
    activeWorkspaceContent: { id: 'content-1', title: '资料标题' },
    activeWorkspaceResult: { display_title: '  当前\n任务  ' },
    markdownObsidianPath: '/active.md',
    result: { obsidian_path: '/fallback.md' },
  })
  assert.equal(state.controller.currentInsightTitle.value, '当前 任务')
  assert.equal(state.controller.currentObsidianPath.value, '/active.md')

  state.activeWorkspaceTab.value = null
  assert.equal(state.controller.currentObsidianPath.value, '/fallback.md')
})
