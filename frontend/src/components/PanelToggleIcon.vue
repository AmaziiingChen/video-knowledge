<template>
  <span
    class="panel-toggle-icon"
    :class="[`is-${side}`, { 'is-collapsed': collapsed }]"
    aria-hidden="true"
  >
    <span class="panel-toggle-icon-art" v-html="svgMarkup"></span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import leftPanelSvg from '../../assets/inset.filled.lefthalf.rectangle.svg?raw'
import rightPanelSvg from '../../assets/inset.filled.trailinghalf.rectangle.svg?raw'

const props = defineProps({
  side: {
    type: String,
    required: true,
    validator: (value) => value === 'left' || value === 'right'
  },
  collapsed: {
    type: Boolean,
    default: false
  }
})

const svgMarkup = computed(() => (props.side === 'left' ? leftPanelSvg : rightPanelSvg))
</script>

<style scoped>
.panel-toggle-icon,
.panel-toggle-icon-art {
  width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  color: currentColor;
}

.panel-toggle-icon-art :deep(svg) {
  width: 19px;
  height: 19px;
  display: block;
  overflow: visible;
}

.panel-toggle-icon-art :deep(path) {
  fill: currentColor !important;
}

/* The last path is the filled half-pane supplied by the native SVG. */
.panel-toggle-icon-art :deep(path:last-of-type) {
  transform-box: fill-box;
  transform-origin: left center;
  transition: transform var(--vk-motion-panel) var(--vk-ease-out);
}

.panel-toggle-icon.is-right .panel-toggle-icon-art :deep(path:last-of-type) {
  transform-origin: right center;
}

.panel-toggle-icon.is-collapsed .panel-toggle-icon-art :deep(path:last-of-type) {
  transform: scaleX(0.22);
}

@media (prefers-reduced-motion: reduce) {
  .panel-toggle-icon-art :deep(path:last-of-type) {
    transition: none;
  }
}
</style>
