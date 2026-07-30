<template>
  <el-dialog
    :model-value="visible"
    class="wechat-cover-plan-dialog"
    width="min(920px, calc(100vw - 40px))"
    align-center
    :close-on-click-modal="!loading && !submitting"
    :close-on-press-escape="!loading && !submitting"
    :show-close="!loading && !submitting"
    @update:model-value="emit('update:visible', $event)"
  >
    <template #header>
      <div class="cover-plan-heading">
        <strong>确认公众号封面主题</strong>
        <span>先选择视觉语言；文本模型完成策划后，确认才调用图像模型。</span>
      </div>
    </template>

    <div class="cover-plan-body" :aria-busy="loading ? 'true' : 'false'">
      <section
        v-if="!hasPlan"
        class="cover-style-picker"
        :class="{ 'is-planning': loading }"
        :aria-disabled="loading ? 'true' : 'false'"
        aria-labelledby="cover-style-picker-title"
      >
        <div class="cover-style-picker-copy">
          <strong id="cover-style-picker-title">选择封面风格</strong>
          <span>选择本次策划使用的视觉语言；所有候选都会根据文章重新选题，并生成横版封面。</span>
        </div>
        <div class="cover-style-options">
          <button
            v-for="option in styleOptions"
            :key="option.value"
            type="button"
            class="cover-style-option"
            :class="{
              'is-selected': styleDraft === option.value,
              'is-planning': loading && styleDraft === option.value,
            }"
            :aria-pressed="styleDraft === option.value ? 'true' : 'false'"
            :disabled="loading"
            @click="styleDraft = option.value"
          >
            <span
              class="cover-style-option-preview"
              :class="{ 'is-zine-preview': !option.preview }"
            >
              <img
                v-if="option.preview"
                :src="option.preview"
                :alt="option.previewAlt || `${option.label}横版风格参考`"
                :style="{ objectPosition: option.previewPosition || 'center' }"
                width="720"
                height="306"
                loading="lazy"
                decoding="async"
              />
              <span v-else class="cover-style-zine-preview" aria-hidden="true">
                <i></i>
                <b>ZINE</b>
                <em>quiet matter / issue 07</em>
              </span>
              <span class="cover-style-aspect">横版</span>
              <span
                v-if="loading && styleDraft === option.value"
                class="cover-style-planning-state"
                role="status"
              >
                <span class="cover-style-planning-spinner" aria-hidden="true"></span>
                <span>
                  <strong>正在策划主题</strong>
                  <small>正在从文章中提炼核心视觉线索</small>
                </span>
              </span>
            </span>
            <span class="cover-style-option-meta">
              <span class="cover-style-option-mark" aria-hidden="true"></span>
              <span class="cover-style-option-copy">
                <strong>{{ option.label }}</strong>
                <span>{{ option.description }}</span>
              </span>
            </span>
          </button>
        </div>
      </section>

      <el-form v-else label-position="top" class="cover-plan-form">
        <div class="cover-plan-current-style">
          <span>当前风格</span>
          <strong>{{ selectedStyleOption?.label || draft.cover_style }}</strong>
          <p>{{ selectedStyleOption?.description }}</p>
        </div>

        <section class="cover-plan-primary">
          <el-form-item label="核心主题">
            <el-input
              v-model="draft.core_theme"
              name="wechat-cover-core-theme"
              maxlength="160"
              placeholder="这张封面只表达的一件事"
            />
          </el-form-item>
          <el-form-item label="选择理由">
            <el-input
              v-model="draft.selection_reason"
              name="wechat-cover-selection-reason"
              type="textarea"
              :rows="3"
              resize="none"
              maxlength="500"
            />
          </el-form-item>
          <el-form-item label="正文依据">
            <el-input
              v-model="listDraft.evidence_sections"
              name="wechat-cover-evidence"
              type="textarea"
              :rows="3"
              resize="none"
              placeholder="每行一项，写明支撑主题的章节或事实"
            />
          </el-form-item>
        </section>

        <section class="cover-plan-grid" aria-label="画面策划">
          <el-form-item label="内容类型">
            <el-input v-model="draft.content_category" name="wechat-cover-category" />
          </el-form-item>
          <el-form-item label="策划置信度">
            <el-input-number
              v-model="draft.confidence"
              name="wechat-cover-confidence"
              :min="0"
              :max="1"
              :step="0.05"
              :precision="2"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="主视觉主体">
            <el-input v-model="draft.primary_subject" name="wechat-cover-subject" />
          </el-form-item>
          <el-form-item label="画面情绪">
            <el-input v-model="draft.mood" name="wechat-cover-mood" />
          </el-form-item>
          <el-form-item label="场景与动作" class="cover-plan-span">
            <el-input
              v-model="draft.scene"
              name="wechat-cover-scene"
              type="textarea"
              :rows="2"
              resize="none"
            />
          </el-form-item>
          <el-form-item label="视觉隐喻">
            <el-input
              v-model="draft.visual_metaphor"
              name="wechat-cover-metaphor"
              placeholder="不需要时留空"
            />
          </el-form-item>
          <el-form-item label="表现风格">
            <el-input v-model="draft.rendering_style" name="wechat-cover-style" />
          </el-form-item>
          <el-form-item label="色彩">
            <el-input v-model="draft.palette" name="wechat-cover-palette" />
          </el-form-item>
          <el-form-item label="构图" class="cover-plan-span">
            <el-input
              v-model="draft.composition"
              name="wechat-cover-composition"
              type="textarea"
              :rows="2"
              resize="none"
            />
          </el-form-item>
        </section>

        <details class="cover-plan-advanced">
          <summary>辅助元素、事实约束与完整提示词</summary>
          <div class="cover-plan-advanced-fields">
            <el-form-item label="装饰微文案（可选）">
              <el-input
                v-model="draft.decorative_microcopy"
                name="wechat-cover-decorative-microcopy"
                maxlength="28"
                placeholder="留空即不生成文字；仅 Minimal Zine、孔版印刷、编辑型海报支持"
              />
            </el-form-item>
            <el-form-item label="辅助元素（最多两项）">
              <el-input
                v-model="listDraft.supporting_elements"
                name="wechat-cover-supporting-elements"
                type="textarea"
                :rows="2"
                resize="none"
                placeholder="每行一项"
              />
            </el-form-item>
            <el-form-item label="不能画错的事实">
              <el-input
                v-model="listDraft.factual_constraints"
                name="wechat-cover-factual-constraints"
                type="textarea"
                :rows="2"
                resize="none"
                placeholder="每行一项"
              />
            </el-form-item>
            <el-form-item label="本篇必须避开的内容">
              <el-input
                v-model="listDraft.must_avoid"
                name="wechat-cover-must-avoid"
                type="textarea"
                :rows="2"
                resize="none"
                placeholder="每行一项"
              />
            </el-form-item>
            <div class="cover-resolved-prompt">
              <div class="cover-resolved-prompt-head">
                <strong>实际生图提示词</strong>
                <el-button
                  size="small"
                  :loading="previewingPrompt"
                  @click="emit('preview-prompt', payload())"
                >
                  刷新
                </el-button>
              </div>
              <pre v-if="resolvedPrompt">{{ resolvedPrompt }}</pre>
              <p v-else>点击“刷新”查看当前策划解析后的完整提示词。</p>
            </div>
          </div>
        </details>
      </el-form>
    </div>

    <template #footer>
      <el-button
        :disabled="loading || submitting"
        @click="emit('update:visible', false)"
      >
        取消
      </el-button>
      <el-button
        v-if="!hasPlan"
        type="primary"
        :loading="loading"
        :disabled="loading || submitting || !styleDraft"
        @click="emit('start-plan', styleDraft)"
      >
        {{ loading ? '正在策划主题' : '开始视觉策划' }}
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="submitting"
        :disabled="loading || !canSubmit"
        @click="emit('confirm', payload())"
      >
        确认并生成封面
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
  previewingPrompt: { type: Boolean, default: false },
  plan: { type: Object, default: () => ({}) },
  resolvedPrompt: { type: String, default: '' },
  styleOptions: { type: Array, default: () => [] },
  selectedStyle: { type: String, default: 'minimal_zine' },
})

