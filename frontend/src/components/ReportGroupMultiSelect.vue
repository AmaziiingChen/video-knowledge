<template>
  <el-popover
    v-model:visible="open"
    class="report-group-multi-select"
    placement="bottom-start"
    :width="300"
    trigger="click"
    teleported
    persistent
    popper-class="report-group-multi-select-popper"
    @show="focusSearch"
  >
    <template #reference>
      <button
        type="button"
        class="report-group-summary"
        :class="{ 'is-empty': !selectedGroups.length }"
        :disabled="disabled"
        :aria-label="ariaLabel"
        aria-haspopup="listbox"
        :aria-expanded="open"
      >
        <template v-if="selectedGroups.length">
          <span
            v-for="group in visibleGroups"
            :key="group.id"
            class="report-group-summary-chip"
            :title="group.name"
          >{{ group.name }}</span>
          <span v-if="selectedGroups.length > visibleGroups.length" class="report-group-summary-more">+{{ selectedGroups.length - visibleGroups.length }}</span>
          <span class="report-group-summary-edit" aria-hidden="true">＋</span>
        </template>
        <template v-else>
          <span>{{ placeholder }}</span>
          <span class="report-group-summary-add" aria-hidden="true">＋</span>
        </template>
      </button>
    </template>

    <section class="report-group-editor" :aria-label="ariaLabel">
      <header class="report-group-editor-head">
        <span>报告分组</span>
        <small>已选 {{ selectedIds.length }}/{{ max }}</small>
      </header>
      <div v-if="selectedGroups.length" class="report-group-editor-chips">
        <span v-for="group in selectedGroups" :key="group.id" class="report-group-editor-chip">
          {{ group.name }}
          <button type="button" :aria-label="`移除分组 ${group.name}`" @click="toggleGroup(group.id)">×</button>
        </span>
      </div>
      <el-input
        ref="searchInput"
        v-model="query"
        class="report-group-editor-search"
        name="report-group-search"
        autocomplete="off"
        clearable
        placeholder="搜索或添加分组…"
        :aria-activedescendant="activeOption ? `report-group-option-${activeOption.id}` : undefined"
        @keydown="handleSearchKeydown"
      />
      <div class="report-group-editor-options vk-scroll-area" role="listbox" :aria-label="`${ariaLabel} 可选项`">
        <button
          v-for="(group, index) in filteredGroups"
          :key="group.id"
          :id="`report-group-option-${group.id}`"
          :ref="(element) => setOptionRef(group.id, element)"
          type="button"
          role="option"
          class="report-group-editor-option"
          :aria-selected="selectedIdSet.has(String(group.id))"
          :disabled="!selectedIdSet.has(String(group.id)) && selectedIds.length >= max"
          :class="{ selected: selectedIdSet.has(String(group.id)), active: activeOptionIndex === index }"
          @mousemove="activeOptionIndex = index"
          @click="toggleGroup(group.id)"
        >
          <span>{{ group.name }}</span>
          <span v-if="selectedIdSet.has(String(group.id))" aria-hidden="true">✓</span>
        </button>
        <p v-if="!filteredGroups.length" class="report-group-multi-select-empty">
          {{ groups.length ? '没有匹配的分组。' : '尚未创建分组，请先在“生成报告”中新增。' }}
        </p>
      </div>
    </section>
  </el-popover>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  groups: { type: Array, default: () => [] },
  max: { type: Number, default: 3 },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '添加报告分组' },
  ariaLabel: { type: String, default: '报告分组' },
})

const emit = defineEmits(['update:modelValue'])

const selectedIds = computed(() => [...new Set(
  (props.modelValue || []).map(String).filter(Boolean),
)].slice(0, props.max))
const selectedIdSet = computed(() => new Set(selectedIds.value))
const selectedGroups = computed(() => props.groups.filter((group) => selectedIdSet.value.has(String(group.id))))
// 管理表格的单元格必须先保证一个分组名称可读；额外分组用数量提示，
// 避免多个 chip 互相挤压后只剩一个字。
const visibleGroups = computed(() => selectedGroups.value.slice(0, 1))
const query = ref('')
const open = ref(false)
const searchInput = ref(null)
const optionRefs = new Map()
const activeOptionIndex = ref(0)
const filteredGroups = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  if (!keyword) return props.groups
  return props.groups.filter((group) => String(group.name || '').toLocaleLowerCase().includes(keyword))
})
const activeOption = computed(() => filteredGroups.value[activeOptionIndex.value] || null)

watch(filteredGroups, (groups) => {
  activeOptionIndex.value = groups.length
    ? Math.max(0, Math.min(activeOptionIndex.value, groups.length - 1))
    : 0
})

watch(open, (visible) => {
  if (!visible) return
  query.value = ''
  activeOptionIndex.value = 0
})

function focusSearch() {
  nextTick(() => searchInput.value?.focus())
}

function setOptionRef(groupId, element) {
  if (element) optionRefs.set(String(groupId), element)
  else optionRefs.delete(String(groupId))
}

function focusActiveOption() {
  const group = activeOption.value
  if (!group) return
  nextTick(() => optionRefs.get(String(group.id))?.scrollIntoView({ block: 'nearest' }))
}

