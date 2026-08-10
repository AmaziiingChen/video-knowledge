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
        <div
          v-if="currentInsightTitle"
          class="assistant-message-body insight-summary assistant-summary-title"
          v-html="renderMarkdown(summaryTitleMarkdown(currentInsightTitle))"
        />
        <div class="assistant-message-body insight-summary" v-html="currentInsightHtml" />
      </article>

      <article
        v-if="generatingAiSummary || (!currentInsightHtml && generatingSummaryText)"
        class="assistant-message assistant-message-answer assistant-message-new"
      >
        <div
          v-if="generatingSummaryText"
          class="assistant-message-body qa-answer"
          v-html="renderMarkdown(generatingSummaryText)"
        />
        <AiSkeletonStream
          v-else
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
          <div
            v-if="item.answer"
            class="assistant-message-body qa-answer"
            v-html="renderMarkdown(item.answer)"
          />
          <AiSkeletonStream
            v-else-if="item.pending"
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
              :disabled="askingQuestion || generatingAiSummary || startingNewChat || !item.id"
              @click="$emit('regenerate-qa-answer', item)"
            >
              <SvgMaskIcon :src="regenerateAnswerIcon" :size="14" />
            </button>
          </div>
        </article>
      </template>

    </section>

    <section class="assistant-input">
      <div class="assistant-input-panel">
        <div class="assistant-input-tools">
          <div
            ref="modelMenuRef"
            class="assistant-model-menu"
            @focusout="handleMenuFocusOut('model', $event)"
          >
            <button
              class="assistant-model-pill"
              :class="{ open: modelMenuOpen }"
              type="button"
              aria-label="切换模型"
              :aria-expanded="modelMenuOpen"
              @click="toggleModelMenu"
              @keydown.esc="closeAssistantMenus"
            >
              <span>{{ selectedAiModelLabel }}</span>
              <el-icon class="assistant-menu-chevron"><ArrowDown /></el-icon>
            </button>
            <Transition name="assistant-model-pop">
              <div v-if="modelMenuOpen" class="assistant-model-options">
                <button
                  v-for="model in aiModelOptions"
                  :key="model.value"
                  class="assistant-model-option"
                  :class="{ active: model.value === selectedAiModel }"
                  type="button"
                  @click="selectAiModel(model.value)"
                >
                  {{ model.label }}
                </button>
              </div>
            </Transition>
          </div>
          <div
            v-if="qaShortcutButtons.length"
            ref="shortcutMenuRef"
            class="assistant-command-menu"
            @focusout="handleMenuFocusOut('shortcut', $event)"
          >
            <button
              class="assistant-command-menu-button"
              :class="{ active: shortcutMenuOpen }"
              type="button"
              :aria-expanded="shortcutMenuOpen"
              :disabled="askingQuestion || !currentQaEnabled"
              @click="toggleShortcutMenu"
              @keydown.esc="closeAssistantMenus"
            >
              <span>快捷命令</span>
              <el-icon class="assistant-menu-chevron"><ArrowDown /></el-icon>
            </button>
          </div>
          <el-tooltip v-if="showOcrControl" :content="ocrControlTooltip" placement="top">
            <button
              class="assistant-command-menu-button assistant-ocr-button"
              :class="{ active: articleOcrStatus.priority, complete: articleOcrStatus.status === 'completed' }"
              type="button"
              :disabled="!canPrioritizeOcr"
              @click="$emit('prioritize-ocr')"
            >
              {{ ocrControlLabel }}
            </button>
          </el-tooltip>
        </div>

        <Transition name="assistant-shortcut-pop">
          <div
            v-if="shortcutMenuOpen"
            ref="shortcutSuggestionsRef"
            class="assistant-shortcut-suggestions"
            role="listbox"
          >
            <button
              v-for="shortcut in qaShortcutButtons"
              :key="shortcut.id"
              class="assistant-shortcut-suggestion"
              type="button"
              @click="insertShortcut(shortcut.name)"
            >
              <strong>@{{ shortcut.name }}</strong>
              <span>{{ shortcut.template }}</span>
            </button>
          </div>
        </Transition>

        <div
          v-if="!shortcutMenuOpen && shortcutSuggestions.length"
          ref="shortcutSuggestionsRef"
          class="assistant-shortcut-suggestions"
          role="listbox"
        >
          <button
            v-for="shortcut in shortcutSuggestions"
            :key="shortcut.id"
            class="assistant-shortcut-suggestion"
            type="button"
            @click="insertShortcut(shortcut.name)"
          >
            <strong>@{{ shortcut.name }}</strong>
            <span>{{ shortcut.template }}</span>
          </button>
        </div>

        <textarea
          ref="questionInputRef"
          class="assistant-question-textarea"
          name="assistant-question"
          autocomplete="off"
          aria-label="向当前内容提问"
          :value="questionInput"
          :placeholder="questionPlaceholder"
          rows="1"
          @input="handleQuestionInput"
          @keydown.enter.exact.prevent="handleAskKeydown"
        />

        <div class="assistant-side-actions">
          <div class="assistant-context-actions">
            <el-tooltip content="开启新对话（保留原文、摘要和历史记录）" placement="top">
              <button
                class="assistant-action-button"
                type="button"
                aria-label="开启新对话"
                :disabled="askingQuestion || generatingAiSummary || startingNewChat"
                @click="$emit('new-chat')"
              >
                <SvgMaskIcon :src="newChatIcon" :size="18" />
              </button>
            </el-tooltip>

            <el-tooltip content="生成 AI 摘要" placement="top">
              <button
                class="assistant-action-button assistant-regenerate-button"
                :class="{ loading: generatingAiSummary }"
                type="button"
                aria-label="生成 AI 摘要"
                :disabled="!canGenerateAiSummary || askingQuestion || generatingAiSummary || startingNewChat"
                @click="$emit('generate-ai-summary')"
              >
                <SvgMaskIcon :src="summaryIcon" :size="18" />
              </button>
            </el-tooltip>

            <el-tooltip content="导出当前 AI 对话为 Markdown" placement="top">
              <button
                class="assistant-action-button assistant-export-button"
                :class="{ loading: exportingMarkdown }"
                type="button"
                aria-label="导出当前 AI 对话为 Markdown"
                :disabled="exportingMarkdown || !hasExportableConversation"
                @click="$emit('export-markdown')"
              >
                <SvgMaskIcon :src="exportIcon" :size="18" />
              </button>
            </el-tooltip>

            <el-tooltip :content="customActionLoading ? `正在使用${customActionLabel}` : `在当前对话中使用${customActionLabel}`" placement="top">
              <button
                class="assistant-action-button assistant-custom-button"
                :class="{ loading: customActionLoading }"
                type="button"
                :aria-label="`在当前对话中使用${customActionLabel}`"
                :disabled="askingQuestion || generatingAiSummary || startingNewChat || !currentQaEnabled"
                @click="$emit('run-content-analysis')"
              >
                <SvgMaskIcon :src="customActionIcon" :size="18" />
              </button>
            </el-tooltip>
          </div>

          <button
            class="assistant-send-button vk-ai-send-button"
            :class="{ active: questionInput.trim(), 'is-launching': sendLaunchActive }"
            type="button"
            aria-label="发送"
            :disabled="!questionInput.trim() || askingQuestion || generatingAiSummary || startingNewChat || !currentQaEnabled"
            @click="triggerQuestionSend"
          >
            <SvgMaskIcon class="vk-ai-send-icon" :src="sendIcon" :size="16" />
          </button>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'
