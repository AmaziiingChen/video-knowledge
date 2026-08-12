<template>
  <section class="assistant-input">
    <div class="assistant-input-panel">
      <div class="assistant-input-tools">
        <div ref="modelMenuRef" class="assistant-model-menu" @focusout="handleMenuFocusOut('model', $event)">
          <button class="assistant-model-pill" :class="{ open: modelMenuOpen }" type="button" aria-label="切换模型" :aria-expanded="modelMenuOpen" :disabled="modelSwitchDisabled" @click="toggleModelMenu" @keydown.esc="closeAssistantMenus">
            <span>{{ selectedAiModelLabel }}</span>
            <SvgMaskIcon class="assistant-menu-chevron" src="chevron.down" :size="14" />
          </button>
          <Transition name="assistant-model-pop">
            <div v-if="modelMenuOpen" class="assistant-model-options">
              <button v-for="model in aiModelOptions" :key="model.value" class="assistant-model-option" :class="{ active: model.value === selectedAiModel }" type="button" :disabled="model.disabled" @click="selectAiModel(model.value)">
                <span>{{ model.label }}</span>
              </button>
            </div>
          </Transition>
        </div>
        <div v-if="qaShortcutButtons.length" ref="shortcutMenuRef" class="assistant-command-menu" @focusout="handleMenuFocusOut('shortcut', $event)">
          <button class="assistant-command-menu-button" :class="{ active: shortcutMenuOpen }" type="button" :aria-expanded="shortcutMenuOpen" :disabled="askingQuestion || !currentQaEnabled" @click="toggleShortcutMenu" @keydown.esc="closeAssistantMenus">
            <span>快捷命令</span>
            <SvgMaskIcon class="assistant-menu-chevron" src="chevron.down" :size="14" />
          </button>
        </div>
        <el-tooltip v-if="showOcrControl" :content="ocrControlTooltip" placement="top">
          <button class="assistant-command-menu-button assistant-ocr-button" :class="{ active: articleOcrStatus.priority }" type="button" :disabled="!canPrioritizeOcr" @click="$emit('prioritize-ocr')">
            {{ ocrControlLabel }}
          </button>
        </el-tooltip>
      </div>

      <Transition name="assistant-shortcut-pop">
        <div v-if="shortcutMenuOpen" ref="shortcutSuggestionsRef" class="assistant-shortcut-suggestions" role="listbox">
          <button v-for="shortcut in qaShortcutButtons" :key="shortcut.id" class="assistant-shortcut-suggestion" type="button" @click="insertShortcut(shortcut.name)">
            <strong>@{{ shortcut.name }}</strong>
            <span>{{ shortcut.template }}</span>
          </button>
        </div>
      </Transition>

      <div v-if="!shortcutMenuOpen && shortcutSuggestions.length" ref="shortcutSuggestionsRef" class="assistant-shortcut-suggestions" role="listbox">
        <button v-for="shortcut in shortcutSuggestions" :key="shortcut.id" class="assistant-shortcut-suggestion" type="button" @click="insertShortcut(shortcut.name)">
          <strong>@{{ shortcut.name }}</strong>
          <span>{{ shortcut.template }}</span>
        </button>
      </div>

      <textarea ref="questionInputRef" class="assistant-question-textarea" name="assistant-question" autocomplete="off" aria-label="向当前内容提问" :value="questionInput" :placeholder="questionPlaceholder" rows="1" @input="handleQuestionInput" @keydown.enter.exact.prevent="handleAskKeydown" />

      <div class="assistant-side-actions">
        <div class="assistant-context-actions">
          <el-tooltip content="开启新对话（保留原文、摘要和历史记录）" placement="top">
            <button class="assistant-action-button" type="button" aria-label="开启新对话" :disabled="askingQuestion || generatingAiSummary || startingNewChat" @click="$emit('new-chat')">
              <SvgMaskIcon :src="newChatIcon" :size="18" />
            </button>
          </el-tooltip>
          <el-tooltip content="生成 AI 摘要" placement="top">
            <button class="assistant-action-button assistant-regenerate-button" :class="{ loading: generatingAiSummary }" type="button" aria-label="生成 AI 摘要" :disabled="!canGenerateAiSummary || askingQuestion || generatingAiSummary || startingNewChat" @click="$emit('generate-ai-summary')">
              <SvgMaskIcon :src="summaryIcon" :size="18" />
            </button>
          </el-tooltip>
          <el-tooltip content="导出当前 AI 对话为 Markdown" placement="top">
            <button class="assistant-action-button assistant-export-button" :class="{ loading: exportingMarkdown }" type="button" aria-label="导出当前 AI 对话为 Markdown" :disabled="exportingMarkdown || !hasExportableConversation" @click="$emit('export-markdown')">
              <SvgMaskIcon :src="exportIcon" :size="18" />
            </button>
          </el-tooltip>
          <el-tooltip :content="customActionLoading ? `正在使用${customActionLabel}` : `在当前对话中使用${customActionLabel}`" placement="top">
            <button class="assistant-action-button assistant-custom-button" :class="{ loading: customActionLoading }" type="button" :aria-label="`在当前对话中使用${customActionLabel}`" :disabled="askingQuestion || generatingAiSummary || startingNewChat || !currentQaEnabled" @click="$emit('run-content-analysis')">
              <SvgMaskIcon :src="customActionIcon" :size="18" />
            </button>
          </el-tooltip>
        </div>
        <button class="assistant-send-button vk-ai-send-button" :class="{ active: questionInput.trim(), 'is-launching': sendLaunchActive }" type="button" aria-label="发送" :disabled="!questionInput.trim() || askingQuestion || generatingAiSummary || startingNewChat || !currentQaEnabled" @click="triggerQuestionSend">
          <SvgMaskIcon class="vk-ai-send-icon" :src="sendIcon" :size="16" />
        </button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'