const emit = defineEmits([
  'update:visible',
  'start-plan',
  'confirm',
  'preview-prompt',
])

const styleDraft = ref(props.selectedStyle)

const draft = reactive({
  cover_style: 'minimal_zine',
  core_theme: '',
  selection_reason: '',
  confidence: 0.5,
  content_category: '',
  primary_subject: '',
  scene: '',
  visual_metaphor: '',
  decorative_microcopy: '',
  rendering_style: '',
  mood: '',
  palette: '',
  composition: '',
})

const listDraft = reactive({
  evidence_sections: '',
  supporting_elements: '',
  factual_constraints: '',
  must_avoid: '',
})

watch(
  () => props.plan,
  (value) => {
    const plan = value || {}
    for (const key of Object.keys(draft)) {
      if (key === 'confidence') {
        const confidence = Number(plan[key])
        draft[key] = Number.isFinite(confidence) ? confidence : 0.5
      } else {
        draft[key] = String(plan[key] || '')
      }
    }
    for (const key of Object.keys(listDraft)) {
      listDraft[key] = Array.isArray(plan[key]) ? plan[key].join('\n') : ''
    }
  },
  { immediate: true, deep: true },
)

watch(
  () => props.selectedStyle,
  (value) => {
    const next = String(value || 'minimal_zine')
    styleDraft.value = next
    if (!draft.core_theme) draft.cover_style = next
  },
  { immediate: true },
)

