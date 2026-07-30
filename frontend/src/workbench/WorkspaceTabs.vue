<template>
  <div class="workspace-tabs-shell">
    <div
      ref="tabsContainer"
      class="workspace-tabs"
      role="tablist"
      aria-label="已打开内容"
      @scroll="updateOverflow"
      @wheel="handleWheel"
      @keydown="handleTablistKeydown"
    >
      <span
        class="workspace-tab-selection"
        :class="{ 'is-ready': activeSelectionReady }"
        :style="activeSelectionStyle"
        aria-hidden="true"
      ></span>
      <div
        v-for="tab in tabs"
        :key="tab.id"
        :ref="(element) => setTabRef(tab.id, element)"
        class="workspace-tab-item"
        :class="{ active: activeTabId === tab.id }"
        @contextmenu="openTabContextMenu($event, tab)"
      >
        <button
          class="workspace-tab"
          :class="{ active: activeTabId === tab.id }"
          type="button"
          role="tab"
          :tabindex="activeTabId === tab.id ? 0 : -1"
          :aria-selected="activeTabId === tab.id"
          :title="tab.title"
          @click="emit('activate', tab.id)"
        >
          <span class="workspace-tab-label">{{ tab.title }}</span>
          <span v-if="tab.dirty" class="workspace-tab-dirty" aria-label="未保存"></span>
        </button>
        <button
          class="workspace-tab-close"
          type="button"
          :aria-label="`关闭 ${tab.title}`"
          title="关闭标签"
          @click.stop="emit('close', tab.id)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="tabContextMenu"
        ref="tabContextMenuRef"
        class="workspace-tab-context-menu"
        :style="tabContextMenuStyle"
        role="menu"
        :aria-label="`${tabContextMenu.tab.title} 的操作`"
        @keydown="handleTabContextMenuKeydown"
      >
        <button
          type="button"
          role="menuitem"
          class="workspace-tab-context-menu-item"
          @click="closeContextTab"
        >
          <el-icon><Close /></el-icon>
          <span>关闭标签</span>
        </button>
        <button
          v-if="allowReveal"
          type="button"
          role="menuitem"
          class="workspace-tab-context-menu-item"
          @click="revealContextTab"
        >
          <SvgMaskIcon :src="finderIcon" :size="15" />
          <span>在 Finder 中显示</span>
        </button>
        <button
          type="button"
          role="menuitem"
          class="workspace-tab-context-menu-item"
          :disabled="tabs.length <= 1"
          @click="closeOtherContextTabs"
        >
          <SvgMaskIcon :src="eraserIcon" :size="15" />
          <span>关闭其他标签</span>
        </button>
        <button
          type="button"
          role="menuitem"
          class="workspace-tab-context-menu-item"
          :disabled="!contextTabsToRight.length"
          @click="closeContextTabsToRight"
        >
          <SvgMaskIcon :src="arrowRightIcon" :size="15" />
          <span>关闭右侧标签</span>
        </button>
        <div v-if="allowDelete" class="workspace-tab-context-menu-separator" role="separator"></div>
        <button
          v-if="allowDelete"
          type="button"
          role="menuitem"
          class="workspace-tab-context-menu-item danger"
          @click="deleteContextTab"
        >
          <SvgMaskIcon :src="trashIcon" :size="15" />
          <span>移入回收站</span>
        </button>
      </div>
    </Teleport>

    <div v-if="overflowing" class="workspace-tabs-controls">
      <button
        class="workspace-tabs-control"
        type="button"
        title="向左浏览标签"
        aria-label="向左浏览标签"
        :disabled="!canScrollLeft"
        @click="scrollTabs(-1)"
      >
        <el-icon><ArrowLeft /></el-icon>
      </button>
      <button
        class="workspace-tabs-control"
        type="button"
        title="向右浏览标签"
        aria-label="向右浏览标签"
        :disabled="!canScrollRight"
        @click="scrollTabs(1)"
      >
        <el-icon><ArrowRight /></el-icon>
      </button>
      <el-popover
        v-model:visible="managerOpen"
        placement="bottom-end"
        :width="312"
        trigger="click"
        :show-arrow="false"
        popper-class="workspace-tab-manager-popover"
      >
        <template #reference>
          <button
            class="workspace-tabs-control workspace-tabs-manager-button"
            type="button"
            title="全部标签"
            aria-label="打开全部标签"
          >
            <el-icon><ArrowDown /></el-icon>
          </button>
        </template>
        <div class="workspace-tab-manager">
          <label class="workspace-tab-manager-search">
            <el-icon><Search /></el-icon>
            <input
              v-model="searchQuery"
              type="search"
              name="open-tab-search"
              autocomplete="off"
              placeholder="搜索已打开标签…"
              aria-label="搜索已打开标签"
            />
          </label>
          <div class="workspace-tab-manager-list" role="listbox" aria-label="全部标签">
            <div
              v-for="tab in filteredTabs"
              :key="tab.id"
              class="workspace-tab-manager-row"
              :class="{ active: activeTabId === tab.id }"
            >
              <button
                class="workspace-tab-manager-select"
                type="button"
                role="option"
                :aria-selected="activeTabId === tab.id"
                :title="tab.title"
                @click="activateFromManager(tab.id)"
              >
                <span class="workspace-tab-manager-indicator"></span>
                <span>{{ tab.title }}</span>
              </button>
              <button
                class="workspace-tab-manager-close"
                type="button"
                :aria-label="`关闭 ${tab.title}`"
                title="关闭标签"
                @click="emit('close', tab.id)"
              >
                <el-icon><Close /></el-icon>
              </button>
            </div>
            <div v-if="!filteredTabs.length" class="workspace-tab-manager-empty">没有匹配的标签</div>
          </div>
          <div class="workspace-tab-manager-actions">
            <button type="button" :disabled="tabs.length <= 1" @click="closeOtherTabs">关闭其他</button>
            <button type="button" :disabled="!tabsToRight.length" @click="closeTabsToRight">关闭右侧</button>
            <button type="button" @click="closeAllTabs">关闭全部</button>
          </div>
        </div>
      </el-popover>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowLeft, ArrowRight, Close, Search } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import arrowRightIcon from '../../assets/arrow.right.svg'
