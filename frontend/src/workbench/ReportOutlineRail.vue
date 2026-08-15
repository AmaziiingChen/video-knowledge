<template>
  <Teleport to="body">
    <nav
      v-if="visible"
      ref="rail"
      class="report-outline-rail"
      :class="{ 'is-lensing': pointerY !== null, 'is-dense': isOverflowing }"
      :style="railStyle"
      :aria-label="ariaLabel"
      @pointermove="handlePointerMove"
      @pointerleave="clearPointerLens"
    >
      <button
        v-for="(entry, index) in entries"
        :key="entry.id"
        class="report-outline-rail-item"
        :class="{ 'is-active': entry.id === activeId, 'is-secondary': entry.level === 3 }"
        type="button"
        :aria-label="entry.text"
        :aria-current="entry.id === activeId ? 'location' : undefined"
        :title="entry.text"
        :ref="(element) => setMarkerElement(entry.id, element)"
        :style="markerStyle(index, entry)"
        @pointerenter="setHoveredEntry(entry.id)"
        @focus="setHoveredEntry(entry.id)"
        @blur="clearHoveredEntry"
        @click="scrollToEntry(entry)"
        @keydown="handleKeydown($event, index)"
      >
        <span aria-hidden="true"></span>
      </button>
    </nav>
    <Transition name="report-outline-card">
      <aside
        v-if="hoveredEntry && visible"
        class="report-outline-card"
        :style="cardStyle"
        role="tooltip"
      >
        <strong>{{ hoveredEntry.text }}</strong>
        <p>{{ hoveredEntry.preview || '定位至该节内容。' }}</p>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  canShowReportOutline,
  reportOutlineHeight,
} from './reportOutlineLayout.js'

const props = defineProps({
  scrollRoot: { type: Object, default: null },
  contentRoot: { type: Object, default: null },
  contentVersion: { type: String, default: '' },
  reportKey: { type: String, default: '' },
  headingSelector: { type: String, default: 'h2, h3' },
  entryFilter: { type: Function, default: null },
  entryLevel: { type: Function, default: null },
  remoteEntries: { type: Array, default: () => [] },
  remoteActiveId: { type: String, default: '' },
  onRemoteSelect: { type: Function, default: null },
  ariaLabel: { type: String, default: '报告目录' },
})

const rail = ref(null)
const entries = ref([])
const activeId = ref('')
const visible = ref(false)
const isOverflowing = ref(false)
const railStyle = ref({})
const pointerY = ref(null)
const hoveredId = ref('')
let layoutFrame = 0
let scrollFrame = 0
let resizeObserver = null
let scrollListenerRoot = null
const markerElements = new Map()

const hoveredEntry = computed(() => entries.value.find((entry) => entry.id === hoveredId.value) || null)
const isRemoteOutline = computed(() => props.remoteEntries.length > 0)
const cardStyle = computed(() => {
  const entry = hoveredEntry.value
  const marker = entry ? markerElements.get(entry.id) : null
  const railBox = rail.value?.getBoundingClientRect()
  if (!entry || !marker || !railBox) return {}
  // Reading rail location changes on window / pane resize. Reading railStyle here
  // makes the card recalculate with the same geometry update.
  void railStyle.value
  const markerBox = marker.getBoundingClientRect()
  const cardHeight = 112
  const safeTop = 16
  const safeBottom = window.innerHeight - 16
  const top = Math.max(safeTop, Math.min(safeBottom - cardHeight, markerBox.top + markerBox.height / 2 - cardHeight / 2))
  const left = railBox.right + 14
  const width = Math.max(210, Math.min(330, window.innerWidth - left - 18))
  return { left: `${Math.round(left)}px`, top: `${Math.round(top)}px`, width: `${Math.round(width)}px` }
})

function headingId(index) {
  return `report-outline-${String(props.reportKey || 'preview').replace(/[^a-zA-Z0-9_-]/g, '-')}-${index + 1}`
}

function collectHeadings() {
  if (isRemoteOutline.value) {
    entries.value = props.remoteEntries.map((entry, index) => ({
      id: String(entry.id || `remote-outline-${index + 1}`),
      text: String(entry.text || '').trim(),
      order: Number(entry.order ?? index),
      level: Number(entry.level) || 2,
      preview: String(entry.preview || '').trim(),
      element: null,
    })).filter((entry) => entry.text)
    activeId.value = props.remoteActiveId || entries.value[0]?.id || ''
    measure()
    return
  }
  const root = props.contentRoot
  if (!root) {
    entries.value = []
    activeId.value = ''
    measure()
    return
  }

  const allEntries = [...root.querySelectorAll(props.headingSelector)]
    .map((element, index) => {
      const text = element.textContent?.replace(/\s+/g, ' ').trim() || ''
      if (!text || (props.entryFilter && !props.entryFilter(element, text))) return null
      const id = element.id || headingId(index)
      element.id = id
      return {
        id,
        text,
        order: index,
        level: Number(props.entryLevel?.(element, text)) || Number(element.tagName.slice(1)) || 2,
        preview: headingPreview(element),
        element,
      }
    })
    .filter(Boolean)
  const nextEntries = selectOutlineEntries(allEntries)

  entries.value = nextEntries
  if (!nextEntries.some((entry) => entry.id === activeId.value)) activeId.value = nextEntries[0]?.id || ''
  measure()
  updateActiveEntry()
}

