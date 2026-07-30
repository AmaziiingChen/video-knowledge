<template>
  <div class="knowledge-shell">
    <ActivityBar
      :active-view="activeView"
      :items="ribbonItems"
      @update:active-view="$emit('update:activeView', $event)"
      @open-settings="$emit('open-settings')"
    />

    <div ref="workspaceFrame" class="workspace-frame">
      <div v-if="activeView === 'wechat' || activeView === 'campus' || activeView === 'creator' || activeView === 'reports'" class="workspace-single-pane">
        <slot name="editor" />
      </div>
      <template v-else>
        <splitpanes
          class="workspace-panes"
          :class="{
            'pointer-resizing': pointerResizing,
            'is-snap-animating': paneSnapAnimating,
            'primary-pane-collapsed': !showPrimaryPane,
            'context-pane-collapsed': !showContextPane,
          }"
          @resized="handleResized"
          @pointerdown.capture="beginSplitterDrag"
          @keydown.capture="handleSplitterKeydown"
        >
          <pane
            :size="showPrimaryPane ? workspaceLayout.primary : 0"
            :min-size="showPrimaryPane ? snapMinSize : 0"
            :max-size="showPrimaryPane ? 45 : 0"
          >
            <aside
              class="primary-sidebar-shell"
              :class="{ 'primary-sidebar-hidden': !showPrimaryPane }"
              aria-label="左侧栏"
              :aria-hidden="!showPrimaryPane"
            >
              <slot name="primary" />
            </aside>
          </pane>

          <pane :size="editorPaneSize" :min-size="showContextPane ? editorMinSize : 50">
            <slot name="editor" />
          </pane>

          <pane
            :size="showContextPane ? workspaceLayout.context : 0"
            :min-size="showContextPane ? snapMinSize : 0"
            :max-size="showContextPane ? 65 : 0"
          >
            <aside
              class="context-sidebar"
              :class="{ 'context-sidebar-hidden': !showContextPane }"
              aria-label="AI 助手"
              :aria-hidden="!showContextPane"
            >
              <slot name="context" />
            </aside>
          </pane>
        </splitpanes>
        <div
          v-if="!showPrimaryPane"
          class="collapsed-pane-handle left"
          :class="{ 'is-revealing': collapsedPaneReveal.side === 'primary' && collapsedPaneReveal.progress > 0 }"
          :style="collapsedPaneRevealStyle('primary')"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          aria-label="拖拽展开左侧栏"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="collapsedPaneRevealValue('primary')"
          @pointerdown="beginCollapsedPaneDrag($event, 'primary')"
          @keydown="handleCollapsedPaneKeydown($event, 'primary')"
        ></div>
        <div
          v-if="!showContextPane"
          class="collapsed-pane-handle right"
          :class="{ 'is-revealing': collapsedPaneReveal.side === 'context' && collapsedPaneReveal.progress > 0 }"
          :style="collapsedPaneRevealStyle('context')"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          aria-label="拖拽展开右侧栏"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="collapsedPaneRevealValue('context')"
          @pointerdown="beginCollapsedPaneDrag($event, 'context')"
          @keydown="handleCollapsedPaneKeydown($event, 'context')"
        ></div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Splitpanes, Pane } from 'splitpanes'
import 'splitpanes/dist/splitpanes.css'
import ActivityBar from './ActivityBar.vue'
import {
  COLLAPSED_PANE_REVEAL_DISTANCE,
  resolvePaneDragTransition,
  revealProgressForDistance,
} from './splitterDragState.js'

const props = defineProps({
  activeView: {
    type: String,
    required: true
  },
  ribbonItems: {
    type: Array,
    required: true
  },
  workspaceLayout: {
    type: Object,
    required: true
  },
  editorPaneSize: {
    type: Number,
    required: true
  },
  showPrimaryPane: {
    type: Boolean,
    required: true
  },
  showContextPane: {
    type: Boolean,
    required: true
  }
})

const emit = defineEmits([
  'update:activeView',
  'open-settings',
  'resized',
  'snap-collapse',
  'snap-open',
  'pane-drag-resize'
])

