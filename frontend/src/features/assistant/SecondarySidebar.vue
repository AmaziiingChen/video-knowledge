<template>
  <aside class="insight-sidebar">
    <section
      ref="conversationRef"
      class="assistant-conversation"
      @scroll.passive="handleConversationScroll"
      @wheel.passive="handleConversationWheel"
      @click="handleTimestampLinkClick"
    >
      <div v-if="qaHistoryLoading && !qaHistory.length" class="qa-history-status" role="status">正在恢复对话记录…</div>
      <div v-else-if="qaHistoryLoadingMore" class="qa-history-status" role="status">正在加载更早对话…</div>
      <button
        v-if="qaHistoryError"
        class="qa-history-retry"
        type="button"
        :disabled="qaHistoryLoading || qaHistoryLoadingMore"
        @click="$emit('retry-qa-history')"
      >
        {{ qaHistoryError }}，点击重试
      </button>

      <Transition name="assistant-empty-state">
        <section
          v-if="showConversationEmptyState"
          class="assistant-empty-state"
          aria-live="polite"
        >
          <div class="assistant-empty-icon" aria-hidden="true">
            <SvgMaskIcon :src="emptyStateIcon" :size="28" />
          </div>
          <div class="assistant-empty-copy">
            <h2>{{ emptyStateHeading }}</h2>
            <p>{{ emptyStateDetail }}</p>
          </div>
          <div v-if="isConversationStarterReady" class="assistant-starter-prompts" aria-label="建议问题">
            <button
              v-for="prompt in starterPrompts"
              :key="prompt"
              class="assistant-starter-prompt"
              type="button"
              @click="askStarterPrompt(prompt)"
            >
              {{ prompt }}
            </button>
          </div>
        </section>
      </Transition>

      <article v-if="currentInsightHtml" class="assistant-message assistant-message-summary">
        <AiReasoningPanel
          :reasoning="visibleInsightReasoning"
          :expanded="visibleInsightReasoningExpanded"
          :pending-answer="false"
          :truncated="visibleInsightReasoningTruncated"
          :render-markdown="renderMarkdown"
          @update:expanded="updateVisibleInsightReasoningExpanded"
        />
        <div
          v-if="currentInsightTitle"
          class="assistant-message-body insight-summary assistant-summary-title"
          v-html="renderMarkdown(summaryTitleMarkdown(currentInsightTitle))"
        />
        <div class="assistant-message-body insight-summary" v-html="currentInsightHtml" />
      </article>

      <article
        v-if="isGeneratingAnySummary || (!currentInsightHtml && visibleGeneratingSummaryText)"
        class="assistant-message assistant-message-answer assistant-message-new"
      >
        <AiReasoningPanel
          :reasoning="visibleGeneratingSummaryReasoning"
          :expanded="visibleGeneratingReasoningExpanded"
          :pending-answer="!visibleGeneratingSummaryText"
          :truncated="visibleGeneratingSummaryReasoningTruncated"
          :render-markdown="renderMarkdown"
          @update:expanded="updateVisibleGeneratingReasoningExpanded"
        />
        <div
          v-if="visibleGeneratingSummaryText"
          class="assistant-message-body qa-answer"
          v-html="renderMarkdown(visibleGeneratingSummaryText)"
        />
        <AiSkeletonStream
          v-else-if="!visibleGeneratingSummaryReasoning"
          class="assistant-message-body qa-answer"
          label="正在生成 AI 摘要"
          aria-label="AI 正在生成摘要"
        />
      </article>

      <template v-for="(item, index) in qaHistory" :key="index">
        <article class="assistant-message assistant-message-user">
          <p>{{ item.question }}</p>
          <div v-if="item.selectedText" class="assistant-message-selection" :title="item.selectedText">
            <strong>@选中文本</strong>
            <span>{{ selectedTextPreview(item.selectedText) }}</span>
          </div>
          <small v-if="item.autoShortcutName" class="assistant-message-auto-shortcut">已附加 @{{ item.autoShortcutName }} 指引</small>
        </article>
        <article
          class="assistant-message assistant-message-answer"
          :class="{ 'assistant-message-new': item.pending && index === qaHistory.length - 1 }"
        >
          <AiReasoningPanel
            :reasoning="item.reasoning"
            :expanded="item.reasoningExpanded"
            :pending-answer="item.pending && !item.answer"
            :render-markdown="renderMarkdown"
            @update:expanded="item.reasoningExpanded = $event"
          />
          <div
            v-if="item.answer"
            class="assistant-message-body qa-answer"
            v-html="renderMarkdown(item.answer)"
          />
          <AiSkeletonStream
            v-else-if="item.pending && !item.reasoning"
            class="assistant-message-body qa-answer"
            aria-label="AI 正在生成回答"
          />
          <div v-else-if="item.error" class="assistant-message-body qa-answer qa-answer-error">追问失败，请检查连接后重试。</div>
          <button
            v-if="item.answer && !item.pending && !item.error && externalImportCitation"
            class="assistant-source-citation"
            type="button"
            :title="`回到 ${externalImportCitation.title} 的${item.selectedText ? '选中文本' : '提取正文'}`"
            @click="$emit('return-to-source')"
          >
            <span>资料依据</span>
            <strong>{{ externalImportCitation.title }}</strong>
            <em>导入于 {{ externalImportCitation.importedAt }} · {{ item.selectedText ? '选中文本' : '提取正文' }}</em>
          </button>
          <div v-if="item.answer && !item.pending && !item.error" class="assistant-message-actions">
            <button
              class="assistant-message-action"
              type="button"
              aria-label="复制本次完整问答"
              title="复制本次完整问答"
              @click="$emit('copy-qa-exchange', item)"
            >
              <SvgMaskIcon :src="copyExchangeIcon" :size="14" />
            </button>
            <button
              v-if="index === qaHistory.length - 1"
              class="assistant-message-action"
              type="button"
              aria-label="重新生成回答"
              title="重新生成回答"
              :disabled="askingQuestion || isGeneratingAnySummary || startingNewChat || !item.id"
              @click="$emit('regenerate-qa-answer', item)"
            >
              <SvgMaskIcon :src="regenerateAnswerIcon" :size="14" />
            </button>
          </div>
        </article>
      </template>

    </section>

    <div class="assistant-composer-stack">
      <AssistantComposer
      :question-input="questionInput"
      :selected-ai-model="selectedAiModel"
      :available-ai-models="availableAiModels"
      :qa-shortcut-templates="qaShortcutTemplates"
      :article-ocr-status="articleOcrStatus"
      :prioritizing-article-ocr="prioritizingArticleOcr"
      :selected-text-context="selectedTextContext"
      :asking-question="askingQuestion"
      :generating-ai-summary="isGeneratingAnySummary"
      :starting-new-chat="startingNewChat"
      :current-qa-enabled="currentQaEnabled"
      :current-qa-hint="currentQaHint"
      :can-generate-ai-summary="canGenerateAiSummary"
      :exporting-markdown="exportingMarkdown"
      :content-analysis-templates="contentAnalysisTemplates"
      :current-insight-html="currentInsightHtml"
      :qa-history="qaHistory"
      @update:question-input="$emit('update:questionInput', $event)"
      @update:selected-ai-model="$emit('update:selectedAiModel', $event)"
      @prioritize-ocr="$emit('prioritize-ocr')"
      @insert-shortcut="$emit('insert-shortcut', $event)"
      @new-chat="$emit('new-chat')"
      @generate-ai-summary="$emit('generate-ai-summary')"
      @export-markdown="$emit('export-markdown')"
      @run-content-analysis="$emit('run-content-analysis')"
        @ask-question="forwardAskQuestion"
      />
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'
import AiSkeletonStream from '../../components/AiSkeletonStream.vue'
import AiReasoningPanel from './AiReasoningPanel.vue'
import AssistantComposer from './AssistantComposer.vue'
import { useConversationScrollController } from './useConversationScrollController.js'
import {
  conversationEmptyState,
  externalImportCitation as externalImportCitationForContent,
  selectedTextPreview,
  summaryTitleMarkdown,
} from './assistantPresentation.js'
const emptyDocumentIcon = 'questionmark.bubble.fill'
const emptyConversationIcon = 'bubble.and.pencil'
const copyExchangeIcon = 'document.on.clipboard'
const regenerateAnswerIcon = 'arrow.clockwise'