import AiSkeletonStream from '../../components/AiSkeletonStream.vue'
import { useConversationScrollController } from './useConversationScrollController.js'
import {
  assistantAiModelOptions,
  assistantQuestionPlaceholder,
  assistantSelectedModelLabel,
  conversationEmptyState,
  customContentActionLabel,
  externalImportCitation as externalImportCitationForContent,
  hasExportableConversation as hasExportableConversationForContent,
  ocrAssistantPresentation,
  qaShortcutButtons as buildQaShortcutButtons,
  selectedTextPreview,
  shortcutSuggestions as findShortcutSuggestions,
  summaryTitleMarkdown,
} from './assistantPresentation.js'
const summaryIcon = 'apple.intelligence'
const customActionIcon = 'dot.scope'
const exportIcon = 'arrow.down.document'
const newChatIcon = 'ellipsis.bubble'
const emptyDocumentIcon = 'questionmark.bubble.fill'
const emptyConversationIcon = 'bubble.and.pencil'
const sendIcon = 'custom.paperplane.fill'
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
  contentContext: {
    type: Object,
    default: null
  },
  currentObsidianPath: {
    type: String,
    default: ''
  },
  conversationKey: {
    type: String,
    default: ''
  },
  markdownState: {
    type: Object,
    required: true
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
  generatingSummaryText: {
    type: String,
    default: ''
  },
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
  lastQaSaved: {
    type: Boolean,
    default: false
  },
  taskStatus: {
    type: String,
    default: 'idle'
  },
  hasTaskProgress: {
    type: Boolean,
    default: false
  },
  currentStageLabel: {
    type: String,
    default: ''
  },
  result: {
    type: Object,
    required: true
  },
  totalElapsed: {
    type: Number,
    default: null
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
  markdownSyncLabel: {
    type: Function,
    required: true
  },
  renderMarkdown: {
    type: Function,
    required: true
  },
  statusTagType: {
    type: Function,
    required: true
  },
  statusLabel: {
    type: Function,
    required: true
  },
  modelLabel: {
    type: Function,
    required: true
  },
  formatSeconds: {
    type: Function,
    required: true
  },
  roundedProgress: {
    type: Function,
    required: true
  },
  progressStatus: {
    type: Function,
    required: true
  }
})

