<template>
  <Teleport to="body">
    <Transition name="sidebar-context-menu">
      <div
        v-if="menu"
        ref="menuRef"
        class="sidebar-context-menu"
        :style="menuStyle"
        role="menu"
        :aria-label="menu.node?.name ? `${menu.node.name} 操作菜单` : '文件树菜单'"
        @pointerdown.stop
        @contextmenu.prevent
        @keydown="handleKeydown"
      >
        <button
          v-if="menu.kind === 'blank'"
          type="button"
          role="menuitem"
          class="sidebar-context-menu-item"
          @click="select('create-separator')"
        >
          <span class="sidebar-context-menu-divider-icon" aria-hidden="true"></span>
          <span>新建分割线</span>
        </button>
        <button
          v-else-if="menu.node?.type === 'user-group-separator'"
          type="button"
          role="menuitem"
          class="sidebar-context-menu-item is-danger"
          @click="select('delete-separator')"
        >
          <SvgMaskIcon :src="trashIcon" :size="16" />
          <span>删除分割线</span>
        </button>
        <template v-else>
          <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="select('reveal')">
            <SvgMaskIcon :src="finderIcon" :size="16" />
            <span>在 Finder 中显示</span>
          </button>
          <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="select('rename')">
            <SvgMaskIcon :src="highlighterIcon" :size="16" />
            <span>{{ menu.node?.type === 'folder' ? '编辑文件夹名称' : '编辑文件名' }}</span>
          </button>
          <button
            v-if="menu.node?.type === 'folder'"
            type="button"
            role="menuitem"
            class="sidebar-context-menu-item"
            @click="select('toggle-pin')"
          >
            <SvgMaskIcon :src="folderPinIcon" :size="16" />
            <span>{{ menu.node.raw?.is_pinned ? '取消置顶文件夹' : '置顶文件夹' }}</span>
          </button>
          <template v-if="isContentNode">
            <div class="sidebar-context-menu-separator" role="separator"></div>
            <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="select('set-viewed', true)">
              <SvgMaskIcon :src="markReadIcon" :size="16" />
              <span>标记为已读</span>
            </button>
            <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="select('set-viewed', false)">
              <SvgMaskIcon :src="markUnreadIcon" :size="16" />
              <span>标记为未读</span>
            </button>
          </template>
          <div class="sidebar-context-menu-separator" role="separator"></div>
          <button type="button" role="menuitem" class="sidebar-context-menu-item is-danger" @click="select('delete')">
            <SvgMaskIcon :src="trashIcon" :size="16" />
            <span>{{ menu.node?.type === 'folder' ? '删除文件夹' : '删除文件' }}</span>
          </button>
        </template>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'

const trashIcon = 'trash'
const finderIcon = 'finder'
const highlighterIcon = 'highlighter'
const folderPinIcon = 'arrow.up.to.line'
const markReadIcon = 'checkmark.circle'
const markUnreadIcon = 'x.circle'

const props = defineProps({
  menu: { type: Object, default: null },
})
const emit = defineEmits(['close', 'select'])
const menuRef = ref(null)
const position = ref({ x: Number(props.menu?.x || 0), y: Number(props.menu?.y || 0), ready: false })
const isContentNode = computed(() => ['content', 'unread-content'].includes(props.menu?.node?.type))
const menuStyle = computed(() => ({
  left: `${position.value.x}px`,
  top: `${position.value.y}px`,
  visibility: position.value.ready ? 'visible' : 'hidden',
}))

function positionAndFocus() {
  const element = menuRef.value
  if (!props.menu || !element) return
  const margin = 8
  position.value = {
    x: Math.max(margin, Math.min(Number(props.menu.x || 0), window.innerWidth - element.offsetWidth - margin)),
    y: Math.max(margin, Math.min(Number(props.menu.y || 0), window.innerHeight - element.offsetHeight - margin)),
    ready: true,
  }
  nextTick(() => element.querySelector('[role="menuitem"]:not(:disabled)')?.focus())
}

function select(id, payload = null) {
  emit('select', { id, payload })
}

