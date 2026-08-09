<template>
  <el-popover
    v-model:visible="open"
    placement="bottom-end"
    :width="320"
    trigger="hover"
    :show-after="90"
    :hide-after="180"
    :show-arrow="false"
    transition="content-action-pop"
    popper-class="content-action-popover"
  >
    <template #reference>
      <slot name="reference" />
    </template>

    <div class="content-action-menu">
      <div class="content-action-menu-heading">内容操作</div>
      <button
        v-for="action in model.actions"
        :key="action.id"
        type="button"
        :class="{ 'is-danger': action.danger }"
        :disabled="action.disabled"
        @click="select(action.id)"
      >{{ action.label }}</button>

      <div v-if="model.details.length" class="content-action-menu-details">
        <div
          v-for="detail in model.details"
          :key="detail.label"
          :class="{ 'is-url': detail.kind === 'url', 'is-path': detail.kind === 'path' }"
        >
          <span>{{ detail.label }}</span>
          <button
            v-if="detail.kind === 'path'"
            class="content-detail-path"
            type="button"
            :title="detail.title || detail.value"
            @click="select('reveal-detail-path', detail.value, false)"
          >{{ detail.value }}</button>
          <button
            v-else-if="detail.kind === 'url'"
            class="content-detail-path content-detail-url"
            type="button"
            :title="detail.title || detail.value"
            @click="select('open-detail-url', detail.value, false)"
          >{{ detail.value }}</button>
          <strong v-else :title="detail.title || detail.value">{{ detail.value }}</strong>
        </div>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  model: {
    type: Object,
    default: () => ({ actions: [], details: [] }),
  },
})

const emit = defineEmits(['select'])
const open = ref(false)

function select(id, payload = null, close = true) {
  emit('select', { id, payload })
  if (close) open.value = false
}
</script>

<style scoped>
:global(.content-action-popover) {
  z-index: 3000 !important;
  padding: 7px !important;
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, var(--vk-bg-panel)) !important;
  border-radius: var(--vk-radius-surface) !important;
  background:
    linear-gradient(
      145deg,
      color-mix(in srgb, var(--vk-bg-panel) 88%, var(--vk-bg-center)) 0%,
      color-mix(in srgb, var(--vk-bg-panel) 94%, transparent) 100%
    ) !important;
  box-shadow:
    0 18px 40px color-mix(in srgb, var(--vk-text) 18%, transparent),
    0 3px 9px color-mix(in srgb, var(--vk-text) 8%, transparent),
    inset 0 1px 0 color-mix(in srgb, var(--vk-bg-panel) 68%, transparent) !important;
  backdrop-filter: blur(28px) saturate(150%) brightness(1.04);
  -webkit-backdrop-filter: blur(28px) saturate(150%) brightness(1.04);
  transform-origin: right top;
}

:global(.content-action-pop-enter-active) {
  transition: opacity 150ms var(--vk-ease-out), scale 150ms var(--vk-ease-out);
}

:global(.content-action-pop-leave-active) {
  transition: opacity 100ms var(--vk-ease-out), scale 100ms var(--vk-ease-out);
}

:global(.content-action-pop-enter-from) {
  opacity: 0;
  scale: 0.96;
}

:global(.content-action-pop-leave-to) {
  opacity: 0;
  scale: 0.98;
}

:global(.content-action-popover .el-popper__arrow::before) {
  background: color-mix(in srgb, var(--vk-bg-panel) 74%, transparent) !important;
}

.content-action-menu-heading {
  padding: 3px 7px 5px;
  color: var(--vk-muted);
  font-size: 11px;
}

.content-action-menu > button {
  width: 100%;
  padding: 7px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.content-action-menu > button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--vk-accent) 10%, transparent);
  color: var(--vk-accent-strong);
}

.content-action-menu > button.is-danger {
  margin-top: 5px;
  color: var(--vk-danger);
}

.content-action-menu > button.is-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--vk-danger) 10%, transparent);
  color: var(--vk-danger);
}

.content-action-menu > button:disabled {
  color: var(--vk-muted);
  cursor: default;
}

.content-action-menu-details {
  display: grid;
  gap: 5px;
  margin-top: 6px;
  padding: 9px 7px 3px;
  border-top: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
}

.content-action-menu-details > div {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  font-size: 11px;
}

.content-action-menu-details span {
  color: var(--vk-muted);
  line-height: 1.45;
}

.content-action-menu-details strong {
  color: var(--vk-text);
  font-weight: 500;
  text-align: right;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.content-action-menu-details > div.is-url,
.content-action-menu-details > div.is-path {
  margin-top: 2px;
}

.content-action-menu-details > div.is-url strong,
.content-action-menu-details > div.is-path .content-detail-path {
  color: var(--vk-muted);
  font-size: 10px;
}

.content-detail-path {
  min-width: 0;
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
  font: inherit;
  line-height: 1.45;
  text-align: right;
  text-decoration: underline;
  text-decoration-color: transparent;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content-detail-path:hover {
  color: var(--vk-text);
  text-decoration-color: currentColor;
}

@media (prefers-reduced-motion: reduce) {
  :global(.content-action-pop-enter-active),
  :global(.content-action-pop-leave-active) {
    transition: opacity var(--vk-motion-fast) ease;
  }

  :global(.content-action-pop-enter-from),
  :global(.content-action-pop-leave-to) {
    scale: 1;
  }
}

@media (prefers-reduced-transparency: reduce) {
  :global(.content-action-popover) {
    background: var(--vk-bg-panel) !important;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
  :global(.content-action-popover) {
    border-color: color-mix(in srgb, var(--vk-text) 48%, var(--vk-border)) !important;
    background: var(--vk-bg-panel) !important;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
