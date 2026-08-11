<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="command-palette-backdrop"
      @pointerdown.self="close"
    >
      <section
        ref="dialogRef"
        class="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="快速打开"
      >
        <label class="command-palette-input-wrap">
          <el-icon><Search /></el-icon>
          <input
            ref="inputRef"
            v-model="query"
            type="search"
            name="command-palette-search"
            autocomplete="off"
            placeholder="搜索资料、页面和操作…"
            aria-label="搜索资料、页面和操作"
            aria-controls="command-palette-results"
            :aria-activedescendant="activeItem ? `command-item-${activeItem.id}` : undefined"
            @keydown="handleInputKeydown"
          >
          <kbd>⌘K</kbd>
        </label>

        <div id="command-palette-results" class="command-palette-results" role="listbox" aria-label="快速打开结果">
          <template v-for="(item, index) in filteredItems" :key="item.id">
            <p v-if="index === 0 || item.group !== filteredItems[index - 1].group" class="command-palette-group">{{ item.group }}</p>
            <button
              :id="`command-item-${item.id}`"
              ref="itemRefs"
              type="button"
              role="option"
              class="command-palette-item"
              :class="{ active: activeIndex === index }"
              :aria-selected="activeIndex === index"
              @mousemove="activeIndex = index"
              @click="select(item)"
            >
              <span class="command-palette-item-mark" :class="`is-${item.kind || 'action'}`">{{ item.mark || defaultMark(item) }}</span>
              <span class="command-palette-item-copy">
                <strong>{{ item.title }}</strong>
                <small v-if="item.subtitle">{{ item.subtitle }}</small>
              </span>
              <kbd v-if="item.shortcut">{{ item.shortcut }}</kbd>
            </button>
          </template>
          <div v-if="!filteredItems.length" class="command-palette-empty">
            <strong>没有匹配的结果</strong>
            <span>尝试搜索资料标题、订阅源或页面名称。</span>
          </div>
        </div>

        <footer class="command-palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd>选择</span>
          <span><kbd>↵</kbd>打开</span>
          <span><kbd>Esc</kbd>关闭</span>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search } from './macosSymbolComponents.js'
import { filterCommandItems } from './commandPaletteState.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'select'])

const query = ref('')
const activeIndex = ref(0)
const inputRef = ref(null)
const dialogRef = ref(null)
const itemRefs = ref([])
let previousFocus = null

const filteredItems = computed(() => filterCommandItems(props.items, query.value))
const activeItem = computed(() => filteredItems.value[activeIndex.value] || null)

watch(filteredItems, (items) => {
  if (!items.length) activeIndex.value = 0
  else activeIndex.value = Math.max(0, Math.min(activeIndex.value, items.length - 1))
})

watch(() => props.modelValue, async (open) => {
  if (!open) return
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  query.value = ''
  activeIndex.value = 0
  await nextTick()
  inputRef.value?.focus()
})

onMounted(() => window.addEventListener('keydown', handleGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleGlobalKeydown))

function close({ restoreFocus = true } = {}) {
  emit('update:modelValue', false)
  if (restoreFocus) nextTick(() => previousFocus?.focus?.())
}

function select(item) {
  if (!item) return
  emit('select', item)
  close({ restoreFocus: false })
}

function defaultMark(item) {
  if (item.kind === 'content') return '⌁'
  if (item.kind === 'view') return '◫'
  return '→'
}

function moveActive(direction) {
  const count = filteredItems.value.length
  if (!count) return
  activeIndex.value = (activeIndex.value + direction + count) % count
  nextTick(() => itemRefs.value[activeIndex.value]?.scrollIntoView({ block: 'nearest' }))
}

function handleInputKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveActive(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveActive(-1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    select(activeItem.value)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

function handleGlobalKeydown(event) {
  const isShortcut = (event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === 'k'
  if (isShortcut) {
    event.preventDefault()
    if (props.modelValue) close()
    else emit('update:modelValue', true)
    return
  }
  if (props.modelValue && event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}
</script>

<style scoped>
.command-palette-backdrop {
  position: fixed;
  z-index: 3600;
  inset: 0;
  display: grid;
  align-items: start;
  justify-items: center;
  padding: min(14vh, 116px) var(--vk-space-panel) var(--vk-space-panel);
  background: color-mix(in srgb, var(--vk-text) 13%, transparent);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.command-palette {
  width: min(640px, 100%);
  max-height: min(680px, calc(100vh - 32px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 84%, transparent);
  border-radius: var(--vk-radius-feature);
  background: color-mix(in srgb, var(--vk-bg-panel) 96%, white);
  box-shadow: 0 20px 48px color-mix(in srgb, var(--vk-text) 18%, transparent);
}

.command-palette-input-wrap {
  min-height: 48px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 0 13px;
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 74%, transparent);
  color: var(--vk-muted);
}

.command-palette-input-wrap input {
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-reading-size);
}

.command-palette-input-wrap input::placeholder { color: color-mix(in srgb, var(--vk-muted) 76%, transparent); }
.command-palette kbd {
  min-width: 18px;
  padding: 2px 5px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 84%, transparent);
  border-radius: var(--vk-radius-compact);
  background: color-mix(in srgb, var(--vk-bg-hover) 52%, transparent);
  color: var(--vk-muted);
  font-family: var(--vk-font-mono);
  font-size: var(--vk-type-micro-size);
  line-height: 1.1;
  text-align: center;
}

.command-palette-results {
  min-height: 130px;
  max-height: 510px;
  padding: 7px;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.command-palette-group {
  margin: 8px 7px 4px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-weight: var(--vk-weight-medium);
  letter-spacing: var(--vk-tracking-meta);
}
.command-palette-group:first-child { margin-top: 2px; }

.command-palette-item {
  width: 100%;
  min-height: 42px;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 5px 7px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  cursor: pointer;
}

.command-palette-item:hover,
.command-palette-item.active { background: color-mix(in srgb, var(--vk-bg-hover) 86%, transparent); }
.command-palette-item:focus-visible { outline: 0; box-shadow: var(--vk-focus-ring); }

.command-palette-item-mark {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--vk-border) 82%, transparent);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 70%, var(--vk-bg-hover));
  color: var(--vk-accent-strong);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-strong);
}
.command-palette-item-mark.is-content { color: var(--vk-muted); }
.command-palette-item-copy { min-width: 0; display: grid; gap: 1px; }
.command-palette-item-copy strong,
.command-palette-item-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.command-palette-item-copy strong { font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-medium); }
.command-palette-item-copy small { color: var(--vk-muted); font-size: var(--vk-type-meta-size); }

.command-palette-empty { min-height: 160px; display: grid; align-content: center; justify-items: center; gap: 5px; color: var(--vk-muted); text-align: center; }
.command-palette-empty strong { color: var(--vk-text); font-size: var(--vk-type-body-size); }
.command-palette-empty span { font-size: var(--vk-type-label-size); }

.command-palette-footer { min-height: 34px; display: flex; align-items: center; gap: 12px; padding: 0 12px; border-top: 1px solid color-mix(in srgb, var(--vk-border) 68%, transparent); color: var(--vk-muted); font-size: var(--vk-type-meta-size); }
.command-palette-footer span { display: inline-flex; align-items: center; gap: 3px; }

@media (prefers-reduced-transparency: reduce) {
  .command-palette-backdrop { backdrop-filter: none; -webkit-backdrop-filter: none; }
  .command-palette { background: var(--vk-bg-panel); }
}
</style>
