<template>
  <section class="sidebar-trash" :class="{ open }">
    <button class="sidebar-trash-toggle" type="button" @click="toggleOpen">
      <SvgMaskIcon src="trash" :size="14" />
      <span>回收站</span>
      <small>{{ entries.length || '' }}</small>
      <el-icon class="sidebar-trash-arrow"><ArrowRight /></el-icon>
    </button>
    <Transition name="sidebar-trash-list">
      <div v-if="open" class="sidebar-trash-list" v-loading="loading">
        <div v-if="entries.length" class="sidebar-trash-actions">
          <button type="button" class="danger" @click="requestEmptyTrash">清空回收站</button>
        </div>
        <div v-for="entry in entries" :key="`${entry.entry_type}:${entry.id}`" class="sidebar-trash-entry">
          <SvgMaskIcon :src="entryIcon(entry)" :size="14" />
          <span :title="entry.name">{{ entry.name }}</span>
          <button type="button" @click="$emit('restore', entry)">恢复</button>
          <button type="button" class="danger" @click.stop="requestPermanentDeletion(entry)">删除</button>
        </div>
        <p v-if="!loading && !entries.length" class="sidebar-trash-empty">回收站为空</p>
      </div>
    </Transition>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowRight } from '../components/macosSymbolComponents.js'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import { requestDestructiveConfirmation } from '../composables/useDestructiveConfirm'
import { libraryContentIcon } from '../utils/contentIcons'

const props = defineProps({
  entries: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['load', 'restore', 'permanently-delete', 'empty'])
const open = ref(false)

function toggleOpen() {
  open.value = !open.value
  if (open.value) emit('load')
}

function entryIcon(entry) {
  return entry?.entry_type === 'content' ? libraryContentIcon(entry) : 'folder'
}

async function requestPermanentDeletion(entry) {
  const confirmed = await requestDestructiveConfirmation({
    title: '彻底删除',
    message: '彻底删除后将同时清理相关缓存，无法恢复。',
    confirmLabel: '彻底删除',
  })
  if (confirmed) emit('permanently-delete', entry)
}

async function requestEmptyTrash() {
  const count = props.entries.length
  if (!count) return
  const confirmed = await requestDestructiveConfirmation({
    title: '清空回收站',
    message: `将彻底删除回收站中的 ${count} 个项目及相关缓存，无法恢复。`,
    confirmLabel: '清空回收站',
  })
  if (confirmed) emit('empty')
}
</script>

<style scoped>
.sidebar-trash {
  min-width: 0;
  margin: 0 calc(var(--vk-space-control) + 4px) 0 4px;
  padding-top: 5px;
  border-top: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
}

.sidebar-trash-toggle {
  width: 100%;
  min-height: 28px;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto 14px;
  align-items: center;
  gap: 6px;
  padding: 0 6px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--vk-muted);
  text-align: left;
  cursor: pointer;
}

.sidebar-trash-toggle:hover {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.sidebar-trash-toggle small {
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
}

.sidebar-trash-arrow {
  transition: transform 0.16s ease;
}

.sidebar-trash.open .sidebar-trash-arrow {
  transform: rotate(90deg);
}

.sidebar-trash-list {
  --el-loading-spinner-size: 14px;
  min-height: 28px;
  display: grid;
  gap: 2px;
  padding: 3px 0 0 18px;
}

.sidebar-trash-list-enter-active {
  transition: opacity var(--vk-motion-standard) var(--vk-ease-out), transform var(--vk-motion-standard) var(--vk-ease-out);
}

.sidebar-trash-list-leave-active {
  transition: opacity var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out);
}

.sidebar-trash-list-enter-from,
.sidebar-trash-list-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.sidebar-trash-list :deep(.el-loading-spinner) {
  margin-top: -7px;
}

.sidebar-trash-list :deep(.el-loading-spinner .circular) {
  width: 14px;
  height: 14px;
}

.sidebar-trash-actions {
  min-height: 23px;
  display: flex;
  justify-content: flex-end;
  padding-right: 2px;
}

.sidebar-trash-actions button {
  padding: 2px 3px;
  border: 0;
  background: transparent;
  color: var(--vk-error-text);
  font: inherit;
  font-size: var(--vk-type-meta-size);
  cursor: pointer;
}

.sidebar-trash-entry {
  min-height: 27px;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 5px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.sidebar-trash-entry > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-trash-entry button {
  padding: 2px 3px;
  border: 0;
  background: transparent;
  color: var(--vk-accent-strong);
  font: inherit;
  cursor: pointer;
}

.sidebar-trash-entry button.danger {
  color: var(--vk-error-text);
}

.sidebar-trash-empty {
  margin: 5px 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}
</style>
