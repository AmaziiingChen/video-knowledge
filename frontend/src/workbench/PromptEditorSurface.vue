<template>
  <section
    class="editor-surface prompt-editor-surface"
    @keydown.meta.s.prevent="saveCurrentPrompt"
    @keydown.ctrl.s.prevent="saveCurrentPrompt"
  >
    <div v-if="activePromptTabId" v-loading="promptWorkspaceLoading" class="prompt-editor-main">
      <div class="prompt-function-bar">
        <div class="prompt-usage" aria-label="提示词使用说明">
          <strong>使用说明</strong>
          <span v-if="isSystemPromptEditor" class="prompt-system-readonly">系统角色 · 只读核验</span>
          <span v-else-if="isPromptContextEditor" class="prompt-system-readonly">任务上下文 · 只读核验</span>
          <span><b>入口</b>{{ activePromptContract.entry }}</span>
          <span><b>输入</b>{{ activePromptContract.input }}</span>
          <span><b>输出</b>{{ activePromptContract.output }}</span>
          <span v-if="activePromptContract.variables.length" class="prompt-contract-variables">
            <b>变量</b><code v-for="variable in activePromptContract.variables" :key="variable">{{ variable }}</code>
            <em>删除变量后，运行时仍会附加必要输入</em>
          </span>
        </div>
        <div class="prompt-editor-actions">
          <span v-if="currentPromptDirty" class="prompt-editor-dirty">未保存</span>
          <el-button
            v-if="!isReadOnlyPromptEditor && !isReportPromptEditor && selectedPromptTemplateId && !selectedPromptTemplate?.is_active"
            class="prompt-activate-button"
            size="small"
            :loading="activatingPromptTemplate"
            @click="$emit('activate-prompt-template', selectedPromptTemplateId)"
          >
            设为启用
          </el-button>
          <el-button
            v-if="!isReadOnlyPromptEditor && (selectedPromptTemplateId || selectedWechatReportPrompt)"
            class="prompt-reset-button"
            size="small"
            :disabled="currentPromptSaving"
            @click="requestPromptReset"
          >
            <el-icon><Refresh /></el-icon>
            恢复默认
          </el-button>
          <el-button
            v-if="!isReadOnlyPromptEditor"
            class="prompt-save-button"
            size="small"
            type="primary"
            aria-keyshortcuts="Meta+S Control+S"
            :loading="currentPromptSaving"
            :disabled="!canSaveCurrentPrompt"
            @click="saveCurrentPrompt"
          >
            保存
          </el-button>
        </div>
      </div>

      <el-input
        class="prompt-editor-text"
        :model-value="isReportPromptEditor ? wechatReportPromptText : promptEditorText"
        type="textarea"
        resize="none"
        :name="isReportPromptEditor ? 'wechat-report-prompt' : 'prompt-template-content'"
        autocomplete="off"
        :aria-label="isReportPromptEditor ? '报告提示词' : '提示词内容'"
        :placeholder="isReportPromptEditor ? '编辑报告提示词…' : '编辑当前提示词…'"
        :readonly="isReadOnlyPromptEditor"
        @update:model-value="updateCurrentPromptText"
      />
    </div>
    <div v-else class="prompt-editor-empty">
      <SvgMaskIcon src="append.page" :size="42" />
      <strong>从左侧文件树打开提示词</strong>
      <span>提示词会在标签页中打开，可同时编辑多个文件。</span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { promptTaskContracts, promptTemplateDisplayName } from '../config/promptInterface'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'

const props = defineProps({
  promptWorkspaceTabs: { type: Array, default: () => [] },
  activePromptTabId: { type: String, default: '' },
  promptTaskType: { type: String, default: 'summary' },
  promptTemplates: { type: Array, default: () => [] },
  selectedPromptTemplateId: { type: String, default: '' },
  loadingPrompts: { type: Boolean, default: false },
  promptEditorText: { type: String, default: '' },
  promptEditorName: { type: String, default: '' },
  savingPromptTemplate: { type: Boolean, default: false },
  activatingPromptTemplate: { type: Boolean, default: false },
  wechatReportPrompts: { type: Array, default: () => [] },
  selectedWechatReportPromptGroupId: { type: String, default: '' },
  selectedWechatReportPromptType: { type: String, default: 'group_context' },
  wechatReportPromptText: { type: String, default: '' },
  loadingWechatReportPrompts: { type: Boolean, default: false },
  savingWechatReportPrompt: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:promptEditorText',
  'update:wechat-report-prompt-text',
  'activate-prompt-template',
  'save-prompt',
  'save-wechat-report-prompt',
  'reset-prompt',
])

