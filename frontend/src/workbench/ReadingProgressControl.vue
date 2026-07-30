<template>
  <span class="reading-progress-control-anchor">
    <el-popover
      placement="bottom-end"
      :width="214"
      trigger="hover"
      :show-after="90"
      :hide-after="160"
      :show-arrow="false"
      transition="reading-progress-pop"
      popper-class="content-action-popover reading-progress-popover"
    >
      <template #reference>
        <button
          class="reading-progress-control"
          type="button"
          :aria-label="`阅读进度 ${progress}%`"
          :title="`阅读进度 ${progress}%`"
        >
          <svg class="reading-progress-ring" viewBox="0 0 20 20" aria-hidden="true">
            <circle class="reading-progress-track" cx="10" cy="10" r="7" />
            <circle
              class="reading-progress-value"
              cx="10"
              cy="10"
              r="7"
              :style="{ strokeDashoffset: ringOffset }"
            />
          </svg>
          <span>{{ progress }}%</span>
        </button>
      </template>

      <div class="reading-progress-card">
        <div class="reading-progress-card-head">
          <span>阅读进度</span>
          <strong>{{ progress }}%</strong>
        </div>
        <div class="reading-progress-bar" aria-hidden="true">
          <span :style="{ width: `${progress}%` }"></span>
        </div>
        <div class="reading-progress-stats">
          <div>
            <span>总字符数</span>
            <strong>{{ characterCountLabel }}</strong>
          </div>
          <div>
            <span>预计还需</span>
            <strong>{{ remainingTimeLabel }}</strong>
          </div>
        </div>
      </div>
    </el-popover>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  characterCount: { type: Number, default: 0 },
  remainingMinutes: { type: Number, default: 0 },
})

const normalizedProgress = computed(() => Math.min(100, Math.max(0, Math.round(Number(props.progress) || 0))))
const ringOffset = computed(() => `${44 * (1 - normalizedProgress.value / 100)}`)
const characterCountLabel = computed(() => {
  const count = Math.max(0, Math.round(Number(props.characterCount) || 0))
  return count ? `${count.toLocaleString('zh-CN')} 字` : '—'
})
const remainingTimeLabel = computed(() => {
  if (normalizedProgress.value >= 100) return '已读完'
  const minutes = Math.max(0, Math.round(Number(props.remainingMinutes) || 0))
  return minutes ? `约 ${minutes} 分钟` : '—'
})
</script>

<style scoped>
.reading-progress-control-anchor {
  display: inline-flex;
  flex: 0 0 auto;
}

.reading-progress-control {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 9px 0 7px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 76%, transparent);
  color: var(--vk-muted);
  font: inherit;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  cursor: default;
  transition:
    transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color var(--vk-motion-standard) ease,
    color var(--vk-motion-standard) ease,
    box-shadow var(--vk-motion-standard) ease;
}

.reading-progress-control > span {
  display: inline-block;
  width: 4ch;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}

.reading-progress-control:hover,
.reading-progress-control:focus-visible {
  outline: 0;
  background: var(--vk-bg-panel);
  color: var(--vk-accent-strong);
  transform: scale(1.02);
  box-shadow:
    0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent),
    0 2px 4px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.reading-progress-ring {
  width: 16px;
  height: 16px;
  overflow: visible;
  transform: rotate(-90deg);
}

.reading-progress-track,
.reading-progress-value {
  fill: none;
  stroke-width: 2.25;
}

.reading-progress-track { stroke: color-mix(in srgb, currentColor 22%, transparent); }

.reading-progress-value {
  stroke: currentColor;
  stroke-linecap: round;
  stroke-dasharray: 44;
  transition: stroke-dashoffset 160ms var(--vk-ease-out);
}

.reading-progress-card { padding: 3px 4px; }

.reading-progress-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 9px;
  color: var(--vk-muted);
  font-size: 12px;
}

.reading-progress-card-head strong {
  color: var(--vk-text);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.reading-progress-bar {
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-border) 72%, transparent);
}

.reading-progress-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--vk-accent);
  transition: width 160ms var(--vk-ease-out);
}

.reading-progress-stats {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.reading-progress-stats > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14px;
  color: var(--vk-muted);
  font-size: 12px;
}

.reading-progress-stats strong {
  color: var(--vk-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

:global(.reading-progress-pop-enter-active),
:global(.reading-progress-pop-leave-active) {
  transition: opacity 140ms var(--vk-ease-out), scale 140ms var(--vk-ease-out);
}

:global(.reading-progress-pop-enter-from),
:global(.reading-progress-pop-leave-to) {
  opacity: 0;
  scale: 0.97;
}

@media (prefers-reduced-motion: reduce) {
  .reading-progress-control,
  .reading-progress-value,
  .reading-progress-bar span,
  :global(.reading-progress-pop-enter-active),
  :global(.reading-progress-pop-leave-active) { transition: none; }

  .reading-progress-control:hover,
  .reading-progress-control:focus-visible { transform: none; }
}
</style>