import eraserIcon from '../../assets/eraser.svg'
import finderIcon from '../../assets/finder.svg'
import trashIcon from '../../assets/trash.svg'

const props = defineProps({
  tabs: { type: Array, default: () => [] },
  activeTabId: { type: String, default: '' },
  allowReveal: { type: Boolean, default: false },
  allowDelete: { type: Boolean, default: false },
})

const emit = defineEmits(['activate', 'close', 'close-tabs', 'reveal-tab', 'delete-tab'])

const tabsContainer = ref(null)
const tabRefs = new Map()
const overflowing = ref(false)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)
const managerOpen = ref(false)
const searchQuery = ref('')
const activeSelectionStyle = ref({})
const activeSelectionReady = ref(false)
const tabContextMenu = ref(null)
const tabContextMenuRef = ref(null)
let resizeObserver = null

const filteredTabs = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return props.tabs
  return props.tabs.filter((tab) => String(tab.title || '').toLocaleLowerCase().includes(query))
})

const tabsToRight = computed(() => {
  const activeIndex = props.tabs.findIndex((tab) => tab.id === props.activeTabId)
  return activeIndex < 0 ? [] : props.tabs.slice(activeIndex + 1)
})

const contextTabsToRight = computed(() => {
  const contextTabId = tabContextMenu.value?.tab?.id
  const tabIndex = props.tabs.findIndex((tab) => tab.id === contextTabId)
  return tabIndex < 0 ? [] : props.tabs.slice(tabIndex + 1)
})

const tabContextMenuStyle = computed(() => {
  if (!tabContextMenu.value) return {}
  return {
    left: `${tabContextMenu.value.x}px`,
    top: `${tabContextMenu.value.y}px`,
    visibility: tabContextMenu.value.positioned ? 'visible' : 'hidden',
  }
})

