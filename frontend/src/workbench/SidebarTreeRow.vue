<template>
  <div
    class="sidebar-tree-row"
    :class="[
      `tone-${tone}`,
      {
        active,
        selected,
        editing,
        folder: kind === 'folder',
        open,
        'has-actions': Boolean($slots.actions),
        'has-check': Boolean(checkState),
        'has-meta': meta !== null && meta !== undefined && meta !== '',
        'has-status': Boolean(status),
        'has-unread': unread,
        'has-new-descendants': hasNewDescendants,
        'has-unread-count': hasNewDescendants && unreadCount > 0,
        'high-contrast-unread-count': highContrastUnreadCount,
        'drop-inside': dropPosition === 'inside',
        'drop-before': dropPosition === 'before',
        'drop-after': dropPosition === 'after',
      },
    ]"
    :style="rowStyle"
    :draggable="draggable"
  >
    <div
      v-if="kind === 'separator'"
      class="sidebar-tree-separator"
      :class="{ 'is-labeled': Boolean(label), interactive }"
      role="separator"
      :aria-label="label || undefined"
      :aria-hidden="label ? undefined : 'true'"
    >
      <span v-if="label">{{ label }}</span>
    </div>

    <slot v-else-if="editing" name="editing" />

    <template v-else>
      <button
        v-if="checkState"
        class="sidebar-tree-row-check"
        :class="`is-${checkState}`"
        type="button"
        role="checkbox"
        :aria-checked="checkState === 'checked' ? 'true' : checkState === 'indeterminate' ? 'mixed' : 'false'"
        :aria-label="checkLabel || undefined"
        @click.stop="emit('toggle-check', $event)"
      >
        <el-icon v-if="checkState === 'checked'" aria-hidden="true"><Check /></el-icon>
        <el-icon v-else-if="checkState === 'indeterminate'" aria-hidden="true"><Minus /></el-icon>
      </button>
      <button
        class="sidebar-tree-row-main"
        type="button"
        :aria-expanded="kind === 'folder' ? String(open) : undefined"
        :aria-label="ariaLabel || undefined"
        @click="emit('activate', $event)"
      >
        <el-icon v-if="kind === 'folder'" class="sidebar-tree-row-disclosure" aria-hidden="true">
          <ArrowRight />
        </el-icon>
        <SvgMaskIcon v-else-if="icon" class="sidebar-tree-row-icon" :src="icon" :size="16" />
        <slot v-else name="leading" />
        <span class="sidebar-tree-row-label" :title="labelTitle || label">{{ label }}</span>
        <small v-if="meta !== null && meta !== undefined && meta !== ''" class="sidebar-tree-row-meta">{{ meta }}</small>
      </button>
      <span v-if="unread || (hasNewDescendants && !unreadCount && !highContrastUnreadCount)" class="sidebar-tree-row-unread" aria-hidden="true"></span>
      <button
        v-if="hasNewDescendants && unreadCount"
        class="sidebar-tree-row-unread-count"
        type="button"
        :aria-label="`展开 ${unreadCount} 条未读内容`"
        :title="`展开 ${unreadCount} 条未读内容`"
        @click.stop="emit('expand-unread')"
      >{{ unreadCount }}</button>

      <span v-if="status" class="sidebar-tree-row-status">{{ status }}</span>
      <div v-if="$slots.actions" class="sidebar-tree-row-actions">
        <slot name="actions" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowRight, Check, Minus } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'

const props = defineProps({
  kind: { type: String, default: 'file' },
  label: { type: String, default: '' },
  labelTitle: { type: String, default: '' },
  icon: { type: String, default: '' },
  depth: { type: Number, default: 0 },
  active: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  open: { type: Boolean, default: false },
  editing: { type: Boolean, default: false },
  draggable: { type: Boolean, default: false },
  dropPosition: { type: String, default: '' },
  tone: { type: String, default: 'normal' },
  meta: { type: [String, Number], default: '' },
  status: { type: String, default: '' },
  unread: { type: Boolean, default: false },
  hasNewDescendants: { type: Boolean, default: false },
  unreadCount: { type: Number, default: 0 },
  highContrastUnreadCount: { type: Boolean, default: false },
  actionWidth: { type: Number, default: 72 },
  ariaLabel: { type: String, default: '' },
  interactive: { type: Boolean, default: false },
  checkState: { type: String, default: '' },
  checkLabel: { type: String, default: '' },
})

const emit = defineEmits(['activate', 'expand-unread', 'toggle-check'])

const rowStyle = computed(() => ({
  '--sidebar-tree-depth': props.depth,
  '--sidebar-tree-actions-width': `${props.actionWidth}px`,
}))
</script>

<style scoped>
.sidebar-tree-row {
  position: relative;
  display: flex;
  align-items: center;
  width: calc(100% - 12px);
  min-width: 0;
  height: 24px;
  min-height: 24px;
  margin: 1px 6px;
  padding: 0 8px 0 calc(8px + var(--sidebar-tree-depth) * 16px);
  overflow: hidden;
  border-radius: 6px;
  background: transparent;
  color: var(--vk-text);
  transition: background-color var(--vk-motion-standard) ease, color var(--vk-motion-standard) ease;
}

