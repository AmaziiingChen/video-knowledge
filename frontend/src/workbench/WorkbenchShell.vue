<template>
  <div class="knowledge-shell" :class="{ 'has-integrated-chrome': integratedChrome }">
    <div v-if="integratedChrome" class="workspace-activity-header" aria-hidden="true"></div>
    <ActivityBar
      :active-view="activeView"
      :items="ribbonItems"
      @update:active-view="$emit('update:activeView', $event)"
      @open-settings="$emit('open-settings')"
    />

    <div ref="workspaceFrame" class="workspace-frame">
      <div
        v-if="integratedChrome && !isSinglePaneWorkspaceView(activeView)"
        class="workspace-global-header-actions"
      >
        <slot name="global-header-actions" />
      </div>
      <div v-if="isSinglePaneWorkspaceView(activeView)" class="workspace-single-pane">
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
          @transitionend="handlePaneTransitionEnd"
          @transitioncancel="handlePaneTransitionEnd"
          @resized="handleResized"
          @pointerdown.capture="beginSplitterDrag"
          @keydown.capture="handleSplitterKeydown"
        >
          <pane
            :size="showPrimaryPane ? workspaceLayout.primary : 0"
            :min-size="showPrimaryPane ? snapMinSize : 0"
            :max-size="showPrimaryPane ? 45 : 0"
          >
            <div class="workspace-pane-column workspace-primary-pane">
              <header class="workspace-pane-header workspace-primary-header">
                <slot name="primary-header" />
              </header>
              <aside
                class="primary-sidebar-shell"
                :class="{ 'primary-sidebar-hidden': !showPrimaryPane }"
                aria-label="左侧栏"
                :aria-hidden="!showPrimaryPane"
              >
                <slot name="primary" />
              </aside>
            </div>
          </pane>

          <pane :size="editorPaneSize" :min-size="showContextPane ? editorMinSize : 50">
            <div class="workspace-pane-column workspace-editor-pane">
              <header class="workspace-pane-header workspace-editor-header">
                <slot name="editor-header" />
                <span
                  v-if="integratedChrome && !showContextPane"
                  class="workspace-editor-header-action-region"
                  aria-hidden="true"
                ></span>
              </header>
              <div class="workspace-pane-body">
                <slot name="editor" />
              </div>
            </div>
          </pane>

          <pane
            :size="showContextPane ? workspaceLayout.context : 0"
            :min-size="showContextPane ? snapMinSize : 0"
            :max-size="showContextPane ? 65 : 0"
          >
            <div class="workspace-pane-column workspace-context-pane">
              <header class="workspace-pane-header workspace-context-header">
                <slot name="context-header" />
                <span
                  v-if="integratedChrome"
                  class="workspace-context-header-action-region"
                  aria-hidden="true"
                ></span>
              </header>
              <aside
                class="context-sidebar"
                :class="{ 'context-sidebar-hidden': !showContextPane }"
                aria-label="AI 助手"
                :aria-hidden="!showContextPane"
              >
                <slot name="context" />
              </aside>
            </div>
          </pane>
        </splitpanes>
        <span
          v-if="primaryToggleMotion"
          class="primary-toggle-motion"
          :class="{ 'is-moving': primaryToggleMotion.isMoving }"
          :style="primaryToggleMotionStyle"
          aria-hidden="true"
        >
          <PanelToggleIcon side="left" :collapsed="primaryToggleMotion.collapsed" />
        </span>
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
import PanelToggleIcon from '../components/PanelToggleIcon.vue'
import {
  COLLAPSED_PANE_REVEAL_DISTANCE,
  resolvePaneDragTransition,
  revealProgressForDistance,
} from './splitterDragState.js'
import { isSinglePaneWorkspaceView } from './workspaceViewLoading.js'

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
  },
  primaryPaneTransitioning: {
    type: Boolean,
    default: false
  },
  integratedChrome: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'update:activeView',
  'open-settings',
  'resized',
  'snap-collapse',
  'snap-open',
  'pane-drag-resize',
  'pane-visibility-transition-end'
])

