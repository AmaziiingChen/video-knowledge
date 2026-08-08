<template>
  <span class="process-log-toggle-icon" :class="{ 'is-collapsed': collapsed }" aria-hidden="true">
    <svg class="process-log-toggle-icon-art" viewBox="0 0 20 20" fill="none">
      <rect x="1.5" y="2.5" width="17" height="15" rx="2" stroke="currentColor" stroke-width="1.5" />
      <path class="process-log-toggle-icon-fill" d="M3 11h14v5H3z" fill="currentColor" />
    </svg>
  </span>
</template>

<script setup>
defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped>
.process-log-toggle-icon,
.process-log-toggle-icon-art {
  width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  color: currentColor;
}

.process-log-toggle-icon-art { overflow: visible; }

.process-log-toggle-icon-fill {
  transform-box: fill-box;
  transform-origin: center bottom;
  transition: transform var(--vk-motion-panel) var(--vk-ease-out);
}

.process-log-toggle-icon.is-collapsed .process-log-toggle-icon-fill {
  transform: scaleY(0.22);
}

@media (prefers-reduced-motion: reduce) {
  .process-log-toggle-icon-fill {
    transition: none;
  }
}
</style>