const workspaceFrame = ref(null)
const paneWidth = ref(1200)
const pointerResizing = ref(false)
const paneSnapAnimating = ref(false)
const collapsedPaneReveal = ref({ side: '', progress: 0 })
const MIN_PANE_WIDTH = 200
let splitterDrag = null
let collapsedPaneDrag = null
let splitterResizeFrame = 0
let paneSnapAnimationTimer = 0

const snapMinSize = computed(() => paneSizePercent(24))
const editorMinSize = computed(() => paneSizePercent(320))

onMounted(() => {
  updatePaneWidth()
  window.addEventListener('resize', updatePaneWidth)
  void nextTick(syncSplitterAccessibility)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updatePaneWidth)
  stopSplitterDrag()
  stopCollapsedPaneDrag()
  stopPaneSnapAnimation()
})

function paneSizePercent(width) {
  return Math.min(80, Math.max(1, (width / Math.max(1, paneWidth.value)) * 100))
}

function updatePaneWidth() {
  paneWidth.value = workspaceFrame.value?.clientWidth || window.innerWidth || 1200
  syncSplitterAccessibility()
}

function splitterDefinition(index) {
  if (index === 0) {
    return {
      side: 'primary',
      label: '调整左侧栏宽度',
      min: 8,
      max: 45,
      value: props.showPrimaryPane ? props.workspaceLayout.primary : 0,
    }
  }
  return {
    side: 'context',
    label: '调整右侧栏宽度',
    min: 12,
    max: 65,
    value: props.showContextPane ? props.workspaceLayout.context : 0,
  }
}

function syncSplitterAccessibility() {
  const splitters = workspaceFrame.value?.querySelectorAll?.('.splitpanes__splitter') || []
  splitters.forEach((splitter, index) => {
    const definition = splitterDefinition(index)
    const disabled = (definition.side === 'primary' && !props.showPrimaryPane)
      || (definition.side === 'context' && !props.showContextPane)
    splitter.setAttribute('role', 'separator')
    splitter.setAttribute('aria-orientation', 'vertical')
    splitter.setAttribute('aria-label', definition.label)
    splitter.setAttribute('aria-valuemin', String(definition.min))
    splitter.setAttribute('aria-valuemax', String(definition.max))
    splitter.setAttribute('aria-valuenow', String(Math.round(definition.value)))
    splitter.setAttribute('aria-disabled', String(disabled))
    splitter.tabIndex = disabled ? -1 : 0
  })
}

function handleSplitterKeydown(event) {
  const splitter = event.target.closest?.('.splitpanes__splitter')
  if (!splitter || !workspaceFrame.value) return
  const splitters = [...workspaceFrame.value.querySelectorAll('.splitpanes__splitter')]
  const index = splitters.indexOf(splitter)
  if (index < 0) return
  const definition = splitterDefinition(index)
  const isHidden = (definition.side === 'primary' && !props.showPrimaryPane)
    || (definition.side === 'context' && !props.showContextPane)
  if (isHidden) return

  const step = event.shiftKey ? 8 : 2
  let next = definition.value
  if (event.key === 'Home') next = definition.min
  else if (event.key === 'End') next = definition.max
  else if (definition.side === 'primary' && event.key === 'ArrowLeft') next -= step
  else if (definition.side === 'primary' && event.key === 'ArrowRight') next += step
  else if (definition.side === 'context' && event.key === 'ArrowLeft') next += step
  else if (definition.side === 'context' && event.key === 'ArrowRight') next -= step
  else return

  event.preventDefault()
  event.stopPropagation()
  const oppositeSize = definition.side === 'primary'
    ? (props.showContextPane ? props.workspaceLayout.context : 0)
    : (props.showPrimaryPane ? props.workspaceLayout.primary : 0)
  const max = Math.min(definition.max, 82 - oppositeSize)
  emit('pane-drag-resize', { side: definition.side, size: Math.max(definition.min, Math.min(max, next)) })
}

