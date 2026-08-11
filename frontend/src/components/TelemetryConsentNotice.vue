<template>
  <aside class="telemetry-consent-notice" aria-label="隐私与诊断说明" role="status">
    <div class="telemetry-consent-copy">
      <strong>帮助改进 KnowledgeHub</strong>
      <p>如你允许，我们会发送匿名的启动、功能结果和错误类别，用于修复问题。不会发送资料内容、搜索词、链接、路径、账号或密钥。</p>
    </div>
    <div class="telemetry-consent-actions">
      <button class="telemetry-consent-allow" type="button" :disabled="saving" @click="$emit('allow')">允许匿名诊断数据</button>
      <button type="button" :disabled="saving" @click="$emit('dismiss')">暂不发送</button>
      <button type="button" :disabled="saving" @click="$emit('open-privacy')">查看说明</button>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  saving: { type: Boolean, default: false },
})

defineEmits(['allow', 'dismiss', 'open-privacy'])
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

.telemetry-consent-actions .telemetry-consent-allow { background: var(--vk-action-bg); color: var(--vk-action-fg); }
.telemetry-consent-actions .telemetry-consent-allow:hover,
.telemetry-consent-actions .telemetry-consent-allow:focus-visible { background: var(--vk-action-bg); color: var(--vk-action-fg); }

@media (max-width: 820px) {
  .telemetry-consent-notice { align-items: flex-start; flex-direction: column; }
  .telemetry-consent-copy { align-items: flex-start; flex-direction: column; gap: var(--vk-space-micro); }
  .telemetry-consent-actions { align-self: flex-end; }
}
</style>