function measure() {
  const scrollRoot = props.scrollRoot
  const contentRoot = props.contentRoot
  if (!scrollRoot || (!contentRoot && !isRemoteOutline.value) || entries.value.length < 2) {
    visible.value = false
    isOverflowing.value = false
    return
  }

  const scrollBox = scrollRoot.getBoundingClientRect()
  const contentBox = contentRoot ? entryRect(contentRoot) : null
  const leftGutter = isRemoteOutline.value || props.scrollRoot instanceof HTMLIFrameElement
    ? 70
    : Math.max(0, Number(contentBox?.left) - scrollBox.left)
  const canFitRail = canShowReportOutline({
    width: scrollBox.width,
    height: scrollBox.height,
    entryCount: entries.value.length,
    leftGutter,
  })
  visible.value = canFitRail
  if (!canFitRail) {
    isOverflowing.value = false
    return
  }

  const safeTop = Math.max(scrollBox.top + 12, 12)
  const safeBottom = Math.min(scrollBox.bottom - 12, window.innerHeight - 12)
  const availableHeight = safeBottom - safeTop
  // The pitch is the invariant: every heading owns exactly 16px. The rail grows
  // from its midpoint until it reaches roughly three quarters of the reader;
  // only then does the rail become internally scrollable.
  const markerPitch = 16
  const naturalHeight = entries.value.length * markerPitch
  const height = reportOutlineHeight({
    availableHeight,
    readerHeight: scrollBox.height,
    entryCount: entries.value.length,
  })
  if (!height) {
    visible.value = false
    isOverflowing.value = false
    return
  }
  isOverflowing.value = naturalHeight > height
  const minimumCenter = safeTop + height / 2
  const maximumCenter = safeBottom - height / 2
  const rootCenter = scrollBox.top + scrollBox.height / 2
  const top = Math.max(minimumCenter, Math.min(maximumCenter, rootCenter))
  railStyle.value = {
    '--report-outline-rail-height': `${height}px`,
    '--report-outline-marker-pitch': `${markerPitch}px`,
    // The outline belongs to the reading workspace, not the article column:
    // keep it next to the left sidebar and let its card expand toward the text.
    left: `${Math.round(scrollBox.left + 16)}px`,
    top: `${Math.round(top)}px`,
  }
}

function scrollElement() {
  if (props.scrollRoot instanceof HTMLIFrameElement) {
    return props.scrollRoot.contentDocument?.scrollingElement || props.scrollRoot.contentDocument?.documentElement || null
  }
  return props.scrollRoot
}

function scrollEventTarget() {
  if (props.scrollRoot instanceof HTMLIFrameElement) return props.scrollRoot.contentDocument || null
  return scrollElement()
}

function entryRect(element) {
  const rect = element.getBoundingClientRect()
  if (props.scrollRoot instanceof HTMLIFrameElement) {
    const frame = props.scrollRoot.getBoundingClientRect()
    return { ...rect, top: frame.top + rect.top, bottom: frame.top + rect.bottom, left: frame.left + rect.left, right: frame.left + rect.right }
  }
  return rect
}

function scheduleMeasure() {
  if (layoutFrame) return
  layoutFrame = window.requestAnimationFrame(() => {
    layoutFrame = 0
    measure()
  })
}

function updateActiveEntry() {
  const scrollRoot = props.scrollRoot
  if (!scrollRoot || !entries.value.length) return
  if (isRemoteOutline.value) {
    const nextActive = props.remoteActiveId || entries.value[0].id
    if (activeId.value === nextActive) return
    activeId.value = nextActive
    void nextTick(keepActiveMarkerVisible)
    return
  }
  const scrollBox = scrollRoot.getBoundingClientRect()
  const readingLine = scrollBox.top + Math.min(160, scrollBox.height * 0.3)
  let nextActive = entries.value[0].id
  for (const entry of entries.value) {
    if (entryRect(entry.element).top <= readingLine) nextActive = entry.id
    else break
  }
  if (activeId.value === nextActive) return
  activeId.value = nextActive
  void nextTick(keepActiveMarkerVisible)
}

