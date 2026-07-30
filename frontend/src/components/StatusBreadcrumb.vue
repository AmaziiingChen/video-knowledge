<template>
  <nav
    v-if="visibleItems.length"
    ref="breadcrumbRef"
    class="statusbar-breadcrumb"
    :class="{ 'is-hidden': availableWidth > 0 && availableWidth < 112 }"
    :aria-label="ariaLabel"
  >
    <ol class="statusbar-breadcrumb-list">
      <li
        v-for="(item, index) in visibleItems"
        :key="item.id"
        class="statusbar-breadcrumb-item"
        :class="{
          'is-current': item.current,
          'is-elided': item.elided,
          'is-root': item.kind === 'root',
          'is-folder': item.kind === 'folder',
        }"
      >
        <button
          v-if="item.actionable"
          type="button"
          class="statusbar-breadcrumb-link"
          :title="item.title || item.label"
          @click="$emit('select', item)"
        >
          <span>{{ item.label }}</span>
        </button>
        <span
          v-else
          class="statusbar-breadcrumb-page"
          :title="item.title || item.label"
          :aria-current="item.current ? 'page' : undefined"
        >{{ item.label }}</span>
        <span v-if="index < visibleItems.length - 1" class="statusbar-breadcrumb-separator" aria-hidden="true">›</span>
      </li>
    </ol>
  </nav>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  ariaLabel: { type: String, default: '当前资料位置' },
})

defineEmits(['select'])

const breadcrumbRef = ref(null)
const availableWidth = ref(0)
let resizeObserver = null

function measureLabel(label) {
  if (!breadcrumbRef.value || typeof document === 'undefined') return String(label || '').length * 8
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')
  context.font = getComputedStyle(breadcrumbRef.value).font
  return context.measureText(String(label || '')).width
}

function itemWidth(item, { current = false } = {}) {
  if (item?.elided) return 12
  // Ancestors use their natural text width so widening the window can restore
  // hidden levels.  Only the current document needs a small reserved minimum:
  // its remaining text is allowed to truncate through flexbox.
  return current ? Math.min(measureLabel(item?.label), 88) : measureLabel(item?.label)
}

function requiredWidth(items) {
  return items.reduce((total, item, index) => (
    total + itemWidth(item, { current: item.current }) + (index ? 16 : 0)
  ), 0)
}

const visibleItems = computed(() => {
  const items = props.items.filter((item) => item?.label)
  if (items.length <= 3 || !availableWidth.value || requiredWidth(items) <= availableWidth.value) return items

  const elided = { id: '__elided__', label: '…', title: '已省略目录', elided: true }
  const candidates = [
    [items[0], elided, ...items.slice(-2)],
    [items[0], elided, items.at(-1)],
    [elided, items.at(-1)],
  ]
  return candidates.find((candidate) => requiredWidth(candidate) <= availableWidth.value) || candidates.at(-1)
})

onMounted(() => {
  resizeObserver = new ResizeObserver(([entry]) => {
    availableWidth.value = Math.floor(entry.contentRect.width)
  })
  if (breadcrumbRef.value) resizeObserver.observe(breadcrumbRef.value)
})

onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<style scoped>
.statusbar-breadcrumb {
  display: flex;
  width: 100%;
  min-width: 0;
  flex: 1 1 auto;
  color: var(--vk-muted);
}

.statusbar-breadcrumb.is-hidden {
  visibility: hidden;
}

.statusbar-breadcrumb-list {
  display: flex;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: 0;
  align-items: center;
  list-style: none;
  overflow: hidden;
}

.statusbar-breadcrumb-item {
  display: inline-flex;
  min-width: 0;
  flex: 0 0 auto;
  align-items: center;
}

.statusbar-breadcrumb-item.is-current {
  flex: 1 1 0;
  overflow: hidden;
}

.statusbar-breadcrumb-link {
  display: block;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  line-height: inherit;
  white-space: nowrap;
}

.statusbar-breadcrumb-link {
  cursor: pointer;
}

.statusbar-breadcrumb-link:hover {
  color: var(--vk-accent-strong);
}

.statusbar-breadcrumb-link:focus-visible {
  outline: 1px solid var(--vk-accent);
  outline-offset: 2px;
  border-radius: var(--vk-radius-compact);
  color: var(--vk-accent-strong);
}

.statusbar-breadcrumb-page {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
  font-weight: var(--vk-weight-regular);
}

.statusbar-breadcrumb-item.is-elided {
  flex: 0 0 auto;
}

.statusbar-breadcrumb-item.is-elided .statusbar-breadcrumb-page {
  max-width: none;
  color: var(--vk-muted);
  font-weight: var(--vk-weight-regular);
}

.statusbar-breadcrumb-separator {
  flex: 0 0 auto;
  margin: 0 var(--vk-space-xs);
  color: color-mix(in srgb, var(--vk-muted) 62%, transparent);
}

</style>