watch(
  () => [props.activeTabId, props.tabs.map((tab) => `${tab.id}:${tab.title || ''}`).join('|')],
  async () => {
    await nextTick()
    updateOverflow()
    scrollActiveTabIntoView()
    syncActiveSelection()
  },
  { flush: 'post' }
)

watch(managerOpen, (open) => {
  if (!open) searchQuery.value = ''
})

onMounted(async () => {
  await nextTick()
  if (typeof ResizeObserver === 'function' && tabsContainer.value) {
    resizeObserver = new ResizeObserver(syncTabLayout)
    resizeObserver.observe(tabsContainer.value)
  } else {
    window.addEventListener('resize', syncTabLayout)
  }
  updateOverflow()
  scrollActiveTabIntoView()
  syncActiveSelection()
  window.addEventListener('pointerdown', closeTabContextMenuOnPointerdown)
  window.addEventListener('keydown', closeTabContextMenuOnEscape)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  tabRefs.clear()
  window.removeEventListener('resize', syncTabLayout)
  window.removeEventListener('pointerdown', closeTabContextMenuOnPointerdown)
  window.removeEventListener('keydown', closeTabContextMenuOnEscape)
})

function setTabRef(tabId, element) {
  if (element) tabRefs.set(tabId, element)
  else tabRefs.delete(tabId)
}

function updateOverflow() {
  const container = tabsContainer.value
  if (!container) {
    overflowing.value = false
    canScrollLeft.value = false
    canScrollRight.value = false
    return
  }
  const maximumScroll = Math.max(0, container.scrollWidth - container.clientWidth)
  overflowing.value = maximumScroll > 1
  canScrollLeft.value = container.scrollLeft > 1
  canScrollRight.value = container.scrollLeft < maximumScroll - 1
}

function syncTabLayout() {
  updateOverflow()
  syncActiveSelection()
}

function syncActiveSelection() {
  const activeTab = tabRefs.get(props.activeTabId)
  if (!tabsContainer.value || !activeTab) {
    activeSelectionReady.value = false
    return
  }
  activeSelectionStyle.value = {
    width: `${Math.max(0, activeTab.offsetWidth - 6)}px`,
    transform: `translate3d(${activeTab.offsetLeft + 3}px, 0, 0)`,
  }
  activeSelectionReady.value = true
}

function scrollActiveTabIntoView() {
  const container = tabsContainer.value
  const activeTab = tabRefs.get(props.activeTabId)
  if (!container || !activeTab) return
  const tabLeft = activeTab.offsetLeft
  const tabRight = tabLeft + activeTab.offsetWidth
  const visibleLeft = container.scrollLeft
  const visibleRight = visibleLeft + container.clientWidth
  if (tabLeft < visibleLeft) container.scrollLeft = tabLeft
  else if (tabRight > visibleRight) container.scrollLeft = tabRight - container.clientWidth
  updateOverflow()
}