function beginSplitterDrag(event) {
  const splitter = event.target.closest?.('.splitpanes__splitter')
  if (!splitter || !workspaceFrame.value) return
  const splitters = [...workspaceFrame.value.querySelectorAll('.splitpanes__splitter')]
  const index = splitters.indexOf(splitter)
  if (index < 0) return
  event.preventDefault()
  event.stopPropagation()
  stopSplitterDrag()
  stopPaneSnapAnimation()
  lockTextSelection()
  pointerResizing.value = true
  splitter.classList.add('is-active-splitter')
  splitter.setPointerCapture?.(event.pointerId)
  splitterDrag = {
    side: index === 0 ? 'primary' : 'context',
    pointerId: event.pointerId,
    collapsed: false,
    targetWidth: null,
    element: splitter
  }
  window.addEventListener('pointermove', trackSplitterDrag)
  window.addEventListener('pointerup', stopSplitterDrag)
  window.addEventListener('pointercancel', stopSplitterDrag)
}

function trackSplitterDrag(event) {
  if (!splitterDrag || !workspaceFrame.value || event.pointerId !== splitterDrag.pointerId) return
  event.preventDefault()
  const rect = workspaceFrame.value.getBoundingClientRect()
  const targetWidth = splitterDrag.side === 'primary'
    ? event.clientX - rect.left
    : rect.right - event.clientX
  splitterDrag.targetWidth = targetWidth
  const transition = resolvePaneDragTransition(splitterDrag, targetWidth)
  splitterDrag.collapsed = transition.collapsed

  if (transition.action === 'open') {
    startPaneSnapAnimation()
    emit('snap-open', splitterDrag.side)
    schedulePointerResize(splitterDrag.side, targetWidth, rect.width)
    return
  }

  if (transition.action === 'collapse') {
    startPaneSnapAnimation()
    splitterDrag.pendingResize = null
    if (splitterResizeFrame) {
      window.cancelAnimationFrame(splitterResizeFrame)
      splitterResizeFrame = 0
    }
    emit('snap-collapse', splitterDrag.side)
    return
  }

  if (transition.action === 'resize') {
    stopPaneSnapAnimation()
    schedulePointerResize(splitterDrag.side, targetWidth, rect.width)
  }
}

function startPaneSnapAnimation() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  if (paneSnapAnimationTimer) window.clearTimeout(paneSnapAnimationTimer)
  paneSnapAnimating.value = true
  paneSnapAnimationTimer = window.setTimeout(() => {
    paneSnapAnimationTimer = 0
    paneSnapAnimating.value = false
  }, 220)
}

function stopPaneSnapAnimation() {
  if (paneSnapAnimationTimer) {
    window.clearTimeout(paneSnapAnimationTimer)
    paneSnapAnimationTimer = 0
  }
  paneSnapAnimating.value = false
}

function pointerResizePayload(side, targetWidth, frameWidth) {
  const size = (Math.max(0, targetWidth) / Math.max(1, frameWidth)) * 100
  return { side, size }
}

function schedulePointerResize(side, targetWidth, frameWidth) {
  if (!splitterDrag) return
  splitterDrag.pendingResize = pointerResizePayload(side, targetWidth, frameWidth)
  if (splitterResizeFrame) return
  splitterResizeFrame = window.requestAnimationFrame(flushPointerResize)
}

function flushPointerResize() {
  splitterResizeFrame = 0
  const pendingResize = splitterDrag?.pendingResize
  if (!pendingResize) return
  splitterDrag.pendingResize = null
  applyPaneResizeDirectly(pendingResize)
}

function applyPaneResizeDirectly({ side, size }) {
  const panes = workspaceFrame.value?.querySelectorAll('.workspace-panes > .splitpanes__pane')
  if (!panes || panes.length < 3) return

  const fixedPrimary = props.showPrimaryPane ? props.workspaceLayout.primary : 0
  const fixedContext = props.showContextPane ? props.workspaceLayout.context : 0
  const primary = side === 'primary'
    ? Math.max(8, Math.min(45, 82 - fixedContext, size))
    : fixedPrimary
  const context = side === 'context'
    ? Math.max(12, Math.min(65, 82 - fixedPrimary, size))
    : fixedContext
  const editor = Math.max(18, 100 - primary - context)

  panes[0].style.width = `${primary}%`
  panes[1].style.width = `${editor}%`
  panes[2].style.width = `${context}%`
}