const props = defineProps({
  currentInsightHtml: {
    type: String,
    default: ''
  },
  currentInsightTitle: {
    type: String,
    default: ''
  },
  currentInsightReasoning: { type: String, default: '' },
  currentInsightReasoningTruncated: { type: Boolean, default: false },
  contentContext: {
    type: Object,
    default: null
  },
  conversationKey: {
    type: String,
    default: ''
  },
  contentAnalysisTemplates: {
    type: Array,
    default: () => []
  },
  qaHistory: {
    type: Array,
    default: () => []
  },
  qaHistoryLoading: {
    type: Boolean,
    default: false
  },
  qaHistoryLoadingMore: {
    type: Boolean,
    default: false
  },
  qaHistoryHasMore: {
    type: Boolean,
    default: false
  },
  qaHistoryError: {
    type: String,
    default: ''
  },
  qaShortcutTemplates: {
    type: Array,
    default: () => []
  },
  articleOcrStatus: {
    type: Object,
    default: () => ({ status: 'unavailable', has_images: false, priority: false })
  },
  prioritizingArticleOcr: {
    type: Boolean,
    default: false
  },
  questionInput: {
    type: String,
    default: ''
  },
  selectedTextContext: {
    type: Object,
    default: null
  },
  askingQuestion: {
    type: Boolean,
    default: false
  },
  generatingAiSummary: {
    type: Boolean,
    default: false
  },
  pipelineGeneratingAiSummary: { type: Boolean, default: false },
  generatingSummaryText: {
    type: String,
    default: ''
  },
  pipelineGeneratingSummaryText: { type: String, default: '' },
  generatingSummaryReasoning: { type: String, default: '' },
  generatingSummaryReasoningExpanded: { type: Boolean, default: false },
  pipelineGeneratingSummaryReasoning: { type: String, default: '' },
  pipelineGeneratingSummaryReasoningTruncated: { type: Boolean, default: false },
  pipelineSummaryTaskId: { type: String, default: '' },
  canGenerateAiSummary: {
    type: Boolean,
    default: false
  },
  startingNewChat: {
    type: Boolean,
    default: false
  },
  currentQaEnabled: {
    type: Boolean,
    default: false
  },
  currentQaHint: {
    type: String,
    default: ''
  },
  exportingMarkdown: {
    type: Boolean,
    default: false
  },
  selectedAiModel: {
    type: String,
    default: 'deepseek-v4-flash:enabled'
  },
  availableAiModels: {
    type: Array,
    default: () => [
      { value: 'deepseek-v4-flash:enabled', label: 'V4 Flash Thinking' },
      { value: 'deepseek-v4-pro:enabled', label: 'V4 Pro Thinking' }
    ]
  },
  renderMarkdown: {
    type: Function,
    required: true
  }
})