function handleWheel(event) {
  const container = tabsContainer.value
  if (!container || !overflowing.value || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
  event.preventDefault()
  container.scrollLeft += event.deltaY
  updateOverflow()
}

function scrollTabs(direction) {
  const container = tabsContainer.value
  if (!container) return
  container.scrollLeft += direction * Math.max(160, Math.round(container.clientWidth * 0.62))
  updateOverflow()
}

function activateFromManager(tabId) {
  emit('activate', tabId)
  managerOpen.value = false
}

function closeOtherTabs() {
  emit('close-tabs', props.tabs.filter((tab) => tab.id !== props.activeTabId).map((tab) => tab.id))
  managerOpen.value = false
}

function closeTabsToRight() {
  emit('close-tabs', tabsToRight.value.map((tab) => tab.id))
  managerOpen.value = false
}

function closeAllTabs() {
  emit('close-tabs', props.tabs.map((tab) => tab.id))
  managerOpen.value = false
}

function openTabContextMenu(event, tab) {
  event.preventDefault()
  emit('activate', tab.id)
  tabContextMenu.value = {
    tab,
    x: event.clientX,
    y: event.clientY,
    positioned: false,
  }
  nextTick(positionTabContextMenu)
}

function positionTabContextMenu() {
  const menu = tabContextMenu.value
  const element = tabContextMenuRef.value
  if (!menu || !element) return
  const margin = 8
  tabContextMenu.value = {
    ...menu,
    x: Math.max(margin, Math.min(menu.x, window.innerWidth - element.offsetWidth - margin)),
    y: Math.max(margin, Math.min(menu.y, window.innerHeight - element.offsetHeight - margin)),
    positioned: true,
  }
  nextTick(() => tabContextMenuRef.value?.querySelector('[role="menuitem"]:not(:disabled)')?.focus())
}

function closeTabContextMenu() {
  tabContextMenu.value = null
}

function closeTabContextMenuOnPointerdown(event) {
  if (!tabContextMenu.value || tabContextMenuRef.value?.contains(event.target)) return
  closeTabContextMenu()
}

function closeTabContextMenuOnEscape(event) {
  if (event.key !== 'Escape' || !tabContextMenu.value) return
  event.preventDefault()
  closeTabContextMenu()
}

function closeContextTab() {
  const tabId = tabContextMenu.value?.tab?.id
  closeTabContextMenu()
  if (tabId) emit('close', tabId)
}

function closeOtherContextTabs() {
  const tabId = tabContextMenu.value?.tab?.id
  closeTabContextMenu()
  if (tabId) emit('close-tabs', props.tabs.filter((tab) => tab.id !== tabId).map((tab) => tab.id))
}

function closeContextTabsToRight() {
  const tabIds = contextTabsToRight.value.map((tab) => tab.id)
  closeTabContextMenu()
  if (tabIds.length) emit('close-tabs', tabIds)
}

function revealContextTab() {
  const tab = tabContextMenu.value?.tab
  closeTabContextMenu()
  if (tab) emit('reveal-tab', tab)
}

function deleteContextTab() {
  const tab = tabContextMenu.value?.tab
  closeTabContextMenu()
  if (tab) emit('delete-tab', tab)
}

function handleTabContextMenuKeydown(event) {
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End']
  if (!keys.includes(event.key)) return
  const menuItems = Array.from(tabContextMenuRef.value?.querySelectorAll('[role="menuitem"]:not(:disabled)') || [])
  if (!menuItems.length) return
  event.preventDefault()
  const currentIndex = menuItems.indexOf(document.activeElement)
  const nextIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? menuItems.length - 1
      : event.key === 'ArrowUp'
        ? (currentIndex - 1 + menuItems.length) % menuItems.length
        : (currentIndex + 1) % menuItems.length
  menuItems[nextIndex].focus()
}

function handleTablistKeydown(event) {
  if (event.target?.getAttribute('role') !== 'tab') return
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
  if (!keys.includes(event.key) || !props.tabs.length) return
  event.preventDefault()
  const currentIndex = Math.max(0, props.tabs.findIndex((tab) => tab.id === props.activeTabId))
  const nextIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? props.tabs.length - 1
      : event.key === 'ArrowLeft'
        ? (currentIndex - 1 + props.tabs.length) % props.tabs.length
        : (currentIndex + 1) % props.tabs.length
  const nextTab = props.tabs[nextIndex]
  emit('activate', nextTab.id)
  nextTick(() => tabRefs.get(nextTab.id)?.querySelector('[role="tab"]')?.focus())
}
</script>

<style scoped>
.workspace-tabs-shell {
  position: relative;
  z-index: 8;
  grid-row: 1;
  height: 36px;
  min-width: 0;
  min-height: 36px;
  display: flex;
  overflow: hidden;
  background: transparent;
}

.workspace-tabs {
  position: relative;
  min-width: 0;
  min-height: 36px;
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.workspace-tabs::-webkit-scrollbar { display: none; }

.workspace-tab-selection {
  position: absolute;
  top: 4px;
  left: 0;
  z-index: 0;
  height: 28px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 68%, var(--vk-bg-panel));
  border-radius: 8px;
  background: color-mix(in srgb, var(--vk-bg-panel) 82%, var(--vk-bg-hover));
  box-shadow: none;
  opacity: 0;
  pointer-events: none;
  transform-origin: center;
  transition:
    transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1),
    width 220ms cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 120ms ease-out;
  will-change: transform, width;
}