function stopSplitterDrag(event) {
  if (event?.pointerId !== undefined && splitterDrag && event.pointerId !== splitterDrag.pointerId) return
  window.removeEventListener('pointermove', trackSplitterDrag)
  window.removeEventListener('pointerup', stopSplitterDrag)
  window.removeEventListener('pointercancel', stopSplitterDrag)
  unlockTextSelection()
  pointerResizing.value = false
  splitterDrag?.element?.classList.remove('is-active-splitter')
  if (splitterDrag?.element?.hasPointerCapture?.(splitterDrag.pointerId)) {
    splitterDrag.element.releasePointerCapture?.(splitterDrag.pointerId)
  }
  if (splitterResizeFrame) {
    window.cancelAnimationFrame(splitterResizeFrame)
    splitterResizeFrame = 0
  }
  flushPointerResize()
  let finalTargetWidth = splitterDrag?.targetWidth
  if (splitterDrag && !splitterDrag.collapsed && finalTargetWidth !== null && finalTargetWidth < MIN_PANE_WIDTH) {
    emit('snap-open', splitterDrag.side)
    finalTargetWidth = MIN_PANE_WIDTH
  }
  if (splitterDrag && !splitterDrag.collapsed && finalTargetWidth !== null && workspaceFrame.value) {
    const rect = workspaceFrame.value.getBoundingClientRect()
    emit('pane-drag-resize', pointerResizePayload(splitterDrag.side, finalTargetWidth, rect.width))
  }
  splitterDrag = null
}

function handleResized(payload) {
  emit('resized', payload)
  void nextTick(syncSplitterAccessibility)
}

watch(
  () => [
    props.workspaceLayout.primary,
    props.workspaceLayout.context,
    props.showPrimaryPane,
    props.showContextPane,
  ],
  () => void nextTick(syncSplitterAccessibility),
)

function beginCollapsedPaneDrag(event, side) {
  event.preventDefault()
  stopCollapsedPaneDrag()
  lockTextSelection()
  collapsedPaneDrag = {
    side,
    startX: event.clientX,
    pointerId: event.pointerId,
    distance: 0,
    element: event.currentTarget,
  }
  collapsedPaneReveal.value = { side, progress: 0 }
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', trackCollapsedPaneDrag)
  window.addEventListener('pointerup', stopCollapsedPaneDrag)
  window.addEventListener('pointercancel', stopCollapsedPaneDrag)
}

function trackCollapsedPaneDrag(event) {
  if (!collapsedPaneDrag || event.pointerId !== collapsedPaneDrag.pointerId) return
  event.preventDefault()
  const delta = collapsedPaneDrag.side === 'primary'
    ? event.clientX - collapsedPaneDrag.startX
    : collapsedPaneDrag.startX - event.clientX
  collapsedPaneDrag.distance = Math.max(0, delta)
  collapsedPaneReveal.value = {
    side: collapsedPaneDrag.side,
    progress: revealProgressForDistance(collapsedPaneDrag.distance),
  }
}

function stopCollapsedPaneDrag(event) {
  if (event?.pointerId !== undefined && collapsedPaneDrag && event.pointerId !== collapsedPaneDrag.pointerId) return
  const side = collapsedPaneDrag?.side
  const shouldOpen = event?.type === 'pointerup'
    && collapsedPaneDrag?.distance >= COLLAPSED_PANE_REVEAL_DISTANCE
  window.removeEventListener('pointermove', trackCollapsedPaneDrag)
  window.removeEventListener('pointerup', stopCollapsedPaneDrag)
  window.removeEventListener('pointercancel', stopCollapsedPaneDrag)
  if (collapsedPaneDrag?.element?.hasPointerCapture?.(collapsedPaneDrag.pointerId)) {
    collapsedPaneDrag.element.releasePointerCapture?.(collapsedPaneDrag.pointerId)
  }
  unlockTextSelection()
  collapsedPaneDrag = null
  collapsedPaneReveal.value = { side: '', progress: 0 }
  if (shouldOpen && side) emit('snap-open', side)
}

function collapsedPaneRevealStyle(side) {
  const progress = collapsedPaneReveal.value.side === side ? collapsedPaneReveal.value.progress : 0
  return { '--pane-reveal-progress': progress }
}

function collapsedPaneRevealValue(side) {
  return collapsedPaneReveal.value.side === side
    ? Math.round(collapsedPaneReveal.value.progress * 100)
    : 0
}