const workspaceFrame = ref(null)
const paneWidth = ref(1200)
const pointerResizing = ref(false)
const paneSnapAnimating = ref(false)
const collapsedPaneReveal = ref({ side: '', progress: 0 })
const primaryToggleMotion = ref(null)
const primaryToggleMotionStyle = computed(() => {
  const motion = primaryToggleMotion.value
  if (!motion) return {}
  return {
    '--primary-toggle-motion-x': `${motion.x}px`,
    '--primary-toggle-motion-y': `${motion.y}px`,
  }
})
const MIN_PANE_WIDTH = 200
let splitterDrag = null
let collapsedPaneDrag = null
let splitterResizeFrame = 0
let paneSnapAnimationTimer = 0
let primaryToggleMotionFrame = 0

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
  stopPrimaryToggleMotion()
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

function handlePaneTransitionEnd(event) {
  if (!props.primaryPaneTransitioning || event.propertyName !== 'width') return
  const panes = workspaceFrame.value?.querySelectorAll?.('.workspace-panes > .splitpanes__pane') || []
  if (event.target !== panes[0]) return
  emit('pane-visibility-transition-end', { side: 'primary' })
  void nextTick(stopPrimaryToggleMotion)
}

function beginPrimaryToggleMotion(originRect, opening) {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || !workspaceFrame.value) return
  const frameRect = workspaceFrame.value.getBoundingClientRect()
  const primaryWidth = (workspaceFrame.value.clientWidth * Number(props.workspaceLayout.primary || 0)) / 100
  const destinationX = opening
    ? Math.max(0, primaryWidth - 36)
    : 36

  if (primaryToggleMotionFrame) window.cancelAnimationFrame(primaryToggleMotionFrame)
  primaryToggleMotion.value = {
    x: originRect.left - frameRect.left,
    y: originRect.top - frameRect.top,
    collapsed: opening,
    isMoving: false,
  }
  void nextTick(() => {
    if (!primaryToggleMotion.value || !workspaceFrame.value) return
    // Commit the captured position before applying the destination. Without
    // this layout read, Chromium can coalesce both writes into one paint and
    // skip the transform transition entirely.
    workspaceFrame.value.querySelector('.primary-toggle-motion')?.getBoundingClientRect()
    primaryToggleMotionFrame = window.requestAnimationFrame(() => {
      primaryToggleMotionFrame = 0
      if (!primaryToggleMotion.value) return
      primaryToggleMotion.value = {
        ...primaryToggleMotion.value,
        x: destinationX,
        y: 6,
        collapsed: !opening,
        isMoving: true,
      }
    })
  })
}

