<template>
  <div class="batch-selection-toolbar">
    <div class="batch-selection-toolbar__summary">
      <el-checkbox
        :model-value="allSelected"
        :indeterminate="indeterminate"
        :aria-label="selectAllLabel"
        @update:model-value="emit('update:all-selected', $event)"
      />
      <strong>已选择 {{ selectedCount }} {{ selectionUnit }}</strong>
      <span>{{ summary }}</span>
    </div>
    <div class="batch-selection-toolbar__actions">
      <slot name="actions" />
      <el-button text size="small" :disabled="clearDisabled" @click="emit('clear')">清除选择</el-button>
      <el-button size="small" :disabled="disabled" @click="emit('exit')">退出批量</el-button>
    </div>
  </div>
</template>

<script setup>
import { ElCheckbox } from 'element-plus'

defineProps({
  allSelected: { type: Boolean, default: false },
  indeterminate: { type: Boolean, default: false },
  selectedCount: { type: Number, default: 0 },
  selectionUnit: { type: String, default: '项' },
  summary: { type: String, default: '' },
  selectAllLabel: { type: String, required: true },
  disabled: { type: Boolean, default: false },
  clearDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:all-selected', 'clear', 'exit'])
</script>

<style scoped>
.batch-selection-toolbar,
.batch-selection-toolbar__summary,
.batch-selection-toolbar__actions {
  display: flex;
  align-items: center;
}

.batch-selection-toolbar {
  justify-content: space-between;
  width: 100%;
  min-height: 42px;
  gap: var(--vk-space-cluster);
  padding: var(--vk-space-xs) var(--vk-space-control) var(--vk-space-xs) var(--vk-space-cluster);
  border: 1px solid color-mix(in srgb, var(--vk-accent) 28%, var(--vk-border));
  border-radius: var(--vk-radius-input);
  background: color-mix(in srgb, var(--vk-accent) 5%, var(--vk-bg-panel));
}

.batch-selection-toolbar__summary { min-width: 0; gap: var(--vk-space-control); }
.batch-selection-toolbar__summary strong { color: var(--vk-text); font-size: var(--vk-type-label-size); white-space: nowrap; }
.batch-selection-toolbar__summary span { overflow: hidden; color: var(--vk-muted); font-size: var(--vk-type-meta-size); text-overflow: ellipsis; white-space: nowrap; }
.batch-selection-toolbar__summary :deep(.el-checkbox) { margin: 0; }
.batch-selection-toolbar__actions { flex: 0 0 auto; gap: var(--vk-space-sm); }

@media (max-width: 980px) {
  .batch-selection-toolbar { align-items: flex-start; flex-direction: column; }
  .batch-selection-toolbar__actions { width: 100%; flex-wrap: wrap; }
}
</style>
