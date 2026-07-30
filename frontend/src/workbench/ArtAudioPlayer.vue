<template>
  <section class="art-audio-player" :aria-label="`${title || '音频'}播放器`">
    <button
      ref="waveformButton"
      class="art-audio-waveform"
      type="button"
      :aria-label="`${title || '音频'}波形。点击片段从该处播放；拖动以定位；点击播放头暂停。`"
      @pointerdown="beginSeek"
      @pointermove="dragSeek"
      @pointerup="finishSeek"
      @pointercancel="cancelSeek"
      @keydown.space.prevent="togglePlayback"
      @keydown.left.prevent="seekBy(-5)"
      @keydown.right.prevent="seekBy(5)"
    >
      <canvas ref="waveformCanvas" aria-hidden="true"></canvas>
      <span v-if="waveformState === 'loading'" class="art-audio-waveform-state">正在生成波形…</span>
      <span v-else-if="waveformState === 'unavailable'" class="art-audio-waveform-state">无法生成波形，仍可正常播放</span>
    </button>
    <audio
      ref="audio"
      :src="src"
      preload="metadata"
      @loadedmetadata="handleMetadata"
      @timeupdate="handleTimeUpdate"
      @play="setPlaybackState(true)"
      @pause="setPlaybackState(false)"
      @ended="setPlaybackState(false)"
      @error="waveformState = 'unavailable'"
    ></audio>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { readAudioWaveformCache, writeAudioWaveformCache } from '../features/library/audioWaveformCache.js'

const props = defineProps({
  src: { type: String, required: true },
  title: { type: String, default: '' },
  cacheKey: { type: String, default: '' },
})
const emit = defineEmits(['time-update', 'playback-change'])

const audio = ref(null)
const waveformCanvas = ref(null)
const waveformButton = ref(null)
const duration = ref(0)
const currentTime = ref(0)
const waveformState = ref('loading')
const waveformCacheKey = computed(() => props.cacheKey || props.src)
let waveformPoints = []
let seekStart = null
let resizeObserver = null
let loadVersion = 0
let drawFrame = 0

const progressPercent = computed(() => duration.value ? Math.min(100, Math.max(0, currentTime.value / duration.value * 100)) : 0)

function handleMetadata() {
  duration.value = Number.isFinite(audio.value?.duration) ? audio.value.duration : 0
  emit('time-update', audio.value?.currentTime || 0)
  scheduleDraw()
}

function handleTimeUpdate() {
  currentTime.value = Number(audio.value?.currentTime || 0)
  emit('time-update', currentTime.value)
  scheduleDraw()
}

async function togglePlayback() {
  if (!audio.value) return
  if (audio.value.paused) await audio.value.play().catch(() => {})
  else audio.value.pause()
}

function setPlaybackState(playing) {
  emit('playback-change', playing)
}

function pointerProgress(event) {
  const bounds = waveformButton.value?.getBoundingClientRect()
  if (!bounds?.width) return 0
  return Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width))
}

function beginSeek(event) {
  const progress = pointerProgress(event)
  seekStart = {
    progress,
    clientX: event.clientX,
    playhead: duration.value ? currentTime.value / duration.value : 0,
  }
  waveformButton.value?.setPointerCapture?.(event.pointerId)
  seekTo(progress)
}

function dragSeek(event) {
  if (!seekStart) return
  seekTo(pointerProgress(event))
}

function finishSeek(event) {
  if (!seekStart) return
  const moved = Math.abs(event.clientX - seekStart.clientX) > 3
  const target = pointerProgress(event)
  const clickedPlayhead = !moved && Math.abs(target - seekStart.playhead) < 0.012
  waveformButton.value?.releasePointerCapture?.(event.pointerId)
  seekStart = null
  if (clickedPlayhead) {
    void togglePlayback()
  } else if (audio.value?.paused) {
    void audio.value.play().catch(() => {})
  }
}

function cancelSeek(event) {
  waveformButton.value?.releasePointerCapture?.(event.pointerId)
  seekStart = null
}

function seekTo(progress) {
  if (!audio.value || !duration.value) return
  audio.value.currentTime = duration.value * progress
  currentTime.value = audio.value.currentTime
  scheduleDraw()
}

function seekBy(seconds) {
  seekTo((currentTime.value + seconds) / Math.max(duration.value, 1))
}

function seek(seconds) {
  const value = Number(seconds)
  if (!audio.value || !Number.isFinite(value)) return
  audio.value.currentTime = Math.max(value, 0)
  currentTime.value = audio.value.currentTime
  emit('time-update', currentTime.value)
  scheduleDraw()
  void audio.value.play().catch(() => {})
}

function resolvedColor(name, fallback) {
  const host = waveformButton.value
  return host ? getComputedStyle(host).getPropertyValue(name).trim() || fallback : fallback
}