const emit = defineEmits([
  'open-markdown',
  'copy-link',
  'update:questionInput',
  'update:selectedAiModel',
  'new-chat',
  'generate-ai-summary',
  'ask-question',
  'clear-selected-text-context',
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

const modelMenuOpen = ref(false)
const shortcutMenuOpen = ref(false)
const modelMenuRef = ref(null)
const shortcutMenuRef = ref(null)
const shortcutSuggestionsRef = ref(null)
const questionInputRef = ref(null)
const sendLaunchActive = ref(false)
let sendLaunchTimer = null
const aiModelOptions = computed(() => {
  return assistantAiModelOptions(props.selectedAiModel, props.availableAiModels)
})

const selectedAiModelLabel = computed(() => {
  return assistantSelectedModelLabel(props.selectedAiModel, aiModelOptions.value)
})
const customActionLabel = computed(() => {
  return customContentActionLabel(props.contentAnalysisTemplates)
})
const customActionLoading = computed(() => props.askingQuestion && !props.generatingAiSummary)
const externalImportCitation = computed(() => externalImportCitationForContent(props.contentContext))
const qaShortcutButtons = computed(() => buildQaShortcutButtons(props.qaShortcutTemplates))
const shortcutSuggestions = computed(() => {
  return findShortcutSuggestions(props.questionInput, qaShortcutButtons.value)
})
const hasExportableConversation = computed(() => hasExportableConversationForContent(props.currentInsightHtml, props.qaHistory))
const emptyState = computed(() => conversationEmptyState({
  conversationKey: props.conversationKey,
  currentQaEnabled: props.currentQaEnabled,
  currentQaHint: props.currentQaHint,
  currentInsightHtml: props.currentInsightHtml,
  generatingAiSummary: props.generatingAiSummary,
  generatingSummaryText: props.generatingSummaryText,
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
const ocrPresentation = computed(() => ocrAssistantPresentation(props.articleOcrStatus, props.prioritizingArticleOcr))
const showOcrControl = computed(() => ocrPresentation.value.show)
const canPrioritizeOcr = computed(() => ocrPresentation.value.canPrioritize)
const ocrControlLabel = computed(() => ocrPresentation.value.label)
const ocrControlTooltip = computed(() => ocrPresentation.value.tooltip)
const ocrInputHint = computed(() => ocrPresentation.value.inputHint)
const questionPlaceholder = computed(() => {
  return assistantQuestionPlaceholder({
    ocrInputHint: ocrInputHint.value,
    selectedTextContext: props.selectedTextContext,
    currentQaHint: props.currentQaHint,
    currentQaEnabled: props.currentQaEnabled,
  })
})
const {
  conversationRef,
  handleConversationScroll,
  handleConversationWheel,
  handleTimestampLinkClick,
} = useConversationScrollController({ props, emit })

function selectAiModel(model) {
  emit('update:selectedAiModel', model)
  modelMenuOpen.value = false
}

function closeAssistantMenus() {
  modelMenuOpen.value = false
  shortcutMenuOpen.value = false
}

function toggleModelMenu() {
  const shouldOpen = !modelMenuOpen.value
  closeAssistantMenus()
  modelMenuOpen.value = shouldOpen
}

function toggleShortcutMenu() {
  const shouldOpen = !shortcutMenuOpen.value
  closeAssistantMenus()
  shortcutMenuOpen.value = shouldOpen
}

function handleMenuFocusOut(menu, event) {
  const container = menu === 'model' ? modelMenuRef.value : shortcutMenuRef.value
  if (container?.contains(event.relatedTarget)) return
  if (menu === 'shortcut' && shortcutSuggestionsRef.value?.contains(event.relatedTarget)) return
  if (menu === 'model') modelMenuOpen.value = false
  else shortcutMenuOpen.value = false
}

function handleOutsidePointerDown(event) {
  if (modelMenuOpen.value && !modelMenuRef.value?.contains(event.target)) modelMenuOpen.value = false
  if (
    shortcutMenuOpen.value
    && !shortcutMenuRef.value?.contains(event.target)
    && !shortcutSuggestionsRef.value?.contains(event.target)
  ) shortcutMenuOpen.value = false
}

function insertShortcut(name) {
  shortcutMenuOpen.value = false
  emit('insert-shortcut', name)
}

function askStarterPrompt(prompt) {
  if (!isConversationStarterReady.value) return
  emit('ask-question', prompt)
}

function handleAskKeydown(event) {
  if (event.isComposing) return
  triggerQuestionSend()
}

function resizeQuestionInput(input = questionInputRef.value) {
  if (!input) return
  input.style.height = 'auto'
  const maxHeight = Number.parseFloat(window.getComputedStyle(input).maxHeight)
  const nextHeight = Number.isFinite(maxHeight)
    ? Math.min(input.scrollHeight, maxHeight)
    : input.scrollHeight
  input.style.height = `${nextHeight}px`
  input.style.overflowY = Number.isFinite(maxHeight) && input.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function handleQuestionInput(event) {
  emit('update:questionInput', event.target.value)
  resizeQuestionInput(event.target)
}

function triggerQuestionSend() {
  if (!props.questionInput.trim() || props.askingQuestion || !props.currentQaEnabled) return
  sendLaunchActive.value = false
  requestAnimationFrame(() => {
    sendLaunchActive.value = true
  })
  if (sendLaunchTimer !== null) clearTimeout(sendLaunchTimer)
  sendLaunchTimer = window.setTimeout(() => {
    sendLaunchActive.value = false
    sendLaunchTimer = null
  }, 600)
  emit('ask-question')
}

watch(() => props.selectedTextContext?.id || '', async (contextId) => {
  if (!contextId) return
  await nextTick()
  questionInputRef.value?.focus({ preventScroll: true })
})

watch(() => props.questionInput, () => {
  nextTick(() => resizeQuestionInput())
})


onMounted(() => {
  document.addEventListener('pointerdown', handleOutsidePointerDown)
  nextTick(() => resizeQuestionInput())
  if (props.selectedTextContext?.id) nextTick(() => questionInputRef.value?.focus({ preventScroll: true }))
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutsidePointerDown)
  if (sendLaunchTimer !== null) clearTimeout(sendLaunchTimer)
})
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

.assistant-conversation,
.assistant-input {
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

.assistant-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 22px;
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-strong);
  letter-spacing: var(--vk-tracking-meta);
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
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

.assistant-message-selection,
.assistant-selected-context {
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

.assistant-message-selection strong,
.assistant-selected-context-label {
  flex: 0 0 auto;
  color: var(--vk-accent-strong);
  font-weight: var(--vk-weight-strong);
}

.assistant-message-selection span,
.assistant-selected-context-copy {
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

.assistant-action-button {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
}

.assistant-action-button:hover {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.assistant-action-button:disabled {
  cursor: default;
  opacity: 0.42;
}

.assistant-regenerate-button.loading :deep(.svg-mask-icon) {
  animation: assistant-regenerate-pulse 0.95s ease-in-out infinite alternate;
}

.assistant-export-button.loading :deep(.svg-mask-icon) {
  animation: assistant-regenerate-pulse 0.95s ease-in-out infinite alternate;
}

.assistant-custom-button.loading :deep(.svg-mask-icon) {
  animation: assistant-regenerate-pulse 0.95s ease-in-out infinite alternate;
}

@keyframes assistant-regenerate-pulse {
  from { opacity: 0.45; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}

.assistant-input {
  position: sticky;
  bottom: 0;
  z-index: 20;
  padding: 10px 6px 12px;
  box-sizing: border-box;
  overflow: visible;
  background: color-mix(in srgb, var(--vk-bg-quiet) 86%, transparent);
  border-top: 0;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.assistant-input-panel {
  position: relative;
  width: 100%;
  max-width: 100%;
  display: grid;
  gap: 6px;
  min-width: 0;
  box-sizing: border-box;
  padding: 9px 8px 10px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: 12px;
  background: var(--vk-bg-panel);
  box-shadow: 0 6px 18px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.assistant-input-tools {
  width: 100%;
  max-width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 6px;
  min-width: 0;
  padding-right: 0;
  box-sizing: border-box;
  overflow-x: auto;
  overflow-y: hidden;
  overscroll-behavior-inline: contain;
  scrollbar-width: none;
}

.assistant-input-tools::-webkit-scrollbar {
  display: none;
}

.assistant-input-tools:has(.assistant-model-pill.open) {
  overflow-x: clip;
  overflow-y: visible;
}

.assistant-command-menu-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: 999px;
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  font-size: var(--vk-type-label-size);
  cursor: pointer;
}

.assistant-command-menu-button:hover:not(:disabled),
.assistant-command-menu-button.active {
  border-color: color-mix(in srgb, var(--vk-accent) 36%, var(--vk-border));
  color: var(--vk-accent-strong);
}

.assistant-command-menu-button:disabled {
  opacity: 0.45;
  cursor: default;
}

.assistant-ocr-button.complete {
  color: color-mix(in srgb, var(--vk-success) 82%, var(--vk-muted));
}

.assistant-command-menu {
  display: inline-flex;
  flex: 0 0 auto;
}

.assistant-menu-chevron {
  transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
  transform-origin: center;
}

.assistant-model-pill.open .assistant-menu-chevron,
.assistant-command-menu-button.active .assistant-menu-chevron {
  transform: rotate(180deg);
}

@media (prefers-reduced-motion: reduce) {
  .assistant-message-new,
  .assistant-menu-chevron,
  .assistant-starter-prompt,
  .assistant-empty-state-enter-active,
  .assistant-empty-state-leave-active {
    transform: none;
    transition: opacity var(--vk-motion-fast) ease;
  }

  .assistant-regenerate-button.loading :deep(.svg-mask-icon),
  .assistant-export-button.loading :deep(.svg-mask-icon),
  .assistant-custom-button.loading :deep(.svg-mask-icon) {
    transform: none;
    animation: none !important;
    opacity: 0.72;
  }

}

@keyframes assistant-loading-fade {
  from { opacity: 0.5; }
  to { opacity: 0.85; }
}

.assistant-shortcut-suggestions {
  position: absolute;
  right: 8px;
  bottom: calc(100% + 8px);
  left: 8px;
  z-index: 45;
  display: grid;
  gap: 2px;
  max-height: min(240px, 40vh);
  padding: 5px;
  border: 1px solid var(--vk-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--vk-bg-panel) 96%, transparent);
  box-shadow: 0 12px 30px color-mix(in srgb, var(--vk-text) 14%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  overflow-y: auto;
  transform-origin: left bottom;
}

.assistant-shortcut-pop-enter-active {
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    transform var(--vk-motion-standard) var(--vk-ease-out);
}

.assistant-shortcut-pop-leave-active {
  transition:
    opacity var(--vk-motion-fast) var(--vk-ease-out),
    transform var(--vk-motion-fast) var(--vk-ease-out);
}

.assistant-shortcut-pop-enter-from,
.assistant-shortcut-pop-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(.97);
}

@media (prefers-reduced-motion: reduce) {
  .assistant-shortcut-pop-enter-active,
  .assistant-shortcut-pop-leave-active {
    transition: opacity var(--vk-motion-fast) ease;
  }

  .assistant-shortcut-pop-enter-from,
  .assistant-shortcut-pop-leave-to {
    transform: none;
  }
}

.assistant-shortcut-suggestion {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 7px 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.assistant-shortcut-suggestion:hover {
  background: var(--vk-bg-hover);
}

.assistant-shortcut-suggestion strong {
  color: var(--vk-accent-strong);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-heading);
}

.assistant-shortcut-suggestion span {
  overflow: hidden;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-side-actions {
  min-height: 30px;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  pointer-events: none;
}

.assistant-side-actions > * {
  pointer-events: auto;
}

.assistant-context-actions {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.assistant-model-menu {
  position: relative;
  min-width: max-content;
  z-index: 30;
}

.assistant-model-pill {
  max-width: none;
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--vk-accent) 20%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-accent) 9%, transparent);
  color: var(--vk-accent-strong);
  font: inherit;
  font-size: var(--vk-type-label-size);
  cursor: pointer;
}

.assistant-model-pill span {
  min-width: auto;
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
}

.assistant-model-options {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  z-index: 40;
  min-width: 180px;
  max-width: min(280px, calc(100vw - 32px));
  max-height: min(240px, 50vh);
  display: grid;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--vk-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--vk-bg-panel) 96%, transparent);
  box-shadow: 0 12px 30px color-mix(in srgb, var(--vk-text) 14%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  overflow-y: auto;
  transform-origin: left bottom;
}

.assistant-model-pop-enter-active {
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    transform var(--vk-motion-standard) var(--vk-ease-out);
}

.assistant-model-pop-leave-active {
  transition:
    opacity var(--vk-motion-fast) var(--vk-ease-out),
    transform var(--vk-motion-fast) var(--vk-ease-out);
}

.assistant-model-pop-enter-from,
.assistant-model-pop-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(.97);
}

@media (prefers-reduced-motion: reduce) {
  .assistant-model-pop-enter-active,
  .assistant-model-pop-leave-active {
    transition: opacity var(--vk-motion-fast) ease;
  }

  .assistant-model-pop-enter-from,
  .assistant-model-pop-leave-to {
    transform: none;
  }
}

.assistant-model-option {
  min-width: 0;
  min-height: 32px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  text-align: left;
  cursor: pointer;
}

.assistant-model-option:hover,
.assistant-model-option.active {
  background: var(--vk-bg-hover);
  color: var(--vk-accent-strong);
}

.assistant-question-textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 21px;
  max-height: 121px;
  resize: none;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-body-size);
  line-height: var(--vk-leading-body);
  padding: 0;
  overflow-y: hidden;
}

.assistant-selected-context {
  min-height: 18px;
  padding: 0 2px;
}

.assistant-question-textarea::placeholder {
  color: color-mix(in srgb, var(--vk-muted) 68%, transparent);
}

.insight-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.insight-meta span {
  padding: 5px 7px;
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-control);
  color: var(--vk-muted);
  background: var(--vk-bg-panel);
  font-size: var(--vk-type-label-size);
}

@media (prefers-reduced-transparency: reduce) {
  .assistant-input,
  .assistant-shortcut-suggestions,
  .assistant-model-options {
    background: var(--vk-bg-panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
  .assistant-input {
    border-top: 1px solid color-mix(in srgb, var(--vk-text) 38%, var(--vk-border));
    background: var(--vk-bg-panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }

  .assistant-input-panel,
  .assistant-shortcut-suggestions,
  .assistant-model-options {
    border-color: color-mix(in srgb, var(--vk-text) 46%, var(--vk-border));
    background: var(--vk-bg-panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
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

  .assistant-input {
    grid-template-columns: 1fr;
  }
}
</style>
