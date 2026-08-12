<template>
  <span
    class="panel-toggle-icon"
    :class="[`is-${side}`, { 'is-collapsed': collapsed }]"
    aria-hidden="true"
  >
    <svg class="panel-toggle-icon-art" viewBox="0 0 20 20" fill="none">
      <rect x="1.5" y="2.5" width="17" height="15" rx="2" stroke="currentColor" stroke-width="1.5" />
      <path class="panel-toggle-icon-fill" :d="side === 'left' ? 'M3 4h6v12H3z' : 'M11 4h6v12h-6z'" fill="currentColor" />
    </svg>
  </span>
</template>

<script setup>
defineProps({
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

.panel-toggle-icon-art {
  overflow: visible;
}

.panel-toggle-icon-fill {
  transform-box: fill-box;
  transform-origin: left center;
  transition: transform var(--vk-motion-panel) var(--vk-ease-out);
}

.panel-toggle-icon.is-right .panel-toggle-icon-fill {
  transform-origin: right center;
}

.panel-toggle-icon.is-collapsed .panel-toggle-icon-fill {
  transform: scaleX(0.22);
}

@media (prefers-reduced-motion: reduce) {
  .panel-toggle-icon-fill {
    transition: none;
  }
}
</style>