function handleCollapsedPaneKeydown(event, side) {
  const opensPane = event.key === 'Enter'
    || event.key === ' '
    || (side === 'primary' && event.key === 'ArrowRight')
    || (side === 'context' && event.key === 'ArrowLeft')
  if (!opensPane) return
  event.preventDefault()
  emit('snap-open', side)
}

function lockTextSelection() {
  window.getSelection?.()?.removeAllRanges()
  document.body.classList.add('workspace-resizing')
}

function unlockTextSelection() {
  document.body.classList.remove('workspace-resizing')
}
</script>

<style scoped>
.knowledge-shell {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 0;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  border: 0;
  border-radius: var(--vk-radius-structural);
  overflow: hidden;
  background: var(--vk-bg-quiet);
  box-shadow: none;
}

.workspace-frame {
  position: relative;
  --panel-motion: var(--vk-motion-panel) var(--vk-ease-drawer);
  --panel-fade: var(--vk-motion-standard) var(--vk-ease-out);
  min-width: 0;
  height: 100%;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: var(--vk-bg-center);
}

.collapsed-pane-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 8;
  --pane-reveal-progress: 0;
  width: 10px;
  cursor: col-resize;
  touch-action: none;
}

.collapsed-pane-handle.left { left: 0; }
.collapsed-pane-handle.right { right: 0; }

.collapsed-pane-handle::before {
  content: "";
  position: absolute;
  inset-block: 0;
  width: 50px;
  pointer-events: none;
  opacity: var(--pane-reveal-progress);
  background: linear-gradient(90deg, color-mix(in srgb, var(--vk-accent) 18%, var(--vk-bg-panel)), transparent);
  transform: scaleX(var(--pane-reveal-progress));
}

.collapsed-pane-handle.left::before {
  left: 0;
  transform-origin: left center;
}

.collapsed-pane-handle.right::before {
  right: 0;
  background: linear-gradient(-90deg, color-mix(in srgb, var(--vk-accent) 18%, var(--vk-bg-panel)), transparent);
  transform-origin: right center;
}

.collapsed-pane-handle::after {
  content: "";
  position: absolute;
  top: 50%;
  width: 2px;
  height: 36px;
  border-radius: 2px;
  background: var(--vk-border);
  opacity: 0;
  transform: translateY(-50%);
  transition: opacity 0.16s ease, background-color 0.16s ease;
}

.collapsed-pane-handle.left::after { left: 3px; }
.collapsed-pane-handle.right::after { right: 3px; }

.collapsed-pane-handle.is-revealing::before {
  will-change: transform, opacity;
}

.collapsed-pane-handle.is-revealing::after {
  background: var(--vk-accent);
  opacity: 1;
  transform: translateY(-50%) scaleX(1);
}

.collapsed-pane-handle:focus-visible {
  outline: none;
}

.collapsed-pane-handle:focus-visible::after {
  background: var(--vk-accent-strong);
  opacity: 1;
}

.workspace-panes {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  height: 100%;
  min-height: 0;
  margin: 0;
  padding: 0;
  background: var(--vk-bg-center);
}

.workspace-single-pane {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--vk-bg-center);
}

.workspace-panes :deep(.splitpanes__pane) {
  min-width: 0;
  max-width: 100%;
  flex-shrink: 1;
  margin: 0;
  padding: 0;
  overflow: hidden;
  transition:
    width var(--panel-motion),
    flex-basis var(--panel-motion);
}

.workspace-panes.splitpanes--dragging :deep(.splitpanes__pane),
.workspace-panes.pointer-resizing :deep(.splitpanes__pane),
.workspace-panes.splitpanes--dragging .primary-sidebar-shell,
.workspace-panes.pointer-resizing .primary-sidebar-shell,
.workspace-panes.splitpanes--dragging .context-sidebar,
.workspace-panes.pointer-resizing .context-sidebar {
  transition: none !important;
}

/* Resizing follows the pointer directly. Only the semantic snap between an
   open pane and its collapsed state receives the drawer transition. */
.workspace-panes.is-snap-animating :deep(.splitpanes__pane) {
  transition:
    width var(--panel-motion),
    flex-basis var(--panel-motion) !important;
}