function keepActiveMarkerVisible() {
  const container = rail.value
  const marker = markerElements.get(activeId.value)
  if (!isOverflowing.value || !container || !marker) return
  const containerBox = container.getBoundingClientRect()
  const markerBox = marker.getBoundingClientRect()
  const safeInset = 28
  if (markerBox.top >= containerBox.top + safeInset && markerBox.bottom <= containerBox.bottom - safeInset) return
  const markerCenter = markerBox.top + markerBox.height / 2
  container.scrollBy({ top: markerCenter - (containerBox.top + containerBox.height / 2), behavior: 'auto' })
}

function handleScroll() {
  if (scrollFrame) return
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = 0
    updateActiveEntry()
  })
}

function connectObservers() {
  resizeObserver?.disconnect()
  const root = props.contentRoot
  const scrollRoot = scrollElement()
  if ((!root && !isRemoteOutline.value) || !scrollRoot) return

  resizeObserver = new ResizeObserver(scheduleMeasure)
  if (root) resizeObserver.observe(root)
  resizeObserver.observe(scrollRoot)
  if (isRemoteOutline.value) {
    window.addEventListener('resize', scheduleMeasure, { passive: true })
    return
  }
  const eventTarget = scrollEventTarget()
  eventTarget?.addEventListener('scroll', handleScroll, { passive: true })
  scrollListenerRoot = eventTarget
  window.addEventListener('resize', scheduleMeasure, { passive: true })
}

function disconnectObservers() {
  scrollListenerRoot?.removeEventListener('scroll', handleScroll)
  scrollListenerRoot = null
  window.removeEventListener('resize', scheduleMeasure)
  resizeObserver?.disconnect()
  resizeObserver = null
}

async function refresh() {
  disconnectObservers()
  await nextTick()
  connectObservers()
  collectHeadings()
}

function handlePointerMove(event) {
  pointerY.value = event.clientY
}

function clearPointerLens() {
  pointerY.value = null
  clearHoveredEntry()
}

function setHoveredEntry(id) {
  hoveredId.value = id
}

function selectOutlineEntries(allEntries) {
  return allEntries
}

function clearHoveredEntry() {
  hoveredId.value = ''
}

function headingPreview(element) {
  const parts = []
  let sibling = element.nextElementSibling
  while (sibling && !/^H[23]$/.test(sibling.tagName) && parts.join('').length < 180) {
    const text = sibling.textContent?.replace(/\s+/g, ' ').trim() || ''
    if (text) parts.push(text)
    sibling = sibling.nextElementSibling
  }
  const preview = parts.join(' ')
  return preview.length > 180 ? `${preview.slice(0, 179)}…` : preview
}

function setMarkerElement(id, element) {
  if (element) markerElements.set(id, element)
  else markerElements.delete(id)
}

function closestMarkerIndex(bounds) {
  let closestIndex = 0
  let closestDistance = Number.POSITIVE_INFINITY
  entries.value.forEach((entry, index) => {
    const markerBounds = markerElements.get(entry.id)?.getBoundingClientRect()
    const center = markerBounds
      ? markerBounds.top + markerBounds.height / 2
      : bounds.top + ((index + 0.5) / entries.value.length) * bounds.height
    const distance = Math.abs(Number(pointerY.value) - center)
    if (distance < closestDistance) {
      closestDistance = distance
      closestIndex = index
    }
  })
  return closestIndex
}

function markerStyle(index, entry) {
  // The primary heading marker is about 3px longer at rest; lens scales below
  // still take precedence whenever the pointer enters the outline.
  const restingScale = entry.level === 2 ? 0.31 : 0.21
  if (pointerY.value === null || !rail.value || entries.value.length < 2) {
    return { '--report-outline-marker-scale': restingScale }
  }
  const bounds = rail.value.getBoundingClientRect()
  const distanceFromFocusedMarker = Math.abs(index - closestMarkerIndex(bounds))
  // The seven-marker lens intentionally overrides the resting level scale: the
  // eye should first read proximity, then use tick length for heading depth.
  const lensScale = [0.56, 0.46, 0.35, 0.27][distanceFromFocusedMarker]
  return { '--report-outline-marker-scale': lensScale ?? restingScale }
}

function scrollToEntry(entry) {
  if (isRemoteOutline.value) {
    props.onRemoteSelect?.(entry)
    return
  }
  const scrollRoot = scrollElement()
  const viewportRoot = props.scrollRoot
  if (!scrollRoot || !viewportRoot || !entry?.element) return
  const rootBox = viewportRoot.getBoundingClientRect()
  const headingBox = entryRect(entry.element)
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  scrollRoot.scrollBy({
    top: headingBox.top - rootBox.top - Math.min(76, rootBox.height * 0.18),
    behavior: reducedMotion ? 'auto' : 'smooth',
  })
}