.workspace-tab-selection.is-ready { opacity: 1; }

.workspace-tab-item {
  position: relative;
  z-index: 1;
  max-width: 240px;
  min-width: 72px;
  height: 28px;
  flex: 0 1 180px;
}

.workspace-tab {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 10px;
  border: 0;
  background: transparent;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-regular);
  text-align: left;
  cursor: pointer;
}

.workspace-tab-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: clip;
  -webkit-mask-image: linear-gradient(to right, #000 0, #000 calc(100% - 14px), transparent 100%);
  mask-image: linear-gradient(to right, #000 0, #000 calc(100% - 14px), transparent 100%);
}

.workspace-tab:hover > .workspace-tab-label,
.workspace-tab:focus-visible > .workspace-tab-label,
.workspace-tab.active > .workspace-tab-label {
  -webkit-mask-image: linear-gradient(to right, #000 0, #000 calc(100% - 32px), transparent calc(100% - 20px));
  mask-image: linear-gradient(to right, #000 0, #000 calc(100% - 32px), transparent calc(100% - 20px));
}

.workspace-tab-dirty {
  display: block;
  width: 5px;
  min-width: 5px;
  max-width: 5px;
  height: 5px;
  flex: 0 0 5px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--vk-warning);
}

.workspace-tab.active,
.workspace-tab:hover { color: var(--vk-text); }
.workspace-tab.active { font-weight: var(--vk-weight-strong); }

.workspace-tab:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--vk-accent-strong) 38%, transparent);
}

.workspace-tab-close {
  position: absolute;
  top: 50%;
  right: 5px;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--vk-muted);
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  transition: none;
}

.workspace-tab-item:focus-within .workspace-tab-close,
.workspace-tab-item.active .workspace-tab-close {
  opacity: 0.78;
  pointer-events: auto;
}

@media (hover: hover) and (pointer: fine) {
  .workspace-tab-item:hover .workspace-tab-close {
    opacity: 0.78;
    pointer-events: auto;
  }
}

.workspace-tab-close:hover {
  color: var(--vk-text);
  background: color-mix(in srgb, var(--vk-muted) 12%, var(--vk-bg-center));
}

.workspace-tabs-controls {
  flex: 0 0 auto;
  height: 36px;
  display: inline-flex;
  align-items: center;
  padding: 0 4px 0 3px;
  background: var(--vk-bg-center);
}

.workspace-tabs-control {
  width: 23px;
  height: 28px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: color-mix(in srgb, var(--vk-muted) 78%, transparent);
  cursor: pointer;
}

.workspace-tabs-control:hover:not(:disabled),
.workspace-tabs-control:focus-visible {
  background: color-mix(in srgb, var(--vk-bg-hover) 70%, transparent);
  color: var(--vk-text);
}

.workspace-tabs-control:disabled { opacity: 0.24; cursor: default; }
.workspace-tabs-manager-button { margin-left: 1px; }

.workspace-tab-manager { min-width: 0; display: grid; gap: 8px; }

.workspace-tab-manager-search {
  height: 32px;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: center;
  gap: 5px;
  padding: 0 9px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 86%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--vk-bg-panel) 92%, transparent);
  color: var(--vk-muted);
}

.workspace-tab-manager-search input {
  min-width: 0;
  width: 100%;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
}

.workspace-tab-manager-search input::placeholder {
  color: color-mix(in srgb, var(--vk-muted) 74%, transparent);
}

.workspace-tab-manager-list {
  max-height: min(340px, 56vh);
  min-height: 36px;
  display: grid;
  align-content: start;
  gap: 2px;
  overflow-y: auto;
}

.workspace-tab-manager-row {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 26px;
  align-items: center;
  border-radius: 7px;
}