function moveActiveOption(direction) {
  const count = filteredGroups.value.length
  if (!count) return
  activeOptionIndex.value = (activeOptionIndex.value + direction + count) % count
  focusActiveOption()
}

function handleSearchKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    open.value = false
  } else if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveActiveOption(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveActiveOption(-1)
  } else if (event.key === 'Enter') {
    const group = activeOption.value
    if (!group || (!selectedIdSet.value.has(String(group.id)) && selectedIds.value.length >= props.max)) return
    event.preventDefault()
    toggleGroup(group.id)
  }
}

function toggleGroup(groupId) {
  const id = String(groupId)
  const next = selectedIdSet.value.has(id)
    ? selectedIds.value.filter((value) => value !== id)
    : [...selectedIds.value, id].slice(0, props.max)
  emit('update:modelValue', next)
}
</script>

<style scoped>
.report-group-multi-select { display: block; min-width: 0; }

.report-group-summary {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  max-width: none;
  min-height: 28px;
  gap: 4px;
  padding: 2px 5px;
  overflow: visible;
  border: 1px solid transparent;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-meta-size);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--vk-motion-fast) var(--vk-ease-out), background-color var(--vk-motion-fast) var(--vk-ease-out);
}

.report-group-summary:hover:not(:disabled),
.report-group-summary:focus-visible {
  border-color: color-mix(in srgb, var(--vk-border) 92%, transparent);
  background: color-mix(in srgb, var(--vk-bg-hover) 74%, transparent);
  outline: none;
}

.report-group-summary:focus-visible { box-shadow: var(--vk-focus-ring); }
.report-group-summary:disabled { cursor: not-allowed; opacity: .48; }
.report-group-summary.is-empty { color: var(--vk-muted); }

.report-group-summary-chip,
.report-group-editor-chip {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  height: 22px;
  padding: 0 7px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-accent) 16%, var(--vk-border));
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-accent) 6%, var(--vk-bg-panel));
  color: color-mix(in srgb, var(--vk-text) 88%, var(--vk-accent-strong));
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-group-summary-chip {
  flex: 0 0 auto;
  min-width: 72px;
  max-width: 144px;
  box-sizing: border-box;
}
.report-group-summary-more { color: var(--vk-muted); font-variant-numeric: tabular-nums; }
.report-group-summary-edit { color: var(--vk-muted); opacity: 0; }
.report-group-summary:hover .report-group-summary-edit,
.report-group-summary:focus-visible .report-group-summary-edit { opacity: 1; }
.report-group-summary-add { color: var(--vk-accent-strong); font-size: 15px; line-height: 1; }

:global(.report-group-multi-select-popper.el-popper) {
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-bg-panel) 97%, transparent);
  box-shadow: 0 14px 30px color-mix(in srgb, var(--vk-text) 13%, transparent), 0 1px 4px color-mix(in srgb, var(--vk-text) 8%, transparent);
  backdrop-filter: blur(18px) saturate(1.08);
}

.report-group-editor { display: grid; gap: 8px; padding: 10px; }
.report-group-editor-head { display: flex; align-items: center; justify-content: space-between; color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-medium); }
.report-group-editor-head small { color: var(--vk-muted); font-size: var(--vk-type-meta-size); font-weight: var(--vk-weight-regular); }
.report-group-editor-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.report-group-editor-chip { max-width: 100%; padding-right: 3px; }
.report-group-editor-chip > button { display: grid; width: 17px; height: 17px; margin-left: 4px; padding: 0; place-items: center; border: 0; border-radius: var(--vk-radius-compact); background: transparent; color: inherit; font: inherit; font-size: 14px; line-height: 1; cursor: pointer; }
.report-group-editor-chip > button:hover { background: color-mix(in srgb, var(--vk-text) 9%, transparent); }
.report-group-editor-search :deep(.el-input__wrapper) { min-height: 30px; border-radius: var(--vk-radius-control); box-shadow: 0 0 0 1px color-mix(in srgb, var(--vk-border) 82%, transparent) inset; }
.report-group-editor-options { display: grid; max-height: 196px; gap: 2px; overflow-y: auto; overscroll-behavior: contain; }
.report-group-editor-option { display: flex; align-items: center; justify-content: space-between; min-height: 32px; padding: 6px 9px; border: 0; border-radius: var(--vk-radius-control); background: transparent; color: var(--vk-text); font: inherit; font-size: var(--vk-type-label-size); text-align: left; cursor: pointer; }
.report-group-editor-option:hover:not(:disabled) { background: var(--vk-bg-hover); }
.report-group-editor-option.active:not(:disabled) { background: color-mix(in srgb, var(--vk-bg-hover) 78%, transparent); }
.report-group-editor-option.selected { color: var(--vk-accent-strong); font-weight: var(--vk-weight-medium); }
.report-group-editor-option:disabled { color: var(--vk-muted); cursor: not-allowed; opacity: .52; }

.report-group-multi-select-empty {
  margin: 0;
  padding: 8px 10px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  line-height: 1.45;
}
</style>