const emit = defineEmits([
  'update:questionInput',
  'update:selectedAiModel',
  'update:generatingSummaryReasoningExpanded',
  'new-chat',
  'generate-ai-summary',
  'ask-question',
  'load-more-qa-history',
  'retry-qa-history',
  'insert-shortcut',
  'prioritize-ocr',
  'run-content-analysis',
  'export-markdown',
  'copy-qa-exchange',
  'regenerate-qa-answer',
  'seek-video',
  'return-to-source'
])

const externalImportCitation = computed(() => externalImportCitationForContent(props.contentContext))
const isGeneratingAnySummary = computed(() => (
  props.generatingAiSummary || props.pipelineGeneratingAiSummary
))
const visibleGeneratingSummaryText = computed(() => (
  props.pipelineGeneratingAiSummary
    ? props.pipelineGeneratingSummaryText
    : props.generatingSummaryText
))
const visibleGeneratingSummaryReasoning = computed(() => (
  props.pipelineGeneratingAiSummary
    ? props.pipelineGeneratingSummaryReasoning
    : props.generatingSummaryReasoning
))
const visibleGeneratingSummaryReasoningTruncated = computed(() => Boolean(
  props.pipelineGeneratingAiSummary && props.pipelineGeneratingSummaryReasoningTruncated
))
const pipelineReasoningExpanded = ref(false)
const insightReasoningExpanded = ref(false)
const usesCompletedManualReasoning = computed(() => Boolean(
  !props.currentInsightReasoning && props.generatingSummaryReasoning
))
const visibleInsightReasoning = computed(() => (
  props.currentInsightReasoning || props.generatingSummaryReasoning
))
const visibleInsightReasoningTruncated = computed(() => (
  usesCompletedManualReasoning.value ? false : props.currentInsightReasoningTruncated
))
const visibleInsightReasoningExpanded = computed(() => (
  usesCompletedManualReasoning.value
    ? props.generatingSummaryReasoningExpanded
    : insightReasoningExpanded.value
))

