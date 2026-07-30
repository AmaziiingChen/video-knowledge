<template>
  <span
    class="svg-mask-icon"
    :style="iconStyle"
    aria-hidden="true"
  ></span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  size: {
    type: Number,
    default: 18
  }
})

const iconStyle = computed(() => ({
  '--icon-size': `${props.size}px`,
  '--icon-source': `url("${props.src}")`
}))
</script>

<style scoped>
.svg-mask-icon {
  width: var(--icon-size);
  height: var(--icon-size);
  display: block;
  flex: 0 0 auto;
  background-color: currentColor;
  -webkit-mask: var(--icon-source) center / contain no-repeat;
  mask: var(--icon-source) center / contain no-repeat;
  opacity: 0.78;
  transition:
    opacity 0.16s ease,
    transform 0.12s ease;
}

@media (prefers-reduced-motion: reduce) {
  .svg-mask-icon {
    transition: opacity var(--vk-motion-fast) ease;
  }
}
</style>