function drawColumns(context, width, height, start, end, color, alpha = 1) {
  if (!waveformPoints.length || end <= start) return
  const mid = height / 2
  context.strokeStyle = color
  context.globalAlpha = alpha
  context.lineWidth = 1
  for (let x = Math.max(0, start); x < Math.min(width, end); x += 1) {
    const point = waveformPoints[Math.floor(x / width * waveformPoints.length)]
    context.beginPath()
    context.moveTo(x + 0.5, mid + point[0] * mid * 0.82)
    context.lineTo(x + 0.5, mid + point[1] * mid * 0.82)
    context.stroke()
  }
  context.globalAlpha = 1
}

function drawWaveform() {
  drawFrame = 0
  const canvas = waveformCanvas.value
  const host = waveformButton.value
  if (!canvas || !host) return
  const ratio = window.devicePixelRatio || 1
  const width = Math.max(1, Math.floor(host.clientWidth))
  const height = Math.max(1, Math.floor(host.clientHeight))
  canvas.width = Math.floor(width * ratio)
  canvas.height = Math.floor(height * ratio)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  const context = canvas.getContext('2d')
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, width, height)
  if (!waveformPoints.length) return
  const progressX = Math.round(width * progressPercent.value / 100)
  drawColumns(context, width, height, 0, width, resolvedColor('--vk-muted'))
  drawColumns(context, width, height, 0, progressX, resolvedColor('--vk-accent'))
  context.fillStyle = resolvedColor('--vk-accent-strong')
  context.fillRect(Math.max(0, progressX - 0.5), 0, 1, height)
}

function scheduleDraw() {
  if (drawFrame) return
  drawFrame = window.requestAnimationFrame(drawWaveform)
}

function bucketWaveform(source) {
  const bucketCount = Math.min(1800, Math.max(360, Math.ceil(source.length / 512)))
  const blockSize = Math.max(1, Math.floor(source.length / bucketCount))
  return Array.from({ length: bucketCount }, (_, index) => {
    let min = 1
    let max = -1
    const end = Math.min(source.length, (index + 1) * blockSize)
    for (let cursor = index * blockSize; cursor < end; cursor += 1) {
      const value = source[cursor]
      if (value < min) min = value
      if (value > max) max = value
    }
    return [min, max]
  })
}

async function buildWaveform() {
  const version = ++loadVersion
  waveformState.value = 'loading'
  waveformPoints = readAudioWaveformCache(waveformCacheKey.value) || []
  if (waveformPoints.length) {
    waveformState.value = 'ready'
    await nextTick()
    scheduleDraw()
    return
  }
  try {
    const response = await fetch(props.src)
    if (!response.ok) throw new Error('media unavailable')
    const audioData = await response.arrayBuffer()
    const context = new (window.AudioContext || window.webkitAudioContext)()
    const decoded = await context.decodeAudioData(audioData)
    await context.close()
    if (version !== loadVersion) return
    waveformPoints = bucketWaveform(decoded.getChannelData(0))
    writeAudioWaveformCache(waveformCacheKey.value, waveformPoints)
    waveformState.value = 'ready'
    await nextTick()
    scheduleDraw()
  } catch {
    if (version === loadVersion) waveformState.value = 'unavailable'
  }
}

watch([() => props.src, waveformCacheKey], () => {
  currentTime.value = 0
  duration.value = 0
  void buildWaveform()
})

onMounted(() => {
  void buildWaveform()
  resizeObserver = new ResizeObserver(scheduleDraw)
  if (waveformButton.value) resizeObserver.observe(waveformButton.value)
})
onBeforeUnmount(() => {
  loadVersion += 1
  if (drawFrame) window.cancelAnimationFrame(drawFrame)
  resizeObserver?.disconnect()
})

defineExpose({
  seek,
  togglePlayback,
})
</script>

<style scoped>
.art-audio-player { position: absolute; inset: 0; display: flex; min-height: 0; padding: 0; border-radius: 0 !important; background: var(--vk-bg-center); color: var(--vk-text); }
.art-audio-waveform { position: relative; flex: 1; width: 100%; height: 100%; min-width: 0; min-height: 0; margin: 0; padding: 0; overflow: hidden; appearance: none; -webkit-appearance: none; border: 0; border-radius: 0 !important; background: var(--vk-bg-center); cursor: pointer; touch-action: none; transition: background-color 120ms ease-out; }
.art-audio-waveform:focus-visible { outline: 2px solid var(--vk-accent); outline-offset: 2px; }
.art-audio-waveform canvas { position: absolute; inset: 0; }
.art-audio-waveform-state { position: absolute; inset: 0; display: grid; place-items: center; color: var(--vk-text-muted); font-size: var(--vk-font-meta); pointer-events: none; }
@media (prefers-reduced-motion: reduce) { .art-audio-waveform { transition: none; } }
</style>