function close({ restoreFocus = false } = {}) {
  emit('close', { restoreFocus })
}

function handleWindowKeydown(event) {
  if (!props.menu || event.key !== 'Escape') return
  event.preventDefault()
  close({ restoreFocus: true })
}

function handleKeydown(event) {
  if (event.key === 'Tab') {
    event.preventDefault()
    close({ restoreFocus: true })
    return
  }
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End']
  if (!keys.includes(event.key)) return
  const items = Array.from(menuRef.value?.querySelectorAll('[role="menuitem"]:not(:disabled)') || [])
  if (!items.length) return
  event.preventDefault()
  const focusedIndex = items.indexOf(document.activeElement)
  const currentIndex = focusedIndex >= 0 ? focusedIndex : 0
  let nextIndex = currentIndex
  if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % items.length
  if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + items.length) % items.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = items.length - 1
  items[nextIndex]?.focus()
}

function handleWindowPointerDown() {
  if (props.menu) close()
}

watch(
  () => [props.menu?.x, props.menu?.y, props.menu?.kind, props.menu?.node?.id],
  () => {
    position.value = { x: Number(props.menu?.x || 0), y: Number(props.menu?.y || 0), ready: false }
    if (props.menu) nextTick(positionAndFocus)
  },
)

onMounted(() => {
  window.addEventListener('pointerdown', handleWindowPointerDown)
  window.addEventListener('keydown', handleWindowKeydown)
  if (props.menu) nextTick(positionAndFocus)
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', handleWindowPointerDown)
  window.removeEventListener('keydown', handleWindowKeydown)
})
</script>

<style scoped>
.sidebar-context-menu {
  position: fixed;
  z-index: 3200;
  display: grid;
  width: max-content;
  min-width: 196px;
  max-width: min(280px, calc(100vw - 16px));
  padding: 5px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
  transform-origin: top left;
}

.sidebar-context-menu-item {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  align-items: center;
  min-height: 32px;
  gap: var(--vk-space-control);
  width: 100%;
  padding: 0 9px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.sidebar-context-menu-item > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-context-menu-item :deep(.svg-mask-icon) { opacity: .72; }

.sidebar-context-menu-item:hover,
.sidebar-context-menu-item:focus-visible {
  outline: none;
  background: color-mix(in srgb, var(--vk-bg-hover) 78%, var(--vk-bg-panel));
}

.sidebar-context-menu-item:hover :deep(.svg-mask-icon),
.sidebar-context-menu-item:focus-visible :deep(.svg-mask-icon) { opacity: 1; }

.sidebar-context-menu-item.is-danger { color: var(--vk-danger, var(--vk-error-text)); }

.sidebar-context-menu-item.is-danger:hover,
.sidebar-context-menu-item.is-danger:focus-visible {
  background: color-mix(in srgb, var(--vk-danger, var(--vk-error-text)) 8%, var(--vk-bg-panel));
}

.sidebar-context-menu-separator {
  height: 1px;
  margin: 5px 4px;
  background: color-mix(in srgb, var(--vk-border) 72%, transparent);
}

.sidebar-context-menu-divider-icon {
  position: relative;
  display: block;
  width: 16px;
  height: 16px;
}

.sidebar-context-menu-divider-icon::after {
  position: absolute;
  top: 50%;
  right: 1px;
  left: 1px;
  height: 1px;
  background: currentColor;
  content: '';
  opacity: .66;
}

.sidebar-context-menu-enter-active,
.sidebar-context-menu-leave-active {
  transition: opacity 120ms var(--vk-ease-out), transform 120ms var(--vk-ease-out);
}

.sidebar-context-menu-enter-from,
.sidebar-context-menu-leave-to {
  opacity: 0;
  transform: scale(0.97);
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-context-menu-enter-active,
  .sidebar-context-menu-leave-active { transition: opacity var(--vk-motion-fast) ease; }

  .sidebar-context-menu-enter-from,
  .sidebar-context-menu-leave-to { transform: none; }
}

</style>
