<template>
  <el-dialog
    :model-value="Boolean(destructiveConfirmation)"
    class="apple-delete-confirm-dialog"
    width="min(360px, calc(100vw - 32px))"
    :show-close="false"
    :close-on-click-modal="false"
    :aria-label="destructiveConfirmation?.title || '确认操作'"
    align-center
    @update:model-value="handleVisibility"
  >
    <section class="apple-delete-confirm-content" aria-live="polite">
      <div class="apple-delete-confirm-media" aria-hidden="true">
        <SvgMaskIcon :src="trashIcon" :size="24" />
      </div>
      <div class="apple-delete-confirm-copy">
        <h3>{{ destructiveConfirmation?.title }}</h3>
        <p v-if="destructiveConfirmation?.message">{{ destructiveConfirmation.message }}</p>
      </div>
    </section>
    <footer class="apple-delete-confirm-actions">
      <el-button @click="settleDestructiveConfirmation(false)">{{ destructiveConfirmation?.cancelLabel || '保留' }}</el-button>
      <el-button type="danger" class="apple-delete-confirm-destructive" @click="settleDestructiveConfirmation(true)">{{ destructiveConfirmation?.confirmLabel || '删除' }}</el-button>
    </footer>
  </el-dialog>
</template>

<script setup>
import { destructiveConfirmation, settleDestructiveConfirmation } from '../composables/useDestructiveConfirm'
import SvgMaskIcon from './SvgMaskIcon.vue'
const trashIcon = 'trash'

function handleVisibility(visible) {
  if (!visible) settleDestructiveConfirmation(false)
}
</script>

<style>
.el-dialog.apple-delete-confirm-dialog {
  --vk-confirm-surface: var(--vk-bg-panel);
  --vk-confirm-text: var(--vk-text);
  --vk-confirm-muted: var(--vk-muted);
  --vk-confirm-line: var(--vk-border);
  --vk-confirm-border: var(--vk-border);
  --vk-confirm-danger-fg: var(--vk-danger);
  --vk-confirm-danger-bg: var(--vk-danger-surface);
  --vk-confirm-danger-bg-hover: color-mix(in srgb, var(--vk-danger) 18%, var(--vk-bg-panel));
  border: 1px solid var(--vk-confirm-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-confirm-surface);
  box-shadow: var(--vk-shadow-dialog);
  overflow: hidden;
}

.el-overlay:has(.apple-delete-confirm-dialog) { background: var(--vk-overlay-backdrop) !important; }

.apple-delete-confirm-dialog .el-dialog__header,
.apple-delete-confirm-dialog .el-dialog__footer { display: none; }

.apple-delete-confirm-dialog .el-dialog__body { padding: 0; }

.apple-delete-confirm-content {
  display: grid;
  justify-items: center;
  gap: var(--vk-space-cluster);
  padding: 28px 24px 22px;
  text-align: center;
}

.apple-delete-confirm-media {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: var(--vk-radius-input);
  background: var(--vk-confirm-danger-bg);
  color: var(--vk-confirm-danger-fg);
}

.apple-delete-confirm-copy { display: grid; max-width: 348px; min-width: 0; gap: var(--vk-space-sm); }

.apple-delete-confirm-copy h3 {
  margin: 0;
  color: var(--vk-confirm-text);
  font-size: var(--vk-type-heading-size);
  font-weight: var(--vk-weight-strong);
  letter-spacing: var(--vk-tracking-display);
}

.apple-delete-confirm-copy p {
  margin: 0;
  color: var(--vk-confirm-muted);
  font-size: var(--vk-type-body-size);
  line-height: var(--vk-leading-body);
}

.apple-delete-confirm-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--vk-space-cluster);
  padding: 14px var(--vk-space-panel) var(--vk-space-panel);
  border-top: 1px solid var(--vk-confirm-line);
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button {
  min-height: 34px;
  border-radius: var(--vk-radius-control);
  border-color: var(--vk-confirm-line);
  background: var(--vk-confirm-surface);
  color: var(--vk-confirm-text);
  box-shadow: none;
  font-weight: var(--vk-weight-medium);
  transition: background-color var(--vk-motion-fast) var(--vk-ease-out), border-color var(--vk-motion-fast) var(--vk-ease-out), transform 80ms var(--vk-ease-out);
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button:not(.apple-delete-confirm-destructive):hover {
  border-color: var(--vk-confirm-line);
  background: var(--vk-bg-hover);
  color: var(--vk-confirm-text);
  box-shadow: none;
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button:not(.apple-delete-confirm-destructive):active:not(:disabled) {
  border-color: var(--vk-confirm-line);
  background: color-mix(in srgb, var(--vk-bg-hover) 76%, var(--vk-bg-center));
  box-shadow: none;
  transform: translateY(1px);
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button.apple-delete-confirm-destructive {
  color: var(--vk-confirm-danger-fg);
  border-color: transparent;
  background: var(--vk-confirm-danger-bg);
  box-shadow: none;
}

@media (max-width: 480px) {
  .apple-delete-confirm-content { gap: var(--vk-space-control); padding: 26px var(--vk-space-panel) var(--vk-space-panel); }
  .apple-delete-confirm-media { width: 40px; height: 40px; }
  .apple-delete-confirm-actions { gap: var(--vk-space-control); padding: var(--vk-space-panel); }
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button.apple-delete-confirm-destructive:hover,
.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button.apple-delete-confirm-destructive:focus-visible {
  border-color: transparent;
  background: var(--vk-confirm-danger-bg-hover);
  box-shadow: none;
}

.el-dialog.apple-delete-confirm-dialog .apple-delete-confirm-actions .el-button.apple-delete-confirm-destructive:active:not(:disabled) {
  border-color: transparent;
  background: color-mix(in srgb, var(--vk-confirm-danger-fg) 18%, var(--vk-confirm-danger-bg));
  box-shadow: none;
  transform: translateY(1px);
}

@media (prefers-reduced-motion: reduce) {
  .apple-delete-confirm-dialog,
  .apple-delete-confirm-dialog * { transition: none !important; }
}
</style>