.sidebar-tree-row:hover,
.sidebar-tree-row.drop-inside,
.sidebar-tree-row:has(.sidebar-tree-row-main:focus-visible) {
  background: var(--vk-bg-hover);
}

.sidebar-tree-row.active,
.sidebar-tree-row.selected {
  background: var(--vk-selected-bg);
  color: var(--vk-selected-fg);
}


.sidebar-tree-row.tone-strong { font-weight: var(--vk-weight-strong); }
.sidebar-tree-row.tone-medium { font-weight: var(--vk-weight-medium); }

.sidebar-tree-row:has(.sidebar-tree-separator) {
  height: 18px;
  min-height: 18px;
  margin-top: 4px;
  margin-bottom: 4px;
  padding: 0 8px;
  pointer-events: none;
}

.sidebar-tree-row:has(.sidebar-tree-separator.interactive) {
  pointer-events: auto;
  cursor: grab;
}

.sidebar-tree-row:has(.sidebar-tree-separator.interactive):active {
  cursor: grabbing;
}

.sidebar-tree-separator {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 1px;
  background: color-mix(in srgb, var(--vk-border) 76%, transparent);
}

.sidebar-tree-separator.is-labeled {
  height: auto;
  min-height: 18px;
  background: transparent;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-weight: var(--vk-weight-strong);
  letter-spacing: var(--vk-tracking-meta);
  line-height: var(--vk-leading-label);
  white-space: nowrap;
}

.sidebar-tree-separator.is-labeled::before,
.sidebar-tree-separator.is-labeled::after {
  content: "";
  height: 1px;
  background: color-mix(in srgb, var(--vk-border) 76%, transparent);
}

.sidebar-tree-separator.is-labeled::before { flex: 0 0 10px; }
.sidebar-tree-separator.is-labeled::after { flex: 1 1 auto; }

.sidebar-tree-row-main {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  width: 100%;
  min-width: 0;
  min-height: 24px;
  gap: 6px;
  padding: 3px 0;
  border: 0;
  border-radius: var(--vk-radius-control);
  outline: none;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.sidebar-tree-row-check {
  width: 14px;
  height: 14px;
  display: grid;
  flex: 0 0 14px;
  margin-right: 6px;
  padding: 0;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--vk-muted) 52%, var(--vk-border));
  border-radius: 4px;
  background: var(--vk-bg-panel);
  color: var(--vk-action-fg);
  cursor: pointer;
}

.sidebar-tree-row-check.is-checked,
.sidebar-tree-row-check.is-indeterminate {
  border-color: var(--vk-action-bg);
  background: var(--vk-action-bg);
}

.sidebar-tree-row-check :deep(svg) { width: 11px; height: 11px; stroke-width: 3; }
.sidebar-tree-row-check:focus-visible { outline: none; box-shadow: var(--vk-focus-ring); }

.sidebar-tree-row.has-status .sidebar-tree-row-main {
  padding-right: 48px;
}

.sidebar-tree-row.has-meta .sidebar-tree-row-main {
  padding-right: 22px;
}

.sidebar-tree-row.has-unread .sidebar-tree-row-main { padding-right: 22px; }
.sidebar-tree-row.has-unread.has-meta .sidebar-tree-row-main,
.sidebar-tree-row.has-new-descendants.has-meta .sidebar-tree-row-main { padding-right: 44px; }
.sidebar-tree-row.has-unread-count .sidebar-tree-row-main { padding-right: 30px; }
.sidebar-tree-row.has-unread-count.has-meta .sidebar-tree-row-main { padding-right: 50px; }

.sidebar-tree-row-disclosure,
.sidebar-tree-row-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
}

.sidebar-tree-row-disclosure {
  transform: rotate(0deg);
  transform-origin: center;
  transition: transform var(--vk-motion-standard) var(--vk-ease-out);
}

.sidebar-tree-row.open .sidebar-tree-row-disclosure {
  transform: rotate(90deg);
}

.sidebar-tree-row-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: var(--vk-type-label-size);
  font-weight: inherit;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-tree-row.has-unread .sidebar-tree-row-label { font-weight: var(--vk-weight-strong); }

.sidebar-tree-row-meta {
  position: absolute;
  right: 8px;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
  font-weight: var(--vk-weight-regular);
}

.sidebar-tree-row.has-unread .sidebar-tree-row-meta,
.sidebar-tree-row.has-new-descendants .sidebar-tree-row-meta { right: 22px; }
.sidebar-tree-row.has-unread-count .sidebar-tree-row-meta { right: 30px; }

