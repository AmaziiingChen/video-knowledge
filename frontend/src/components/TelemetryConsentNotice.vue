<template>
  <aside class="telemetry-consent-notice" aria-label="隐私与诊断说明" role="status" :aria-busy="saving">
    <div class="telemetry-consent-copy">
      <strong>去标识使用诊断已开启</strong>
      <p>KnowledgeHub 默认低频发送 17 个固定检查点到 Cloudflare，最多保留 3 个月。不会发送资料内容、搜索词、链接、路径、账号、密钥或错误原文，可随时关闭。</p>
    </div>
    <div class="telemetry-consent-actions">
      <button class="telemetry-consent-primary" type="button" :disabled="saving" @click="$emit('acknowledge')">知道了</button>
      <button type="button" :disabled="saving" @click="$emit('disable')">关闭并清除</button>
      <button type="button" :disabled="saving" @click="$emit('open-privacy')">查看说明</button>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  saving: { type: Boolean, default: false },
})

defineEmits(['acknowledge', 'disable', 'open-privacy'])
</script>

<style scoped>
.telemetry-consent-notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-cluster);
  min-height: 42px;
  padding: var(--vk-space-xs) var(--vk-space-panel);
  border-bottom: 1px solid var(--vk-border);
  background: color-mix(in srgb, var(--vk-bg-quiet) 90%, var(--vk-accent));
  color: var(--vk-text);
}

.telemetry-consent-copy {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--vk-space-control);
  font-size: var(--vk-type-label-size);
  line-height: 1.4;
}

.telemetry-consent-copy strong { flex: 0 0 auto; font-weight: var(--vk-weight-strong); }
.telemetry-consent-copy p { margin: 0; color: var(--vk-muted); }

.telemetry-consent-actions {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-xs);
}

.telemetry-consent-actions button {
  min-height: 28px;
  padding: 0 var(--vk-space-control);
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  cursor: pointer;
}

.telemetry-consent-actions button:hover,
.telemetry-consent-actions button:focus-visible { color: var(--vk-text); background: var(--vk-bg-hover); outline: none; }
.telemetry-consent-actions button:focus-visible { box-shadow: inset 0 0 0 1px var(--vk-accent-strong); }
.telemetry-consent-actions button:disabled { cursor: default; opacity: 0.48; }

.telemetry-consent-actions .telemetry-consent-primary { background: var(--vk-action-bg); color: var(--vk-action-fg); }
.telemetry-consent-actions .telemetry-consent-primary:hover,
.telemetry-consent-actions .telemetry-consent-primary:focus-visible { background: var(--vk-action-bg); color: var(--vk-action-fg); }

@media (max-width: 820px) {
  .telemetry-consent-notice { align-items: flex-start; flex-direction: column; }
  .telemetry-consent-copy { align-items: flex-start; flex-direction: column; gap: var(--vk-space-micro); }
  .telemetry-consent-actions { align-self: flex-end; }
}
</style>