const hasPlan = computed(() => Boolean(draft.core_theme.trim()))
const selectedStyleOption = computed(() => (
  props.styleOptions.find((option) => option.value === (draft.cover_style || styleDraft.value))
  || props.styleOptions.find((option) => option.value === styleDraft.value)
))

function lines(value, maximum) {
  return String(value || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, maximum)
}

function payload() {
  return {
    ...draft,
    cover_style: String(draft.cover_style || styleDraft.value || props.selectedStyle || 'minimal_zine'),
    confidence: Number(draft.confidence || 0),
    evidence_sections: lines(listDraft.evidence_sections, 8),
    supporting_elements: lines(listDraft.supporting_elements, 2),
    factual_constraints: lines(listDraft.factual_constraints, 8),
    must_avoid: lines(listDraft.must_avoid, 12),
  }
}

const canSubmit = computed(() => {
  const value = payload()
  return Boolean(
    value.core_theme.trim()
    && value.selection_reason.trim()
    && value.evidence_sections.length
    && value.primary_subject.trim()
    && value.scene.trim()
    && value.rendering_style.trim()
    && value.mood.trim()
    && value.palette.trim()
    && value.composition.trim()
  )
})
</script>

<style scoped>
:global(.wechat-cover-plan-dialog) {
  display: flex;
  max-height: calc(100vh - 40px);
  margin-block: 20px !important;
  flex-direction: column;
}

:global(.wechat-cover-plan-dialog .el-dialog__body) {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.cover-plan-heading {
  display: grid;
  gap: var(--vk-space-xs);
}

.cover-plan-heading strong {
  color: var(--vk-text);
  font-size: var(--vk-type-heading-size);
  font-weight: var(--vk-weight-strong);
}

.cover-plan-heading span {
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-reading);
}

.cover-plan-body {
  min-height: 0;
}

.cover-style-picker {
  display: grid;
  gap: var(--vk-space-panel);
  min-height: 240px;
  padding: var(--vk-space-panel);
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
}

.cover-style-picker-copy,
.cover-style-option-copy {
  display: grid;
  gap: var(--vk-space-xs);
}

.cover-style-picker-copy strong,
.cover-style-option-copy strong {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-medium);
}

.cover-style-picker-copy span,
.cover-style-option-copy span {
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-reading);
}

.cover-style-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--vk-space-cluster);
}

.cover-style-option {
  display: grid;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-center);
  color: inherit;
  cursor: pointer;
  text-align: left;
  transition:
    border-color var(--vk-motion-fast) var(--vk-ease-out),
    background-color var(--vk-motion-fast) var(--vk-ease-out);
}

.cover-style-option-preview {
  position: relative;
  display: block;
  aspect-ratio: 2.35 / 1;
  overflow: hidden;
  border-bottom: 1px solid var(--vk-divider-subtle);
  background: var(--vk-bg-hover);
}

.cover-style-option-preview img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-style-option-preview::after {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 48%, color-mix(in srgb, var(--vk-text) 18%, transparent));
  content: "";
  pointer-events: none;
}

.cover-style-aspect {
  position: absolute;
  right: var(--vk-space-control);
  bottom: var(--vk-space-control);
  z-index: 1;
  padding: 2px var(--vk-space-xs);
  border-radius: var(--vk-radius-compact);
  background: color-mix(in srgb, var(--vk-bg-panel) 88%, transparent);
  color: var(--vk-text);
  font-size: var(--vk-type-micro-size);
  font-weight: var(--vk-weight-medium);
  line-height: 1.2;
  backdrop-filter: blur(6px);
}

.cover-style-zine-preview {
  position: absolute;
  inset: 0;
  display: block;
  overflow: hidden;
  background:
    linear-gradient(90deg, transparent 0 7%, color-mix(in srgb, var(--vk-text) 5%, transparent) 7% 7.4%, transparent 7.4%),
    color-mix(in srgb, var(--vk-bg-quiet) 76%, var(--vk-bg-panel));
  color: color-mix(in srgb, var(--vk-text) 74%, transparent);
  font-family: var(--vk-font-mono);
}

.cover-style-zine-preview::before {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(color-mix(in srgb, var(--vk-text) 12%, transparent) 0.6px, transparent 0.7px);
  background-size: 5px 5px;
  content: "";
  opacity: 0.34;
}

.cover-style-zine-preview i {
  position: absolute;
  top: 23%;
  left: 45%;
  width: 17%;
  aspect-ratio: 1;
  background: var(--vk-accent-strong);
  box-shadow: 8px 7px 0 color-mix(in srgb, var(--vk-text) 18%, transparent);
  transform: rotate(-4deg);
}

.cover-style-zine-preview b,
.cover-style-zine-preview em {
  position: absolute;
  left: 13%;
  z-index: 1;
  font-style: normal;
  letter-spacing: 0.08em;
}