function updateVisibleInsightReasoningExpanded(value) {
  if (usesCompletedManualReasoning.value) {
    emit('update:generatingSummaryReasoningExpanded', value)
    return
  }
  insightReasoningExpanded.value = Boolean(value)
}

const visibleGeneratingReasoningExpanded = computed(() => (
  props.pipelineGeneratingAiSummary
    ? pipelineReasoningExpanded.value
    : props.generatingSummaryReasoningExpanded
))

function updateVisibleGeneratingReasoningExpanded(value) {
  if (props.pipelineGeneratingAiSummary) {
    pipelineReasoningExpanded.value = Boolean(value)
    return
  }
  emit('update:generatingSummaryReasoningExpanded', value)
}

watch(
  () => props.pipelineSummaryTaskId,
  () => {
    pipelineReasoningExpanded.value = Boolean(
      props.pipelineGeneratingAiSummary
      && props.pipelineGeneratingSummaryReasoning
      && !props.pipelineGeneratingSummaryText
    )
    insightReasoningExpanded.value = false
  },
)
watch(
  () => props.pipelineGeneratingSummaryReasoning,
  (reasoning, previous) => {
    if (props.pipelineGeneratingAiSummary && reasoning && !previous && !props.pipelineGeneratingSummaryText) {
      pipelineReasoningExpanded.value = true
    }
  },
  { immediate: true },
)
watch(
  () => props.pipelineGeneratingSummaryText,
  (text, previous) => {
    if (props.pipelineGeneratingAiSummary && text && !previous) {
      pipelineReasoningExpanded.value = false
    }
  },
  { immediate: true },
)
const emptyState = computed(() => conversationEmptyState({
  conversationKey: props.conversationKey,
  currentQaEnabled: props.currentQaEnabled,
  currentQaHint: props.currentQaHint,
  currentInsightHtml: props.currentInsightHtml,
  generatingAiSummary: isGeneratingAnySummary.value,
  generatingSummaryText: visibleGeneratingSummaryText.value,
  qaHistory: props.qaHistory,
  qaHistoryLoading: props.qaHistoryLoading,
  qaHistoryLoadingMore: props.qaHistoryLoadingMore,
  qaHistoryError: props.qaHistoryError,
  contentContext: props.contentContext,
  emptyDocumentIcon,
  emptyConversationIcon,
}))
const showConversationEmptyState = computed(() => emptyState.value.show)
const isConversationStarterReady = computed(() => emptyState.value.ready)
const emptyStateIcon = computed(() => emptyState.value.icon)
const emptyStateHeading = computed(() => emptyState.value.heading)
const emptyStateDetail = computed(() => emptyState.value.detail)
const starterPrompts = computed(() => emptyState.value.starterPrompts)
const {
  conversationRef,
  handleConversationScroll,
  handleConversationWheel,
  handleTimestampLinkClick,
} = useConversationScrollController({ props, emit })

function askStarterPrompt(prompt) {
  if (!isConversationStarterReady.value) return
  emit('ask-question', prompt)
}

function forwardAskQuestion(...args) {
  emit('ask-question', ...args)
}
</script>

<style scoped>
.insight-sidebar {
  height: 100%;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  flex-shrink: 1;
  margin: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  overflow: hidden;
  background: var(--vk-bg-quiet);
  border-left: 0;
  color: var(--vk-text);
}
.assistant-composer-stack { min-width: 0; }

.assistant-conversation {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
}

.assistant-conversation {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  padding: 12px 14px 16px 12px;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
}

.qa-history-status,
.qa-history-retry {
  align-self: center;
  margin: 2px 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.qa-history-retry {
  border: 0;
  padding: 3px 6px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--vk-accent) 10%, transparent);
  cursor: pointer;
}

.qa-history-retry:disabled {
  cursor: default;
  opacity: 0.6;
}