function stopPrimaryToggleMotion() {
  if (primaryToggleMotionFrame) {
    window.cancelAnimationFrame(primaryToggleMotionFrame)
    primaryToggleMotionFrame = 0
  }
  primaryToggleMotion.value = null
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

watch(
  () => props.primaryPaneTransitioning,
  (transitioning) => {
    if (!transitioning || !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    stopPrimaryToggleMotion()
    void nextTick(() => emit('pane-visibility-transition-end', { side: 'primary' }))
  },
)

defineExpose({ beginPrimaryToggleMotion })

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
  grid-template-rows: minmax(0, 1fr);
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

.knowledge-shell.has-integrated-chrome {
  grid-template-rows: 40px minmax(0, 1fr);
}

.workspace-activity-header {
  grid-column: 1;
  grid-row: 1;
  min-width: 0;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
  -webkit-app-region: drag;
}

.knowledge-shell.has-integrated-chrome :deep(.workspace-ribbon) {
  grid-column: 1;
  grid-row: 2;
}

.workspace-frame {
  position: relative;
  --workspace-global-actions-width: 204px;
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

.knowledge-shell.has-integrated-chrome .workspace-frame {
  grid-column: 2;
  grid-row: 1 / 3;
}

.workspace-global-header-actions {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 10;
  width: min(var(--workspace-global-actions-width), 100%);
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  overflow: hidden;
  pointer-events: auto;
  -webkit-app-region: no-drag;
}

.workspace-global-header-actions :deep(button),
.workspace-global-header-actions :deep(a),
.workspace-global-header-actions :deep(input),
.workspace-global-header-actions :deep(.el-tooltip__trigger) {
  pointer-events: auto;
  -webkit-app-region: no-drag;
}

.primary-toggle-motion {
  position: absolute;
  z-index: 12;
  top: 0;
  left: 0;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: var(--vk-accent-strong);
  pointer-events: none;
  transform: translate3d(var(--primary-toggle-motion-x), var(--primary-toggle-motion-y), 0);
}

.primary-toggle-motion.is-moving {
  will-change: transform;
  transition: transform var(--panel-motion);
}

.primary-toggle-motion > :deep(.panel-toggle-icon) {
  transform: translateY(1px);
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

.workspace-pane-column {
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: 40px minmax(0, 1fr);
  overflow: hidden;
}

.workspace-pane-header {
  min-width: 0;
  height: 40px;
  display: flex;
  align-items: center;
  overflow: hidden;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
  -webkit-app-region: drag;
}

.workspace-pane-header :deep(button),
.workspace-pane-header :deep(input),
.workspace-pane-header :deep(.el-tooltip__trigger) {
  -webkit-app-region: no-drag;
}

.workspace-primary-header,
.workspace-editor-header,
.workspace-context-header {
  background: var(--vk-bg-quiet);
}

.workspace-context-header {
  position: relative;
}

.workspace-context-header-action-region {
  position: absolute;
  top: 0;
  right: 0;
  width: min(var(--workspace-global-actions-width), 100%);
  height: 100%;
  pointer-events: none;
  -webkit-app-region: no-drag;
}

/* Electron resolves app-region hit testing from the rendered header tree, not
   visual z-index alone. When the context pane is collapsed, the editor header
   reaches the global action cluster, so it needs the same non-draggable shield
   that the context header normally provides. The visible actions remain above
   this inert region and continue receiving pointer input. */
.workspace-editor-header-action-region {
  position: absolute;
  z-index: 9;
  top: 0;
  right: 0;
  width: min(var(--workspace-global-actions-width), 100%);
  height: 100%;
  pointer-events: none;
  -webkit-app-region: no-drag;
}

.workspace-pane-body {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
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
  /* A splitter participates in the flex layout.  Keeping an 8px hit target
     here left a visible blank column on high-density displays, so readers and
     media previews never reached their neighbouring panes.  Make the layout
     boundary itself one physical CSS pixel; the cursor still communicates the
     resize affordance without turning the divider into a gutter. */
  width: 1px;
  min-width: 1px;
  max-width: 1px;
  flex-basis: 1px;
  margin: 0 !important;
  border: 0;
  background: transparent !important;
  cursor: col-resize;
  touch-action: none;
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
  inset: 0;
  background: var(--vk-border);
  transform: none;
  transition:
    background-color var(--vk-motion-standard) ease,
    transform var(--vk-motion-standard) ease;
}

/* Keep an invisible 15px resize hit area without reserving it in the flex
   layout. Splitpanes receives pointer events from this pseudo-element as the
   splitter itself, while the visible workbench boundary remains one pixel. */
.workspace-panes :deep(.splitpanes__splitter::after) {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: -7px;
  width: 15px;
  height: auto !important;
  margin: 0 !important;
  background: transparent !important;
  transform: none !important;
  cursor: col-resize;
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

  .knowledge-shell.has-integrated-chrome {
    grid-template-rows: auto minmax(0, 1fr);
  }

  .workspace-activity-header {
    display: none;
  }

  .knowledge-shell.has-integrated-chrome :deep(.workspace-ribbon) {
    grid-column: 1;
    grid-row: 1;
  }

  .knowledge-shell.has-integrated-chrome .workspace-frame {
    grid-column: 1;
    grid-row: 2;
  }
}
</style>
