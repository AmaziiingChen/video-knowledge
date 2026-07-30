<template>
  <el-dialog
    :model-value="state.visible"
    class="report-generation-dialog"
    width="min(540px, calc(100vw - 32px))"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="state.phase !== 'submitting'"
    align-center
    append-to-body
    @update:model-value="handleVisibility"
  >
    <template #header>
      <header class="report-generation-heading">
        <div>
          <h2>生成{{ state.reportLabel || '报告' }}</h2>
          <p>{{ state.groupName || '报告分组' }}</p>
        </div>
        <span class="report-generation-stage" :class="`is-${state.phase || 'checking'}`">
          {{ stageLabel }}
        </span>
      </header>
    </template>

    <section
      v-if="state.phase === 'checking' || state.phase === 'submitting'"
      class="report-generation-waiting"
      role="status"
      aria-live="polite"
    >
      <span class="report-generation-spinner" aria-hidden="true"></span>
      <div>
        <strong>{{ state.phase === 'checking' ? '正在核对生成范围' : '正在创建生成任务' }}</strong>
        <p>{{ state.phase === 'checking' ? '仅核对时间范围与来源数量；正文和摘要缓存将在任务启动后逐步处理。' : '收到第一条处理进度后，将自动切换到处理日志。' }}</p>
      </div>
    </section>

    <template v-else>
      <section class="report-generation-summary" aria-label="本次生成概况">
        <div class="report-generation-window">
          <span>时间范围</span>
          <strong>{{ dateRange }}</strong>
        </div>
        <div class="report-generation-metric">
          <span>素材</span>
          <strong>{{ formatReportCount(state.preflight?.source_count) }} 篇</strong>
          <small>正文将在任务启动后读取</small>
        </div>
        <div class="report-generation-metric">
          <span>摘要缓存</span>
          <strong>任务启动后核对</strong>
          <small>不在生成前读取全文</small>
        </div>
      </section>

      <section class="report-generation-pipeline" aria-labelledby="report-generation-pipeline-title">
        <header>
          <strong id="report-generation-pipeline-title">预计处理步骤</strong>
          <span>分栏数量由规划模型按素材决定</span>
        </header>
        <ol>
          <li v-for="(step, index) in callPlan" :key="step.label">
            <span>{{ index + 1 }}</span>
            <div>
              <strong>{{ step.label }}</strong>
              <small>{{ step.detail }}</small>
            </div>
          </li>
        </ol>
      </section>
    </template>

    <template #footer>
      <div class="report-generation-actions">
        <el-button :disabled="state.phase === 'submitting'" @click="emit('cancel')">取消</el-button>
        <el-button
          type="primary"
          :loading="state.phase !== 'ready'"
          :disabled="state.phase !== 'ready'"
          @click="emit('confirm')"
        >
          {{ state.phase === 'checking' ? '正在检查' : state.phase === 'submitting' ? '正在启动' : '开始生成' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import {
  formatReportCount,
  formatReportDateRange,
  reportCallPlan,
} from './reportGenerationPresentation.js'

const props = defineProps({
  state: {
    type: Object,
    default: () => ({
      visible: false,
      phase: 'checking',
      reportLabel: '报告',
      groupName: '',
      preflight: null,
    }),
  },
})

const emit = defineEmits(['cancel', 'confirm'])

const stageLabel = computed(() => ({
  checking: '生成前检查',
  ready: '等待确认',
  submitting: '正在启动',
})[props.state.phase] || '生成前检查')

const dateRange = computed(() => formatReportDateRange(
  props.state.preflight?.window_start,
  props.state.preflight?.window_end,
))
const callPlan = computed(() => reportCallPlan(props.state.preflight))

function handleVisibility(visible) {
  if (!visible && props.state.phase !== 'submitting') emit('cancel')
}
</script>

<style scoped>
:global(.report-generation-dialog) {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 82%, transparent);
  border-radius: var(--vk-radius-feature);
  background: color-mix(in srgb, var(--vk-bg-panel) 96%, transparent);
  box-shadow: 0 18px 48px color-mix(in srgb, var(--vk-text) 14%, transparent);
  backdrop-filter: blur(22px) saturate(145%);
}

:global(.report-generation-dialog .el-dialog__header) {
  margin: 0;
  padding: 20px var(--vk-space-section) 0;
}

:global(.report-generation-dialog .el-dialog__body) {
  padding: var(--vk-space-panel) var(--vk-space-section) 0;
}

:global(.report-generation-dialog .el-dialog__footer) {
  padding: 18px var(--vk-space-section) 20px;
}

.report-generation-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--vk-space-panel);
}