.assistant-empty-state {
  width: min(100%, 332px);
  margin: auto;
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 20px 8px;
  color: var(--vk-muted);
  text-align: center;
}

.assistant-empty-icon {
  display: grid;
  place-items: center;
  color: color-mix(in srgb, var(--vk-accent) 68%, var(--vk-muted));
}

.assistant-empty-copy {
  display: grid;
  gap: 4px;
}

.assistant-empty-copy h2,
.assistant-empty-copy p {
  margin: 0;
}

.assistant-empty-copy h2 {
  color: var(--vk-text);
  font-size: var(--vk-type-reading-size);
  font-weight: var(--vk-weight-strong);
  letter-spacing: -0.01em;
  line-height: 1.35;
}

.assistant-empty-copy p {
  max-width: 270px;
  font-size: var(--vk-type-meta-size);
  line-height: 1.55;
}

.assistant-starter-prompts {
  width: min(100%, 280px);
  display: grid;
  gap: 6px;
}

.assistant-starter-prompt {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 76%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--vk-bg-panel) 86%, transparent);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  line-height: 1.35;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--vk-motion-fast) var(--vk-ease-out),
    border-color var(--vk-motion-fast) var(--vk-ease-out),
    color var(--vk-motion-fast) var(--vk-ease-out),
    transform var(--vk-motion-fast) var(--vk-ease-out);
}

.assistant-starter-prompt:hover {
  border-color: color-mix(in srgb, var(--vk-accent) 42%, var(--vk-border));
  background: color-mix(in srgb, var(--vk-accent) 8%, var(--vk-bg-panel));
  color: var(--vk-accent-strong);
}

.assistant-starter-prompt:active {
  transform: scale(0.985);
}

.assistant-empty-state-enter-active,
.assistant-empty-state-leave-active {
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    transform var(--vk-motion-standard) var(--vk-ease-out);
}

.assistant-empty-state-enter-from,
.assistant-empty-state-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.insight-summary {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  line-height: 1.65;
  overflow-x: auto;
}

.assistant-summary-title :deep(h1) {
  margin: 0 0 6px;
  color: var(--vk-text);
  font-size: var(--vk-type-heading-size);
  font-weight: var(--vk-weight-strong);
  line-height: var(--vk-leading-heading);
}

.assistant-message {
  min-width: 0;
  max-width: 100%;
}

.assistant-message-new {
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    transform var(--vk-motion-standard) var(--vk-ease-out);
}

@starting-style {
  .assistant-message-new {
    opacity: 0;
    transform: translateY(4px);
  }
}

.assistant-message-body {
  min-width: 0;
  max-width: 100%;
}

.assistant-message-body :deep(a[href^="#video-t="]) {
  color: var(--vk-accent-strong);
  font-variant-numeric: tabular-nums;
  font-weight: var(--vk-weight-strong);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}

.assistant-message-body :deep(a[href^="#video-t="]:hover) {
  color: var(--vk-accent);
}

.assistant-message-user {
  margin: 4px 0 0;
  padding-left: 8px;
  border-left: 2px solid var(--vk-accent);
  color: var(--vk-text);
}

.assistant-message-user p {
  margin: 0;
  font-size: var(--vk-type-body-size);
  line-height: var(--vk-leading-body);
}

.assistant-message-selection {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 6px;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  line-height: 1.35;
}

.assistant-message-selection {
  margin-top: 6px;
}

.assistant-message-selection strong {
  flex: 0 0 auto;
  color: var(--vk-accent-strong);
  font-weight: var(--vk-weight-strong);
}

.assistant-message-selection span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-message-auto-shortcut {
  display: block;
  margin-top: 5px;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  line-height: 1.35;
}

.assistant-message-answer {
  color: var(--vk-text);
}

.assistant-source-citation {
  display: flex;
  align-items: baseline;
  width: 100%;
  min-width: 0;
  gap: var(--vk-space-xs);
  margin-top: var(--vk-space-xs);
  padding: var(--vk-space-xs) var(--vk-space-sm);
  overflow: hidden;
  border: 1px solid var(--vk-divider-subtle);
  border-radius: var(--vk-radius-control);
  background: var(--vk-bg-quiet);
  color: var(--vk-muted);
  font: inherit;
  font-size: var(--vk-type-micro-size);
  line-height: var(--vk-leading-label);
  text-align: left;
  cursor: pointer;
}

