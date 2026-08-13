<template>
  <div
    class="ai-skeleton-stream"
    role="status"
    aria-live="polite"
    :aria-label="ariaLabel || label || '内容正在生成'"
  >
    <span v-if="label" class="ai-skeleton-stream-label">{{ label }}</span>
    <span class="ai-skeleton-stream-line wide"></span>
    <span class="ai-skeleton-stream-line"></span>
    <span class="ai-skeleton-stream-line medium"></span>
    <span class="ai-skeleton-stream-line short"></span>
  </div>
</template>

<script setup>
defineProps({
  label: {
    type: String,
    default: '',
  },
  ariaLabel: {
    type: String,
    default: '',
  },
})
</script>

<style scoped>
.ai-skeleton-stream {
  display: grid;
  gap: 9px;
  width: var(--ai-skeleton-stream-width, min(100%, 420px));
  padding: var(--ai-skeleton-stream-padding, 12px 0 6px);
}

.ai-skeleton-stream-label {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-weight: var(--vk-weight-medium);
  line-height: 1.35;
}

.ai-skeleton-stream-line {
  position: relative;
  width: 78%;
  height: 10px;
  overflow: hidden;
  border-radius: 3px;
  background: var(--vk-ai-stream-track);
}

.ai-skeleton-stream-line::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    var(--vk-ai-stream-highlight) 48%,
    transparent 100%
  );
  transform: translateX(-110%);
  animation: ai-skeleton-stream-shimmer 1.2s linear infinite;
  will-change: transform;
}

.ai-skeleton-stream-line.wide { width: 96%; }
.ai-skeleton-stream-line.medium { width: 61%; }
.ai-skeleton-stream-line.short { width: 38%; }

@keyframes ai-skeleton-stream-shimmer {
  to { transform: translateX(110%); }
}

@media (prefers-reduced-motion: reduce) {
  .ai-skeleton-stream-line::after {
    transform: none;
    animation: none;
    opacity: 0.72;
  }
}
</style>