import { useAssistantComposerController } from './useAssistantComposerController.js'

const summaryIcon = 'apple.intelligence'
const customActionIcon = 'dot.scope'
const exportIcon = 'arrow.down.document'
const newChatIcon = 'ellipsis.bubble'
const sendIcon = 'custom.paperplane.fill'

const props = defineProps({
  questionInput: { type: String, default: '' },
  selectedAiModel: { type: String, default: 'deepseek-v4-flash:enabled' },
  availableAiModels: { type: Array, default: () => [] },
  qaShortcutTemplates: { type: Array, default: () => [] },
  articleOcrStatus: { type: Object, default: () => ({ status: 'unavailable', has_images: false, priority: false }) },
  prioritizingArticleOcr: { type: Boolean, default: false },
  selectedTextContext: { type: Object, default: null },
  askingQuestion: { type: Boolean, default: false },
  generatingAiSummary: { type: Boolean, default: false },
  startingNewChat: { type: Boolean, default: false },
  currentQaEnabled: { type: Boolean, default: false },
  currentQaHint: { type: String, default: '' },
  canGenerateAiSummary: { type: Boolean, default: false },
  exportingMarkdown: { type: Boolean, default: false },
  contentAnalysisTemplates: { type: Array, default: () => [] },
  currentInsightHtml: { type: String, default: '' },
  qaHistory: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:questionInput', 'update:selectedAiModel', 'prioritize-ocr', 'insert-shortcut',
  'new-chat', 'generate-ai-summary', 'export-markdown', 'run-content-analysis', 'ask-question',
])

const modelSwitchDisabled = computed(() => props.askingQuestion || props.generatingAiSummary || props.startingNewChat)

const {
  modelMenuOpen, shortcutMenuOpen, modelMenuRef, shortcutMenuRef, shortcutSuggestionsRef,
  questionInputRef, sendLaunchActive, aiModelOptions, selectedAiModelLabel, customActionLabel,
  customActionLoading, qaShortcutButtons, shortcutSuggestions, hasExportableConversation,
  showOcrControl, canPrioritizeOcr, ocrControlLabel, ocrControlTooltip, questionPlaceholder,
  selectAiModel, closeAssistantMenus, toggleModelMenu, toggleShortcutMenu, handleMenuFocusOut,
  insertShortcut, handleQuestionInput, handleAskKeydown, triggerQuestionSend,
  mount: mountAssistantComposer, dispose: disposeAssistantComposer,
} = useAssistantComposerController({ props, emit })

onMounted(mountAssistantComposer)
onBeforeUnmount(disposeAssistantComposer)
</script>

<style scoped src="./assistantComposer.css"></style>