.assistant-source-citation:hover {
  border-color: color-mix(in srgb, var(--vk-accent) 42%, var(--vk-divider-subtle));
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.assistant-source-citation:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--vk-accent) 70%, transparent);
  outline-offset: 1px;
}

.assistant-source-citation span {
  flex: 0 0 auto;
  color: var(--vk-accent-strong);
  font-weight: var(--vk-weight-strong);
}

.assistant-source-citation strong,
.assistant-source-citation em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-source-citation strong {
  flex: 1 1 auto;
  color: inherit;
  font-weight: var(--vk-weight-medium);
}

.assistant-source-citation em {
  flex: 0 1 auto;
  font-style: normal;
}

.assistant-message-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
}

.assistant-message-action {
  width: 26px;
  height: 26px;
  align-items: center;
  display: inline-flex;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  font-size: var(--vk-type-meta-size);
  line-height: 1;
  cursor: pointer;
}

.assistant-message-action:hover:not(:disabled) {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.assistant-message-action:disabled {
  cursor: default;
  opacity: 0.48;
}

.insight-summary :deep(h2) {
  margin: 12px 0 6px;
  font-size: var(--vk-type-heading-size);
}

.insight-summary :deep(h1) {
  color: var(--vk-accent);
}

.insight-summary :deep(h3) {
  margin: 10px 0 6px;
  font-size: var(--vk-type-reading-size);
}

.insight-summary :deep(ul) {
  padding-left: 18px;
}

.insight-summary :deep(table),
.qa-answer :deep(table) {
  width: 100%;
  min-width: min(360px, 100%);
  max-width: 100%;
  display: table;
  margin: 8px 0 10px;
  border: 0;
  border-top: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-spacing: 0;
  table-layout: auto;
  background: transparent;
  font-size: 11.5px;
  line-height: 1.5;
}

.insight-summary :deep(thead),
.qa-answer :deep(thead) {
  background: color-mix(in srgb, var(--vk-accent) 7%, transparent);
}

.insight-summary :deep(th),
.insight-summary :deep(td),
.qa-answer :deep(th),
.qa-answer :deep(td) {
  min-width: 84px;
  max-width: none;
  padding: 6px 8px;
  border-right: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 58%, transparent);
  color: var(--vk-text);
  text-align: left;
  vertical-align: top;
  white-space: normal;
  word-break: break-word;
}

.insight-summary :deep(th),
.qa-answer :deep(th) {
  color: color-mix(in srgb, var(--vk-text) 84%, var(--vk-muted));
  font-weight: var(--vk-weight-strong);
}

.insight-summary :deep(tr:last-child td),
.qa-answer :deep(tr:last-child td) {
  border-bottom: 0;
}

.insight-summary :deep(table::-webkit-scrollbar),
.qa-answer :deep(table::-webkit-scrollbar) {
  height: 6px;
}

.insight-summary :deep(table::-webkit-scrollbar-thumb),
.qa-answer :deep(table::-webkit-scrollbar-thumb) {
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-muted) 24%, transparent);
}

.qa-answer {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  line-height: 1.6;
  overflow-x: auto;
}

.qa-answer :deep(p:last-child),
.insight-summary :deep(p:last-child) {
  margin-bottom: 0;
}

.qa-answer :deep(.katex-display),
.insight-summary :deep(.katex-display) {
  max-width: 100%;
  margin: 0.8em 0;
  padding: 2px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.qa-answer :deep(.katex),
.insight-summary :deep(.katex) {
  color: currentColor;
  font-size: 1em;
}

.qa-answer-error {
  color: var(--vk-error-text);
}

@media (prefers-reduced-motion: reduce) {
  .assistant-message-new,
  .assistant-starter-prompt,
  .assistant-empty-state-enter-active,
  .assistant-empty-state-leave-active {
    transform: none;
    transition: opacity var(--vk-motion-fast) ease;
  }
}

@media (max-width: 900px) {
  .insight-sidebar {
    width: 100%;
    border-left: 0;
    border-top: 1px solid var(--vk-border);
  }
}

@media (max-width: 620px) {
  .insight-sidebar {
    grid-row: auto;
  }
}
</style>
