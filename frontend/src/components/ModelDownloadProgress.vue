<template>
  <div class="model-download-progress">
    <el-progress
      :percentage="percentage"
      :indeterminate="!determinate"
      :duration="1.6"
      :stroke-width="5"
      :show-text="false"
      :aria-label="`${model.model} 下载进度`"
    />
    <small>{{ statusText }}</small>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  model: { type: Object, required: true },
  statusText: { type: String, required: true },
})

const total = computed(() => Number(props.model?.job?.total_bytes || 0))
const determinate = computed(() => total.value > 0)
const percentage = computed(() => {
  const downloaded = Number(props.model?.job?.downloaded_bytes || 0)
  if (!(downloaded >= 0 && total.value > 0)) return 0
  return Math.min(99, Math.max(0, Math.floor(downloaded / total.value * 100)))
})
</script>

<style scoped>
.model-download-progress { display: grid; gap: 5px; max-width: 520px; margin-top: 9px; }
.model-download-progress small { color: var(--vk-muted); font-size: var(--vk-type-meta-size); line-height: var(--vk-leading-label); }
.model-download-progress :deep(.el-progress-bar__outer) { background: var(--vk-fill-secondary); }
</style>
