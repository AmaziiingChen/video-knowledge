import assert from 'node:assert/strict'
import test from 'node:test'
import {
  assistantAiModelOptions,
  assistantQuestionPlaceholder,
  assistantSelectedModelLabel,
  conversationEmptyState,
  externalImportCitation,
  ocrAssistantPresentation,
  qaShortcutButtons,
  selectedTextPreview,
  shortcutSuggestions,
  summaryTitleMarkdown,
} from './assistantPresentation.js'

test('normalizes legacy models, deduplicates options, and escapes summary titles', () => {
  const options = assistantAiModelOptions('deepseek-chat', [{ value: 'deepseek-v4-flash:disabled', label: '旧标签' }])
  assert.deepEqual(options.map((option) => option.value), ['deepseek-v4-flash:enabled', 'deepseek-v4-pro:enabled'])
  assert.equal(assistantSelectedModelLabel('deepseek-chat', options), 'DeepSeek · V4 Flash Thinking')
  assert.equal(summaryTitleMarkdown('标题 #1\n'), '# 标题 \\#1')
})

test('retains disabled metadata for the selected provider model', () => {
  const options = assistantAiModelOptions('qwen::qwen3.7-plus:enabled', [{
    value: 'qwen::qwen3.7-plus:enabled', label: 'Qwen Plus', provider: 'qwen', disabled: true,
  }])
  assert.equal(options[0].value, 'qwen::qwen3.7-plus:enabled')
  assert.equal(options[0].disabled, true)
})

test('keeps external citations and shortcut filtering bounded', () => {
  assert.equal(externalImportCitation({ source_provider: 'rss' }), null)
  assert.equal(externalImportCitation({ source_provider: 'local_file', title: '资料', created_at: 'bad' }).importedAt, '时间未知')
  const shortcuts = qaShortcutButtons([{ id: 'one', name: '总结', template: 'x' }, { id: 'two', template: ' ' }])
  assert.deepEqual(shortcutSuggestions('请 @总', shortcuts).map((item) => item.id), ['one'])
  assert.deepEqual(shortcutSuggestions('普通问题', shortcuts), [])
})

test('derives empty state, OCR controls, question hints, and selected text safely', () => {
  const state = conversationEmptyState({
    conversationKey: 'content:1', currentQaEnabled: true, currentQaHint: '', currentInsightHtml: '', generatingAiSummary: false,
    generatingSummaryText: '', qaHistory: [], qaHistoryLoading: false, qaHistoryLoadingMore: false, qaHistoryError: '', contentContext: null,
    emptyDocumentIcon: 'document', emptyConversationIcon: 'conversation',
  })
  assert.equal(state.show, true)
  assert.equal(state.icon, 'conversation')
  const ocr = ocrAssistantPresentation({ status: 'queued', priority: false }, false)
  assert.equal(ocr.show, true)
  assert.equal(ocr.canPrioritize, true)
  assert.equal(assistantQuestionPlaceholder({ ocrInputHint: ocr.inputHint, selectedTextContext: null, currentQaHint: '', currentQaEnabled: true }), ocr.inputHint)
  const completedOcr = ocrAssistantPresentation({ status: 'completed', image_count: 2 }, false)
  assert.equal(completedOcr.show, false)
  assert.equal(completedOcr.inputHint, '图片文字已解析；后续摘要和快捷命令将使用完整内容。')
  assert.equal(selectedTextPreview(` ${'字'.repeat(69)} `).length, 68)
})
