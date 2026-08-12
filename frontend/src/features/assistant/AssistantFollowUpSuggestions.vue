<template>
  <section v-if="normalized.length" class="assistant-followups" aria-label="还有什么想问的">
    <span class="assistant-followups-label">还有什么想问的</span>
    <button
      v-for="question in normalized"
      :key="question"
      type="button"
      :disabled="disabled"
      @click="$emit('select', question)"
    >{{ question }}</button>
  </section>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({
  questions: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
defineEmits(['select'])
const normalized = computed(() => props.questions.filter((item) => typeof item === 'string' && item.trim()).slice(0, 3))
</script>

<style scoped>
.assistant-followups { display: grid; gap: var(--vk-space-xs); margin-bottom: var(--vk-space-sm); }
.assistant-followups-label { color: var(--vk-muted); font-size: var(--vk-type-meta-size); }
.assistant-followups button { width: 100%; padding: var(--vk-space-sm) var(--vk-space-control); border: 1px solid var(--vk-divider-subtle); border-radius: var(--vk-radius-control); background: var(--vk-bg-panel); color: var(--vk-text); font: inherit; font-size: var(--vk-type-label-size); line-height: var(--vk-leading-label); text-align: left; cursor: pointer; }
.assistant-followups button:hover:not(:disabled) { border-color: color-mix(in srgb, var(--vk-accent) 42%, var(--vk-border)); background: var(--vk-bg-hover); }
.assistant-followups button:disabled { opacity: .48; cursor: not-allowed; }
</style>
