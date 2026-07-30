<template>
  <div v-if="available" class="preview-find-anchor" :class="{ 'is-open': open }">
    <button
      type="button"
      class="preview-find-trigger"
      :class="{ 'is-active': open }"
      aria-label="在预览中查找"
      title="在预览中查找"
      :aria-expanded="open ? 'true' : 'false'"
      @click="$emit('open')"
    >
      <SvgMaskIcon class="preview-find-trigger-icon" :src="magnifyingglassIcon" :size="15" />
    </button>

    <Transition name="preview-find-expand">
    <form
      v-if="open"
      class="preview-find-bar"
      role="search"
      aria-label="在预览中查找"
      @submit.prevent="$emit('next')"
    >
      <el-icon class="preview-find-icon"><Search /></el-icon>
      <input
        ref="inputRef"
        :value="query"
        type="search"
        name="preview-find"
        autocomplete="off"
        spellcheck="false"
        placeholder="在预览中查找"
        aria-label="在预览中查找"
        @input="$emit('update:query', $event.target.value)"
        @keydown.enter.exact.prevent="$emit('next')"
        @keydown.shift.enter.prevent="$emit('previous')"
        @keydown.esc.prevent="$emit('close')"
      />
      <output class="preview-find-count" aria-live="polite" :aria-label="countLabel">{{ countLabel }}</output>
      <span class="preview-find-divider" aria-hidden="true"></span>
      <button type="button" aria-label="上一个匹配项" title="上一个匹配项" :disabled="!matchCount" @click="$emit('previous')">
        <el-icon><ArrowUp /></el-icon>
      </button>
      <button type="button" aria-label="下一个匹配项" title="下一个匹配项" :disabled="!matchCount" @click="$emit('next')">
        <el-icon><ArrowDown /></el-icon>
      </button>
      <button type="button" class="preview-find-close" aria-label="关闭查找" title="关闭查找" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </form>
    </Transition>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Close, Search } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import magnifyingglassIcon from '../../assets/magnifyingglass.svg'

const props = defineProps({
  available: { type: Boolean, default: false },
  open: { type: Boolean, default: false },
  query: { type: String, default: '' },
  matchCount: { type: Number, default: 0 },
  activeMatchIndex: { type: Number, default: -1 },
  truncated: { type: Boolean, default: false },
  focusRequest: { type: Number, default: 0 },
})

defineEmits(['update:query', 'previous', 'next', 'open', 'close'])

const inputRef = ref(null)
let focusTimer = null
const countLabel = computed(() => {
  if (!props.query.trim()) return '输入关键词'
  if (!props.matchCount) return '无结果'
  return `${Math.max(0, props.activeMatchIndex + 1)} / ${props.matchCount}${props.truncated ? '+' : ''}`
})

async function focusInput() {
  await nextTick()
  if (focusTimer !== null) window.clearTimeout(focusTimer)
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  focusTimer = window.setTimeout(() => {
    focusTimer = null
    inputRef.value?.focus({ preventScroll: true })
    inputRef.value?.select()
  }, reducedMotion ? 0 : 160)
}

watch(() => props.open, (open) => {
  if (open) {
    focusInput()
  } else if (focusTimer !== null) {
    window.clearTimeout(focusTimer)
    focusTimer = null
  }
})

watch(() => props.focusRequest, () => {
  if (props.open) focusInput()
})

onBeforeUnmount(() => {
  if (focusTimer !== null) window.clearTimeout(focusTimer)
})
</script>

<style scoped>
.preview-find-anchor {
  position: relative;
  flex: 0 0 28px;
  z-index: 8;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
}

.preview-find-trigger {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: inline-grid;
  width: 28px;
  height: 28px;
  padding: 0;
  place-items: center;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 76%, transparent);
  color: var(--vk-muted);
  cursor: pointer;
  transition:
    transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color var(--vk-motion-standard) ease,
    color var(--vk-motion-standard) ease,
    box-shadow var(--vk-motion-standard) ease,
    opacity 180ms ease;
}

.preview-find-trigger:hover,
.preview-find-trigger:focus-visible {
  outline: 0;
  background: var(--vk-bg-panel);
  color: var(--vk-accent-strong);
  transform: scale(1.02);
  box-shadow:
    0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent),
    0 2px 4px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.preview-find-trigger:focus-visible {
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--vk-accent) 22%, transparent),
    0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent),
    0 2px 4px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.preview-find-trigger:active { transform: scale(0.95); }

.preview-find-trigger.is-active {
  opacity: 0;
  pointer-events: none;
  transform: scale(0.9);
}

.preview-find-trigger-icon {
  font-size: 15px;
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), filter var(--vk-motion-standard) ease;
}

.preview-find-trigger:hover .preview-find-trigger-icon,
.preview-find-trigger:focus-visible .preview-find-trigger-icon {
  transform: scale(1.15);
  filter: drop-shadow(0 2px 4px color-mix(in srgb, var(--vk-accent-strong) 28%, transparent));
}