.report-generation-heading h2 {
  margin: 0;
  color: var(--vk-text);
  font-size: var(--vk-type-heading-size);
  font-weight: var(--vk-weight-display);
  letter-spacing: var(--vk-tracking-display);
  line-height: var(--vk-leading-display);
}

.report-generation-heading p {
  margin: var(--vk-space-xs) 0 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.report-generation-stage {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: var(--vk-radius-pill);
  background: var(--vk-bg-quiet);
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-weight: var(--vk-weight-medium);
}

.report-generation-stage.is-ready {
  background: color-mix(in srgb, var(--vk-accent) 12%, var(--vk-bg-panel));
  color: var(--vk-accent-strong);
}

.report-generation-waiting {
  display: flex;
  align-items: center;
  gap: var(--vk-space-panel);
  min-height: 112px;
  padding: var(--vk-space-panel);
  border: 1px solid color-mix(in srgb, var(--vk-border) 70%, transparent);
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-bg-quiet) 64%, var(--vk-bg-panel));
}

.report-generation-waiting strong {
  display: block;
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-strong);
}

.report-generation-waiting p {
  margin: var(--vk-space-xs) 0 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  line-height: var(--vk-leading-body);
}

.report-generation-spinner {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border: 2px solid color-mix(in srgb, var(--vk-accent) 20%, var(--vk-border));
  border-top-color: var(--vk-accent-strong);
  border-radius: 50%;
  animation: report-generation-spin 800ms linear infinite;
}

.report-generation-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-bg-quiet) 48%, var(--vk-bg-panel));
}

.report-generation-window {
  grid-column: 1 / -1;
  padding: var(--vk-space-cluster) var(--vk-space-panel);
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 66%, transparent);
}

.report-generation-window span,
.report-generation-metric > span {
  display: block;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  letter-spacing: var(--vk-tracking-meta);
}

.report-generation-window strong {
  display: block;
  margin-top: 3px;
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
  font-variant-numeric: tabular-nums;
}

.report-generation-metric {
  padding: var(--vk-space-cluster) var(--vk-space-panel);
}

.report-generation-metric + .report-generation-metric {
  border-left: 1px solid color-mix(in srgb, var(--vk-border) 66%, transparent);
}

.report-generation-metric strong {
  display: block;
  margin-top: 3px;
  color: var(--vk-text);
  font-size: var(--vk-type-reading-size);
  font-weight: var(--vk-weight-strong);
  font-variant-numeric: tabular-nums;
}

.report-generation-metric small {
  display: block;
  margin-top: 1px;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
}

.report-generation-pipeline {
  margin-top: var(--vk-space-panel);
}

.report-generation-pipeline > header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--vk-space-cluster);
  margin-bottom: var(--vk-space-control);
}

.report-generation-pipeline > header strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-strong);
}

.report-generation-pipeline > header span {
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
}

.report-generation-pipeline ol {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--vk-space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.report-generation-pipeline li {
  display: flex;
  align-items: center;
  gap: var(--vk-space-control);
  min-width: 0;
  padding: 9px 10px;
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-hover) 52%, transparent);
}

.report-generation-pipeline li > span {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  place-items: center;
  border-radius: 50%;
  background: var(--vk-bg-panel);
  color: var(--vk-accent-strong);
  font-size: var(--vk-type-micro-size);
  font-weight: var(--vk-weight-strong);
}

.report-generation-pipeline li div {
  display: grid;
  min-width: 0;
}

.report-generation-pipeline li strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.report-generation-pipeline li small {
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  line-height: var(--vk-leading-label);
}

.report-generation-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--vk-space-sm);
}

.report-generation-actions :deep(.el-button) {
  min-width: 84px;
  min-height: var(--vk-control-height-default);
  margin: 0;
  border-radius: var(--vk-radius-control);
}

.report-generation-actions :deep(.el-button--primary) {
  border-color: var(--vk-action-bg);
  background: var(--vk-action-bg);
  color: var(--vk-action-fg);
  box-shadow: none;
}

@keyframes report-generation-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 520px) {
  .report-generation-pipeline ol { grid-template-columns: 1fr; }
  .report-generation-pipeline > header { align-items: flex-start; flex-direction: column; gap: 2px; }
}

@media (prefers-reduced-motion: reduce) {
  .report-generation-dialog,
  .report-generation-dialog * {
    transition: none !important;
  }

  .report-generation-spinner {
    animation: none;
    border-color: color-mix(in srgb, var(--vk-accent) 38%, var(--vk-border));
    border-top-color: var(--vk-accent-strong);
    opacity: .82;
  }
}
</style>