.workspace-panes.is-snap-animating .primary-sidebar-shell,
.workspace-panes.is-snap-animating .context-sidebar {
  transition:
    opacity var(--panel-fade),
    transform var(--panel-motion) !important;
}

.workspace-panes :deep(.splitpanes__splitter) {
  position: relative;
  z-index: 4;
  width: 8px;
  min-width: 8px;
  border: 0;
  cursor: col-resize;
  touch-action: none;
}

/* Keep the 8px resize target visually transparent: each half continues the
   surface beside it, while the actual divider remains exactly on the boundary.
   A uniform centre background here made the preview appear to bleed into both
   sidebars by several pixels. */
.workspace-panes :deep(.splitpanes__splitter:nth-child(2)) {
  background: linear-gradient(
    to right,
    var(--vk-bg-quiet) 0 50%,
    var(--vk-bg-center) 50% 100%
  );
}

.workspace-panes :deep(.splitpanes__splitter:nth-child(4)) {
  background: linear-gradient(
    to right,
    var(--vk-bg-center) 0 50%,
    var(--vk-bg-quiet) 50% 100%
  );
}

/* The collapsed handles above the frame provide the drag target. A hidden
   pane's Splitpanes splitter must therefore stop consuming layout space. */
.workspace-panes.primary-pane-collapsed :deep(.splitpanes__splitter:nth-child(2)),
.workspace-panes.context-pane-collapsed :deep(.splitpanes__splitter:nth-child(4)) {
  width: 0;
  min-width: 0;
  max-width: 0;
  pointer-events: none;
}

.workspace-panes.primary-pane-collapsed :deep(.splitpanes__splitter:nth-child(2)::before),
.workspace-panes.context-pane-collapsed :deep(.splitpanes__splitter:nth-child(4)::before) {
  opacity: 0;
}

.workspace-panes :deep(.splitpanes__splitter::before) {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--vk-border);
  transform: translateX(-50%);
  transition:
    background-color var(--vk-motion-standard) ease,
    transform var(--vk-motion-standard) ease;
}

.workspace-panes :deep(.splitpanes__splitter.is-active-splitter::before) {
  background: var(--vk-accent);
}

@media (hover: hover) and (pointer: fine) {
  .collapsed-pane-handle:hover::after {
    opacity: 1;
    background: var(--vk-accent);
  }

  .workspace-panes :deep(.splitpanes__splitter:hover::before) {
    background: var(--vk-accent);
    transform: scaleX(1);
  }
}

.primary-sidebar-shell,
.context-sidebar {
  flex-shrink: 1;
  min-width: 0;
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: hidden;
  background: var(--vk-bg-quiet);
  opacity: 1;
  transform: translateX(0);
  transition:
    opacity var(--panel-fade),
    transform var(--panel-motion);
  will-change: opacity, transform;
}

.primary-sidebar-shell {
  transform-origin: left center;
}

.context-sidebar {
  transform-origin: right center;
}

.primary-sidebar-hidden,
.context-sidebar-hidden {
  opacity: 0;
  pointer-events: none;
}

.primary-sidebar-hidden {
  transform: translateX(-16px);
}

.context-sidebar-hidden {
  transform: translateX(16px);
}

@media (max-width: 900px) {
  .knowledge-shell {
    grid-template-columns: 48px minmax(0, 1fr) !important;
  }

  .workspace-panes {
    display: block !important;
    min-height: auto;
    overflow: visible;
  }

  .workspace-panes :deep(.splitpanes__splitter) {
    display: none !important;
  }

  .workspace-panes :deep(.splitpanes__pane) {
    width: 100% !important;
    height: auto !important;
    position: static !important;
    overflow: visible;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workspace-panes :deep(.splitpanes__pane) {
    transition: none;
  }

  .primary-sidebar-shell,
  .context-sidebar {
    transform: none;
    transition: opacity var(--vk-motion-fast) ease;
  }

  .workspace-panes :deep(.splitpanes__splitter::before),
  .collapsed-pane-handle::after {
    transition: none;
  }
}

@media (max-width: 620px) {
  .knowledge-shell {
    display: grid;
    grid-template-columns: 1fr !important;
    min-height: auto;
  }
}
</style>