function handleKeydown(event, index) {
  let nextIndex = index
  if (event.key === 'ArrowDown') nextIndex += 1
  else if (event.key === 'ArrowUp') nextIndex -= 1
  else if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = entries.value.length - 1
  else return
  event.preventDefault()
  const target = rail.value?.querySelectorAll('.report-outline-rail-item')[Math.max(0, Math.min(entries.value.length - 1, nextIndex))]
  target?.focus()
}

watch(
  () => [props.scrollRoot, props.contentRoot, props.contentVersion, props.reportKey, props.remoteEntries],
  refresh,
  { flush: 'post', immediate: true },
)

watch(() => props.remoteActiveId, updateActiveEntry)

onBeforeUnmount(() => {
  disconnectObservers()
  markerElements.clear()
  if (layoutFrame) window.cancelAnimationFrame(layoutFrame)
  if (scrollFrame) window.cancelAnimationFrame(scrollFrame)
})
</script>

<style>
.report-outline-rail {
  position: fixed;
  z-index: 18;
  display: flex;
  flex-direction: column;
  width: 52px;
  height: var(--report-outline-rail-height);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: none;
  transform: translateY(-50%);
}

.report-outline-rail::-webkit-scrollbar { display: none; }

.report-outline-rail-item {
  display: flex;
  align-items: center;
  flex: 0 0 var(--report-outline-marker-pitch, 16px);
  width: 52px;
  min-height: var(--report-outline-marker-pitch, 16px);
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
  touch-action: none;
}

.report-outline-rail-item > span {
  display: block;
  width: calc(52px * var(--report-outline-marker-scale, 0.24));
  height: 3px;
  border-radius: 999px !important;
  background: currentColor;
  opacity: 0.38;
  transition: width 180ms var(--vk-ease-out), opacity 140ms ease, background-color 140ms ease;
  will-change: width;
}

.report-outline-rail.is-lensing .report-outline-rail-item > span {
  transition: width 150ms var(--vk-ease-out), opacity 100ms ease, background-color 100ms ease;
}

.report-outline-rail.is-dense {
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 24px, #000 calc(100% - 24px), transparent 100%);
  mask-image: linear-gradient(to bottom, transparent 0, #000 24px, #000 calc(100% - 24px), transparent 100%);
}

.report-outline-rail-item.is-active { color: var(--vk-text); }
.report-outline-rail-item.is-active > span { opacity: 0.9; }
.report-outline-rail-item:hover > span { opacity: 0.72; }
.report-outline-rail-item:focus-visible { outline: none; }
.report-outline-rail-item:focus-visible > span {
  color: var(--vk-accent-strong);
  opacity: 1;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--vk-accent) 20%, transparent);
}

.report-outline-card {
  position: fixed;
  z-index: 19;
  box-sizing: border-box;
  min-height: 96px;
  max-height: 112px;
  padding: 14px 16px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 62%, var(--vk-bg-panel));
  border-radius: 16px;
  background: color-mix(in srgb, var(--vk-bg-panel) 92%, transparent);
  box-shadow:
    0 12px 30px color-mix(in srgb, var(--vk-text) 12%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.54);
  backdrop-filter: blur(28px) saturate(145%);
  -webkit-backdrop-filter: blur(28px) saturate(145%);
  transform-origin: left center;
  pointer-events: auto;
}

.report-outline-card strong {
  display: block;
  overflow: hidden;
  color: var(--vk-text);
  font-size: 16px;
  font-weight: 680;
  letter-spacing: -0.012em;
  line-height: 1.28;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-outline-card p {
  display: -webkit-box;
  margin: 6px 0 0;
  overflow: hidden;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.report-outline-card-enter-active {
  transition: opacity 130ms var(--vk-ease-out), transform 130ms var(--vk-ease-out);
}

.report-outline-card-leave-active {
  transition: none;
}

.report-outline-card-enter-from,
.report-outline-card-leave-to {
  opacity: 0;
  transform: scale(0.985);
}

@media (prefers-reduced-motion: reduce) {
  .report-outline-rail-item > span { transition: opacity 100ms ease, background-color 100ms ease; }
  .report-outline-card-enter-active,
  .report-outline-card-leave-active { transition: opacity 100ms ease; }
  .report-outline-card-enter-from,
  .report-outline-card-leave-to { filter: none; transform: none; }
}

@media (prefers-contrast: more), (prefers-reduced-transparency: reduce) {
  .report-outline-rail-item > span { opacity: 0.68; }
  .report-outline-rail-item.is-active > span { opacity: 1; }
  .report-outline-card { background: var(--vk-bg-panel); backdrop-filter: none; -webkit-backdrop-filter: none; }
}
</style>