.preview-find-bar {
  position: absolute;
  top: 50%;
  right: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  width: min(336px, calc(100vw - 112px));
  min-height: 36px;
  padding: 3px 4px 3px 10px;
  border: 1px solid color-mix(in srgb, var(--vk-bg-panel) 62%, var(--vk-border));
  border-radius: var(--vk-radius-input);
  background: color-mix(in srgb, var(--vk-bg-panel) 78%, transparent);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 16%, transparent), 0 1px 2px color-mix(in srgb, var(--vk-text) 10%, transparent);
  backdrop-filter: blur(20px) saturate(160%);
  color: var(--vk-text);
  transform: translate3d(0, -50%, 0);
  transform-origin: right center;
  overflow: hidden;
}

.preview-find-icon {
  flex: 0 0 auto;
  margin-right: 7px;
  color: var(--vk-muted);
  font-size: 15px;
}

.preview-find-bar input {
  min-width: 0;
  flex: 1 1 auto;
  height: 28px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: 13px;
}

.preview-find-bar input::placeholder { color: var(--vk-muted); }

.preview-find-count {
  min-width: 44px;
  padding: 0 6px;
  color: var(--vk-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  text-align: center;
  white-space: nowrap;
}

.preview-find-divider {
  width: 1px;
  height: 16px;
  margin: 0 2px;
  background: color-mix(in srgb, var(--vk-border) 78%, transparent);
}

.preview-find-bar button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
  transition: background-color 120ms ease-out, color 120ms ease-out, transform 100ms ease-out;
}

.preview-find-bar button:hover:not(:disabled),
.preview-find-bar button:focus-visible {
  outline: 0;
  background: color-mix(in srgb, var(--vk-accent) 12%, transparent);
  color: var(--vk-accent-strong);
}

.preview-find-bar button:active:not(:disabled) { transform: scale(0.94); }
.preview-find-bar button:disabled { cursor: default; opacity: 0.4; }
.preview-find-close { margin-left: 1px; }

.preview-find-expand-enter-active,
.preview-find-expand-leave-active {
  transition:
    width 0.56s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.28s ease,
    transform 0.56s cubic-bezier(0.22, 1, 0.36, 1),
    filter 0.36s ease;
}

.preview-find-expand-enter-from,
.preview-find-expand-leave-to {
  width: 28px;
  opacity: 0;
  filter: blur(5px);
  transform: translate3d(0, -50%, 0) scale(0.97);
}

.preview-find-expand-enter-active .preview-find-icon,
.preview-find-expand-enter-active input,
.preview-find-expand-enter-active .preview-find-count,
.preview-find-expand-enter-active .preview-find-divider,
.preview-find-expand-enter-active button,
.preview-find-expand-leave-active .preview-find-icon,
.preview-find-expand-leave-active input,
.preview-find-expand-leave-active .preview-find-count,
.preview-find-expand-leave-active .preview-find-divider,
.preview-find-expand-leave-active button {
  transition: opacity 0.2s ease, transform 0.42s cubic-bezier(0.22, 1, 0.36, 1);
}

.preview-find-expand-enter-from .preview-find-icon,
.preview-find-expand-leave-to .preview-find-icon {
  opacity: 0;
  transform: translateX(6px) scale(0.92);
}

.preview-find-expand-enter-from input,
.preview-find-expand-enter-from .preview-find-count,
.preview-find-expand-enter-from .preview-find-divider,
.preview-find-expand-enter-from button,
.preview-find-expand-leave-to input,
.preview-find-expand-leave-to .preview-find-count,
.preview-find-expand-leave-to .preview-find-divider,
.preview-find-expand-leave-to button {
  opacity: 0;
  transform: translateX(10px);
}

@media (prefers-reduced-motion: reduce) {
  .preview-find-expand-enter-active,
  .preview-find-expand-leave-active,
  .preview-find-trigger,
  .preview-find-bar button { transition: opacity 120ms ease; }

  .preview-find-expand-enter-from,
  .preview-find-expand-leave-to,
  .preview-find-trigger:hover,
  .preview-find-trigger:focus-visible,
  .preview-find-bar button:active:not(:disabled) { transform: none; }

  .preview-find-expand-enter-from .preview-find-icon,
  .preview-find-expand-leave-to .preview-find-icon,
  .preview-find-expand-enter-from input,
  .preview-find-expand-enter-from .preview-find-count,
  .preview-find-expand-enter-from .preview-find-divider,
  .preview-find-expand-enter-from button,
  .preview-find-expand-leave-to input,
  .preview-find-expand-leave-to .preview-find-count,
  .preview-find-expand-leave-to .preview-find-divider,
  .preview-find-expand-leave-to button { transform: none; }
}

@media (prefers-reduced-transparency: reduce) {
  .preview-find-bar {
    background: var(--vk-bg-panel);
    backdrop-filter: none;
  }
}
</style>
