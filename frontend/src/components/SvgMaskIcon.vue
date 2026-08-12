<template>
  <span
    class="svg-mask-icon"
    :data-icon="resolvedName"
    :style="iconStyle"
    aria-hidden="true"
  ></span>
</template>

<script setup>
import { computed } from 'vue'
import iconManifest from './macosSymbolManifest.json'
import { resolveMacosSymbolAssetUrl } from './macosSymbolAssets.js'

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

const fallbackName = 'text.document'
const resolvedName = computed(() => iconManifest[props.src] ? props.src : fallbackName)
const iconAsset = computed(() => iconManifest[resolvedName.value])
const iconUrl = computed(() => resolveMacosSymbolAssetUrl(iconAsset.value))
const iconStyle = computed(() => ({
  '--icon-size': `${props.size}px`,
  '--icon-render-size': iconAsset.value.kind === 'brand' ? 'contain' : '128%',
  '--icon-source': `url("${iconUrl.value}")`
}))
</script>

<style scoped>
.svg-mask-icon {
  width: var(--icon-size);
  height: var(--icon-size);
  display: block;
  flex: 0 0 auto;
  background-color: currentColor;
  -webkit-mask: var(--icon-source) center / var(--icon-render-size) no-repeat;
  mask: var(--icon-source) center / var(--icon-render-size) no-repeat;
  opacity: 1;
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