const activePromptWorkspaceTab = computed(() => (
  props.promptWorkspaceTabs.find((tab) => tab.id === props.activePromptTabId) || null
))
const isSystemPromptEditor = computed(() => activePromptWorkspaceTab.value?.kind === 'system')
const isPromptContextEditor = computed(() => activePromptWorkspaceTab.value?.kind === 'context')
const isReadOnlyPromptEditor = computed(() => isSystemPromptEditor.value || isPromptContextEditor.value)
const isReportPromptEditor = computed(() => props.promptTaskType === 'wechat_reports')
const selectedPromptTemplate = computed(() => (
  props.promptTemplates.find((template) => template.id === props.selectedPromptTemplateId) || null
))
const selectedWechatReportPrompt = computed(() => (
  props.wechatReportPrompts.find((item) => (
    item.group_id === props.selectedWechatReportPromptGroupId
    && item.report_type === props.selectedWechatReportPromptType
  )) || null
))
const activePromptContract = computed(() => promptTaskContracts[props.promptTaskType] || {
  entry: '知识处理流程',
  input: '当前任务材料',
  output: 'AI 生成内容',
  variables: [],
})
const standardPromptDirty = computed(() => {
  if (isReadOnlyPromptEditor.value || isReportPromptEditor.value) return false
  if (!selectedPromptTemplate.value) {
    return Boolean(props.promptEditorName.trim() || props.promptEditorText.trim())
  }
  return props.promptEditorName !== promptTemplateDisplayName(selectedPromptTemplate.value)
    || props.promptEditorText !== selectedPromptTemplate.value.template
})
const reportPromptDirty = computed(() => (
  isReportPromptEditor.value
  && selectedWechatReportPrompt.value
  && props.wechatReportPromptText !== selectedWechatReportPrompt.value.template
))
const currentPromptDirty = computed(() => (
  isReportPromptEditor.value ? reportPromptDirty.value : standardPromptDirty.value
))
const canSaveCurrentPrompt = computed(() => {
  if (!currentPromptDirty.value) return false
  if (isReportPromptEditor.value) {
    return Boolean(selectedWechatReportPrompt.value && props.wechatReportPromptText.trim())
  }
  return Boolean(props.promptEditorName.trim() && props.promptEditorText.trim())
})
const promptWorkspaceLoading = computed(() => (
  isReportPromptEditor.value ? props.loadingWechatReportPrompts : props.loadingPrompts
))
const currentPromptSaving = computed(() => (
  isReportPromptEditor.value ? props.savingWechatReportPrompt : props.savingPromptTemplate
))

function updateCurrentPromptText(value) {
  if (isReadOnlyPromptEditor.value) return
  emit(isReportPromptEditor.value ? 'update:wechat-report-prompt-text' : 'update:promptEditorText', value)
}

function saveCurrentPrompt() {
  if (!canSaveCurrentPrompt.value || currentPromptSaving.value) return
  emit(isReportPromptEditor.value ? 'save-wechat-report-prompt' : 'save-prompt')
}

function requestPromptReset() {
  if (currentPromptSaving.value) return
  emit('reset-prompt')
}
</script>

<style scoped>
.editor-surface {
  height: 100%;
  min-height: 100%;
  overflow: hidden;
  border: 0;
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-center);
  color: var(--vk-text);
}

.prompt-editor-surface {
  display: grid;
  grid-template-rows: minmax(0, 1fr);
  min-height: 0;
}

.prompt-editor-main {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.prompt-function-bar {
  min-width: 0;
  min-height: 42px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--vk-space-sm);
  padding: var(--vk-space-micro) var(--vk-space-control);
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
}

.prompt-usage {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--vk-space-micro) var(--vk-space-cluster);
  color: var(--vk-text);
  font-size: var(--vk-type-meta-size);
  line-height: 1.4;
}

.prompt-usage > strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: 600;
}

.prompt-usage span {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-micro);
}

.prompt-usage b {
  color: var(--vk-muted);
  font-weight: 500;
}

.prompt-usage code {
  color: var(--vk-accent-strong);
  font-family: var(--vk-font-mono);
  font-size: inherit;
}

.prompt-usage em {
  color: var(--vk-muted);
  font-style: normal;
}

.prompt-editor-actions {
  min-width: 0;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: var(--vk-space-xs);
}

.prompt-editor-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.prompt-editor-dirty {
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-micro);
  color: var(--vk-warning);
  font-size: var(--vk-type-meta-size);
  font-weight: 500;
  white-space: nowrap;
}

.prompt-editor-dirty::before {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  content: '';
}

.prompt-save-button {
  min-width: 58px;
}

.prompt-save-button,
.prompt-reset-button {
  border-radius: var(--vk-radius-control);
}

.prompt-reset-button {
  min-width: 84px;
}

.prompt-activate-button {
  border-radius: var(--vk-radius-control);
}

.prompt-editor-empty {
  grid-row: 1 / -1;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: var(--vk-space-sm);
  min-height: 0;
  padding: var(--vk-space-page);
  color: var(--vk-muted);
  text-align: center;
}

.prompt-editor-empty :deep(.svg-mask-icon) {
  color: var(--vk-accent-strong);
  opacity: 0.72;
}

.prompt-editor-empty strong {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: 600;
}

.prompt-editor-empty span {
  font-size: var(--vk-type-label-size);
}

.prompt-editor-text {
  min-height: 0;
  height: 100%;
}

.prompt-editor-text :deep(.el-textarea__inner) {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  border-color: var(--vk-border);
  border-width: 0;
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
  color: var(--vk-text);
  font-family: var(--vk-font-mono);
  font-size: var(--vk-type-body-size);
  line-height: 1.7;
  padding: var(--vk-space-panel) var(--vk-space-page) var(--vk-space-section);
  box-shadow: none;
}
</style>
