<template>
  <section class="sidebar-section sidebar-link-dock">
    <div class="sidebar-process-input">
      <el-input
        :model-value="shareText"
        type="textarea"
        name="source-link"
        autocomplete="off"
        aria-label="粘贴待处理链接"
        :autosize="{ minRows: 1, maxRows: 6 }"
        resize="none"
        placeholder="粘贴链接…"
        @update:model-value="$emit('update:shareText', $event)"
        @input="$emit('input-change')"
        @keydown.enter.exact.prevent="$emit('run')"
      />
      <el-button
        class="sidebar-run-button"
        :loading="running && !taskId"
        :disabled="!shareText.trim() || running"
        aria-label="开始处理"
        @click="$emit('run')"
      >
        <SvgMaskIcon src="arrow.up.circle.fill" :size="19" />
      </el-button>
    </div>
  </section>
</template>

<script setup>
import SvgMaskIcon from '../components/SvgMaskIcon.vue'

defineProps({
  shareText: { type: String, default: '' },
  running: { type: Boolean, default: false },
  taskId: { type: [String, Number], default: '' },
})

defineEmits(['update:shareText', 'input-change', 'run'])
</script>

<style scoped>
.sidebar-link-dock {
  padding: 8px 2px 0;
  border-top: 1px solid var(--vk-border);
}

.sidebar-process-input {
  min-width: 0;
  display: grid;
  gap: 4px;
  padding: 8px 8px 7px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 80%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--vk-bg-panel) 84%, transparent);
  box-shadow: 0 5px 14px color-mix(in srgb, var(--vk-text) 3%, transparent);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background-color 0.16s ease;
}

.sidebar-process-input :deep(.el-textarea__inner) {
  min-height: 0 !important;
  max-height: 132px;
  padding: 0 2px;
  overflow-y: auto;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--vk-text);
  line-height: 1.45;
  box-shadow: none;
}

.sidebar-process-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.sidebar-run-button {
  width: 28px;
  height: 28px;
  min-height: 28px;
  justify-self: end;
  padding: 0;
  border: 0;
  background: transparent !important;
  color: var(--vk-accent-strong) !important;
  box-shadow: none !important;
}

.sidebar-run-button:hover:not(:disabled),
.sidebar-run-button:focus-visible {
  background: transparent !important;
  color: var(--vk-accent-strong) !important;
  box-shadow: none !important;
}

.sidebar-run-button:disabled {
  background: transparent !important;
  color: var(--vk-muted) !important;
  opacity: 0.42;
}
</style>