.sidebar-tree-row-unread {
  position: absolute;
  right: 9px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--vk-accent-strong);
  opacity: 1;
  transform: scale(1);
  transition: opacity 120ms var(--vk-ease-out), transform 120ms var(--vk-ease-out);
}
.sidebar-tree-row.active .sidebar-tree-row-unread,
.sidebar-tree-row.selected .sidebar-tree-row-unread {
  background: currentColor;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--vk-selected-bg) 88%, transparent);
}
.sidebar-tree-row-unread-count {
  position: absolute;
  right: 5px;
  z-index: 4;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border: 0;
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-accent) 16%, transparent);
  color: var(--vk-accent-strong);
  font: inherit;
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
  font-weight: var(--vk-weight-strong);
  line-height: 18px;
  cursor: pointer;
  transition: opacity 120ms var(--vk-ease-out), transform 120ms var(--vk-ease-out), background-color 120ms var(--vk-ease-out);
}
.sidebar-tree-row-unread-count:hover,
.sidebar-tree-row-unread-count:focus-visible { outline: none; background: color-mix(in srgb, var(--vk-accent) 22%, transparent); }
.sidebar-tree-row.high-contrast-unread-count .sidebar-tree-row-unread-count {
  min-width: 20px;
  background: var(--vk-accent-strong);
  color: var(--vk-bg-panel);
  font-weight: var(--vk-weight-display);
}
.sidebar-tree-row.high-contrast-unread-count .sidebar-tree-row-unread-count:hover,
.sidebar-tree-row.high-contrast-unread-count .sidebar-tree-row-unread-count:focus-visible { background: color-mix(in srgb, var(--vk-accent-strong) 88%, var(--vk-text)); }

.sidebar-tree-row-status {
  position: absolute;
  right: 8px;
  flex: 0 0 auto;
  color: var(--vk-accent-strong);
  font-size: var(--vk-type-micro-size);
  font-weight: var(--vk-weight-strong);
  line-height: 18px;
}

.sidebar-tree-row-actions {
  position: absolute;
  top: 50%;
  right: 8px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
}

.sidebar-tree-row.has-unread-count .sidebar-tree-row-actions { right: 30px; }

@media (hover: hover) and (pointer: fine) {
  .sidebar-tree-row:hover .sidebar-tree-row-main {
    padding-right: var(--sidebar-tree-actions-width);
  }

  .sidebar-tree-row:hover .sidebar-tree-row-actions {
    opacity: 1;
    pointer-events: auto;
  }

  .sidebar-tree-row:hover .sidebar-tree-row-status {
    opacity: 0;
  }

  .sidebar-tree-row.has-actions:hover .sidebar-tree-row-meta {
    opacity: 0;
  }
  .sidebar-tree-row.has-actions:hover .sidebar-tree-row-unread { opacity: 0; transform: scale(0.6); }

}

.sidebar-tree-row:has(:focus-visible) .sidebar-tree-row-main {
  padding-right: var(--sidebar-tree-actions-width);
}

.sidebar-tree-row:has(:focus-visible) .sidebar-tree-row-actions {
  opacity: 1;
  pointer-events: auto;
}

.sidebar-tree-row:has(:focus-visible) .sidebar-tree-row-status {
  opacity: 0;
}

.sidebar-tree-row.has-actions:has(:focus-visible) .sidebar-tree-row-meta {
  opacity: 0;
}
.sidebar-tree-row.has-actions:has(:focus-visible) .sidebar-tree-row-unread { opacity: 0; transform: scale(0.6); }

:deep(.sidebar-tree-action) {
  display: inline-grid;
  width: 20px;
  height: 20px;
  padding: 0;
  place-items: center;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--vk-muted);
  line-height: 0;
  cursor: pointer;
}

:deep(.sidebar-tree-action:hover) {
  background: color-mix(in srgb, var(--vk-text) 8%, transparent);
  color: var(--vk-text);
}

:deep(.sidebar-tree-action.danger:hover) {
  background: color-mix(in srgb, var(--vk-danger) 10%, transparent);
  color: var(--vk-danger);
}

:deep(.sidebar-tree-action:focus-visible) {
  outline: none;
  box-shadow: var(--vk-focus-ring);
}

:deep(.sidebar-tree-action:disabled),
:deep(.sidebar-tree-action.disabled) {
  opacity: 0.42;
  cursor: not-allowed;
}

.sidebar-tree-row::before,
.sidebar-tree-row::after {
  content: "";
  position: absolute;
  right: 6px;
  left: calc(6px + var(--sidebar-tree-depth) * 14px);
  z-index: 2;
  pointer-events: none;
}

.sidebar-tree-row.drop-before::before,
.sidebar-tree-row.drop-after::after {
  height: 2px;
  background: var(--vk-drag-indicator);
}

.sidebar-tree-row.drop-before::before { top: 0; }
.sidebar-tree-row.drop-after::after { bottom: 0; }

.sidebar-tree-row.editing {
  gap: 6px;
  padding-top: 1px;
  padding-bottom: 1px;
}

@media (prefers-reduced-motion: reduce) {
.sidebar-tree-row,
  .sidebar-tree-row-disclosure,
  .sidebar-tree-row-unread {
    transition: none;
  }
}
</style>