.workspace-tab-manager-row:hover { background: color-mix(in srgb, var(--vk-bg-hover) 72%, transparent); }
.workspace-tab-manager-row.active { background: color-mix(in srgb, var(--vk-accent) 10%, transparent); }

.workspace-tab-manager-select,
.workspace-tab-manager-close {
  border: 0;
  background: transparent;
  color: var(--vk-text);
  cursor: pointer;
}

.workspace-tab-manager-select {
  min-width: 0;
  height: 31px;
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  padding: 0 5px 0 8px;
  text-align: left;
}

.workspace-tab-manager-select > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-tab-manager-indicator {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: transparent;
}

.workspace-tab-manager-row.active .workspace-tab-manager-indicator { background: var(--vk-accent-strong); }

.workspace-tab-manager-close {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  padding: 0;
  border-radius: 6px;
  color: var(--vk-muted);
  opacity: 0;
  visibility: hidden;
  transition: none;
}

.workspace-tab-manager-row.active .workspace-tab-manager-close,
.workspace-tab-manager-close:focus-visible {
  opacity: 0.72;
  visibility: visible;
}

@media (hover: hover) and (pointer: fine) {
  .workspace-tab-manager-row:hover .workspace-tab-manager-close {
    opacity: 0.72;
    visibility: visible;
  }
}

.workspace-tab-manager-close:hover {
  background: color-mix(in srgb, var(--vk-border) 36%, transparent);
  color: var(--vk-text);
  opacity: 1;
}

.workspace-tab-manager-empty {
  min-height: 56px;
  display: grid;
  place-items: center;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
}

.workspace-tab-manager-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
}

.workspace-tab-manager-actions button {
  min-height: 26px;
  padding: 0 8px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  font-size: var(--vk-type-meta-size);
  cursor: pointer;
}

.workspace-tab-manager-actions button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--vk-bg-hover) 74%, transparent);
  color: var(--vk-text);
}

.workspace-tab-manager-actions button:disabled { opacity: 0.34; cursor: default; }

:global(.workspace-tab-manager-popover.el-popper) {
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 84%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--vk-bg-panel) 97%, transparent);
  backdrop-filter: blur(18px) saturate(1.06);
  -webkit-backdrop-filter: blur(18px) saturate(1.06);
  box-shadow: 0 16px 38px color-mix(in srgb, var(--vk-text) 14%, transparent);
}

@media (prefers-reduced-motion: reduce) {
  .workspace-tab-selection {
    transition: opacity 120ms ease-out;
    will-change: auto;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .workspace-tab-selection {
    background: var(--vk-bg-panel);
  }

  :global(.workspace-tab-manager-popover.el-popper) {
    background: var(--vk-bg-panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
  :global(.workspace-tab-manager-popover.el-popper) {
    border-color: color-mix(in srgb, var(--vk-text) 46%, var(--vk-border));
    background: var(--vk-bg-panel);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

.workspace-tab-context-menu {
  position: fixed;
  z-index: 3200;
  min-width: 178px;
  padding: 5px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 88%, transparent);
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-bg-panel) 96%, white);
  box-shadow: 0 12px 28px color-mix(in srgb, var(--vk-text) 14%, transparent);
}

.workspace-tab-context-menu-item {
  width: 100%;
  min-height: 30px;
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.workspace-tab-context-menu-item:hover:not(:disabled),
.workspace-tab-context-menu-item:focus-visible {
  outline: 0;
  background: color-mix(in srgb, var(--vk-bg-hover) 80%, transparent);
}

.workspace-tab-context-menu-item:disabled {
  opacity: 0.42;
  cursor: default;
}

.workspace-tab-context-menu-separator {
  height: 1px;
  margin: 4px 3px;
  background: color-mix(in srgb, var(--vk-border) 76%, transparent);
}

.workspace-tab-context-menu-item.danger { color: var(--vk-danger); }
.workspace-tab-context-menu-item.danger:hover,
.workspace-tab-context-menu-item.danger:focus-visible { background: color-mix(in srgb, var(--vk-danger) 8%, transparent); }
</style>