.cover-style-zine-preview b {
  bottom: 25%;
  font-size: var(--vk-type-label-size);
}

.cover-style-zine-preview em {
  bottom: 14%;
  font-size: var(--vk-type-micro-size);
}

.cover-style-option-meta {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: var(--vk-space-control);
  padding: var(--vk-space-cluster);
}

.cover-style-option:hover,
.cover-style-option.is-selected {
  border-color: var(--vk-accent);
  background: var(--vk-selected-bg);
}

.cover-style-picker.is-planning .cover-style-option {
  cursor: wait;
}

.cover-style-picker.is-planning .cover-style-option:not(.is-planning) {
  opacity: 0.52;
}

.cover-style-option.is-planning {
  cursor: wait;
  opacity: 1;
}

.cover-style-planning-state {
  position: absolute;
  right: var(--vk-space-control);
  bottom: var(--vk-space-control);
  left: var(--vk-space-control);
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--vk-space-control);
  padding: var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-bg-panel) 72%, transparent);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-text) 74%, transparent);
  color: var(--vk-action-fg);
  backdrop-filter: blur(8px);
}

.cover-style-planning-state > span:last-child {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.cover-style-planning-state strong,
.cover-style-planning-state small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cover-style-planning-state strong {
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.cover-style-planning-state small {
  color: color-mix(in srgb, var(--vk-action-fg) 78%, transparent);
  font-size: var(--vk-type-micro-size);
  line-height: 1.2;
}

.cover-style-planning-spinner {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  border: 2px solid color-mix(in srgb, var(--vk-action-fg) 34%, transparent);
  border-top-color: var(--vk-action-fg);
  border-radius: 50%;
  animation: cover-style-planning-spin 800ms linear infinite;
}

@keyframes cover-style-planning-spin {
  to { transform: rotate(360deg); }
}

.cover-style-option:focus-visible {
  outline: none;
  box-shadow: var(--vk-focus-ring);
}

.cover-style-option-mark {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  margin-top: 5px;
  border: 1px solid var(--vk-border);
  border-radius: 50%;
  background: var(--vk-bg-panel);
}

.cover-style-option.is-selected .cover-style-option-mark {
  border-color: var(--vk-accent);
  background: var(--vk-accent);
  box-shadow: inset 0 0 0 2px var(--vk-bg-panel);
}

.cover-plan-form {
  display: grid;
  gap: var(--vk-space-panel);
}

.cover-plan-current-style {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: baseline;
  gap: var(--vk-space-xs) var(--vk-space-control);
  padding: var(--vk-space-cluster) var(--vk-space-panel);
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
}

.cover-plan-current-style > span,
.cover-plan-current-style p {
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
}

.cover-plan-current-style strong {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-medium);
}

.cover-plan-current-style p {
  grid-column: 2;
  margin: 0;
}

.cover-plan-primary,
.cover-plan-grid,
.cover-plan-advanced {
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
}

.cover-plan-primary {
  padding: var(--vk-space-panel);
}

.cover-plan-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--vk-space-panel);
  padding: var(--vk-space-panel);
}

.cover-plan-span {
  grid-column: 1 / -1;
}

.cover-plan-form :deep(.el-form-item) {
  margin-bottom: var(--vk-space-cluster);
}

.cover-plan-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.cover-plan-form :deep(.el-input-number) {
  width: 100%;
}

.cover-plan-advanced {
  overflow: hidden;
}

.cover-plan-advanced summary {
  padding: var(--vk-space-cluster) var(--vk-space-panel);
  color: var(--vk-text);
  cursor: pointer;
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.cover-plan-advanced-fields {
  padding: 0 var(--vk-space-panel) var(--vk-space-panel);
}

.cover-resolved-prompt {
  overflow: hidden;
  border: 1px solid var(--vk-divider-subtle);
  border-radius: var(--vk-radius-input);
  background: var(--vk-bg-center);
}

.cover-resolved-prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-control);
  padding: var(--vk-space-control) var(--vk-space-cluster);
  border-bottom: 1px solid var(--vk-divider-subtle);
}

.cover-resolved-prompt-head strong {
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.cover-resolved-prompt pre,
.cover-resolved-prompt p {
  max-height: 220px;
  margin: 0;
  padding: var(--vk-space-cluster);
  overflow: auto;
  color: var(--vk-muted);
  font-family: var(--vk-font-mono);
  font-size: var(--vk-type-meta-size);
  line-height: var(--vk-leading-reading);
  white-space: pre-wrap;
}

@media (max-width: 860px) {
  .cover-style-options {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .cover-style-options,
  .cover-plan-grid {
    grid-template-columns: 1fr;
  }

  .cover-plan-span {
    grid-column: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cover-style-planning-spinner {
    animation: none;
  }
}
</style>
