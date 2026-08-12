<template>
  <details v-if="reasoning" class="ai-reasoning" :open="expanded" @toggle="handleToggle">
    <summary>{{ pendingAnswer ? '正在思考' : '思考过程' }}</summary>
    <div class="ai-reasoning-body" v-html="renderMarkdown(reasoning)" />
  </details>
</template>

<script setup>
defineProps({
  reasoning: { type: String, default: '' },
  expanded: { type: Boolean, default: false },
  pendingAnswer: { type: Boolean, default: false },
  renderMarkdown: { type: Function, required: true },
})
const emit = defineEmits(['update:expanded'])
function handleToggle(event) {
  emit('update:expanded', Boolean(event.currentTarget?.open))
}
</script>

<style scoped>
.ai-reasoning { margin: 0 0 var(--vk-space-sm); color: var(--vk-muted); font-size: var(--vk-type-label-size); }
.ai-reasoning summary { width: fit-content; cursor: pointer; user-select: none; font-weight: var(--vk-weight-medium); }
.ai-reasoning-body { margin-top: var(--vk-space-xs); padding-left: var(--vk-space-sm); border-left: 1px solid var(--vk-divider-subtle); line-height: var(--vk-leading-reading); }
.ai-reasoning-body :deep(p:first-child) { margin-top: 0; }
.ai-reasoning-body :deep(p:last-child) { margin-bottom: 0; }
</style>
