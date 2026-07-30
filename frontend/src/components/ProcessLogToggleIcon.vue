<template>
  <span class="process-log-toggle-icon" :class="{ 'is-collapsed': collapsed }" aria-hidden="true">
    <span class="process-log-toggle-icon-art" v-html="processLogSvg"></span>
  </span>
</template>

<script setup>
import processLogSvg from '../../assets/inset.filled.bottomhalf.rectangle.svg?raw'

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

.process-log-toggle-icon-art :deep(svg) {
  width: 19px;
  height: 19px;
  display: block;
  overflow: visible;
}

.process-log-toggle-icon-art :deep(path) {
  fill: currentColor !important;
}

/* The last path is the bottom-panel rectangle in the supplied SVG. */
.process-log-toggle-icon-art :deep(path:last-of-type) {
  transform-box: fill-box;
  transform-origin: center bottom;
  transition: transform var(--vk-motion-panel) var(--vk-ease-out);
}

.process-log-toggle-icon.is-collapsed .process-log-toggle-icon-art :deep(path:last-of-type) {
  transform: scaleY(0.22);
}

@media (prefers-reduced-motion: reduce) {
  .process-log-toggle-icon-art :deep(path:last-of-type) {
    transition: none;
  }
}
</style>
