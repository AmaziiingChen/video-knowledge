<template>
  <div class="art-video-player">
    <canvas
      ref="backdropRef"
      class="art-video-backdrop"
      aria-hidden="true"
    ></canvas>
    <div ref="containerRef" class="art-video-container"></div>
    <div v-if="playerState === 'loading'" class="art-video-state">正在载入视频预览…</div>
    <div v-else-if="playerState === 'error'" class="art-video-state is-error">
      <span>视频预览载入失败</span>
      <button type="button" @click="refreshPlayer">重试</button>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Artplayer from 'artplayer'

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  poster: {
    type: String,
    default: ''
  },
  thumbnailVttUrl: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['time-update'])

const containerRef = ref(null)
const backdropRef = ref(null)
const playerState = ref('loading')
let player = null
let posterObjectUrl = ''
let playerLoadVersion = 0

function buildPlugins() {
  if (!props.thumbnailVttUrl) return []
  return [
    createVttThumbnailPlugin({
      vtt: backendUrl(props.thumbnailVttUrl),
      style: {
        borderRadius: '0',
        boxShadow: '0 8px 22px rgba(0, 0, 0, 0.28)'
      }
    })
  ]
}

function createVttThumbnailPlugin(options) {
  return (art) => {
    loadVttThumbnails(options.vtt).then((thumbnails) => {
      if (!thumbnails.length || art.isDestroy) return

      const progress = art.template.$progress
      const playerElement = art.template.$player
      const thumbnail = document.createElement('div')
      thumbnail.className = 'knowledgehub-vtt-thumbnail'
      Object.assign(thumbnail.style, {
        position: 'absolute',
        bottom: '46px',
        zIndex: '12',
        display: 'none',
        pointerEvents: 'none',
        backgroundRepeat: 'no-repeat',
        ...options.style
      })
      playerElement.appendChild(thumbnail)

      const hide = () => { thumbnail.style.display = 'none' }
      const update = (event) => {
        const bounds = progress.getBoundingClientRect()
        if (!bounds.width || !Number.isFinite(art.duration)) return
        const offset = Math.max(0, Math.min(event.clientX - bounds.left, bounds.width))
        const seconds = offset / bounds.width * art.duration
        const frame = thumbnails.find((item) => seconds >= item.start && seconds <= item.end)
        if (!frame) {
          hide()
          return
        }
        const left = Math.max(
          6,
          Math.min(
            progress.offsetLeft + offset - frame.width / 2,
            playerElement.clientWidth - frame.width - 6
          )
        )
        thumbnail.style.display = 'block'
        thumbnail.style.width = `${frame.width}px`
        thumbnail.style.height = `${frame.height}px`
        thumbnail.style.left = `${left}px`
        thumbnail.style.backgroundImage = `url("${frame.url}")`
        thumbnail.style.backgroundPosition = `-${frame.x}px -${frame.y}px`
      }

      progress.addEventListener('mousemove', update)
      progress.addEventListener('mouseleave', hide)
      art.on('destroy', () => {
        progress.removeEventListener('mousemove', update)
        progress.removeEventListener('mouseleave', hide)
        thumbnail.remove()
      })
    }).catch(() => {})
    return { name: 'knowledgehubVttThumbnails' }
  }
}

async function loadVttThumbnails(vttUrl) {
  const text = await fetch(vttUrl).then((response) => response.text())
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const frames = []
  for (let index = 0; index < lines.length - 1; index += 1) {
    if (!lines[index].includes('-->')) continue
    const times = lines[index].split('-->').map((value) => parseVttTime(value.trim()))
    const match = lines[index + 1].match(/^(.*)#xywh=(\d+),(\d+),(\d+),(\d+)$/)
    if (!match || times.some((value) => !Number.isFinite(value))) continue
    frames.push({
      start: times[0],
      end: times[1],
      url: new URL(match[1], vttUrl).href,
      x: Number(match[2]),
      y: Number(match[3]),
      width: Number(match[4]),
      height: Number(match[5])
    })
  }
  return frames
}

function parseVttTime(value) {
  const parts = value.replace(',', '.').split(':').map(Number)
  if (parts.some((part) => !Number.isFinite(part))) return NaN
  return parts.reduce((total, part) => total * 60 + part, 0)
}

function backendUrl(value) {
  const url = String(value || '').trim()
  if (!url || /^[a-z][a-z\d+.-]*:\/\//iu.test(url)) return url
  return new URL(url, props.src).href
}

async function createPlayer() {
  if (!containerRef.value || !props.src) return
  const loadVersion = ++playerLoadVersion
  destroyPlayer()
  clearBackdrop()
  playerState.value = 'loading'
  const previewPoster = props.poster || await buildPreviewPoster()
  if (loadVersion !== playerLoadVersion || !containerRef.value) {
    if (previewPoster && previewPoster !== props.poster) URL.revokeObjectURL(previewPoster)
    return
  }
  if (previewPoster && previewPoster !== props.poster) posterObjectUrl = previewPoster
  const themeColor = getComputedStyle(document.documentElement).getPropertyValue('--vk-accent').trim()
  player = new Artplayer({
    container: containerRef.value,
    url: props.src,
    poster: previewPoster,
    theme: themeColor,
    volume: 0.8,
    autoplay: false,
    autoSize: false,
    playbackRate: true,
    aspectRatio: true,
    screenshot: false,
    setting: true,
    hotkey: true,
    pip: true,
    mutex: true,
    backdrop: false,
    fullscreen: true,
    fullscreenWeb: true,
    miniProgressBar: true,
    playsInline: true,
    autoPlayback: true,
    moreVideoAttr: {
      preload: 'metadata',
      playsInline: true
    },
    plugins: buildPlugins()
  })
  player.on('video:loadedmetadata', () => {
    playerState.value = 'ready'
    emit('time-update', player?.currentTime || 0)
  })
  player.on('video:loadeddata', renderBackdrop)
  player.on('video:canplay', renderBackdrop)
  player.on('video:error', () => {
    playerState.value = 'error'
  })
  player.on('video:timeupdate', () => {
    emit('time-update', player?.currentTime || 0)
  })
}

async function buildPreviewPoster() {
  if (!props.thumbnailVttUrl || !window.createImageBitmap) return ''
  try {
    const frames = await loadVttThumbnails(backendUrl(props.thumbnailVttUrl))
    const firstFrame = frames[0]
    if (!firstFrame) return ''
    const response = await fetch(firstFrame.url)
    if (!response.ok) return ''
    const sprite = await createImageBitmap(
      await response.blob(),
      firstFrame.x,
      firstFrame.y,
      firstFrame.width,
      firstFrame.height,
    )
    const canvas = document.createElement('canvas')
    canvas.width = 640
    canvas.height = 360
    canvas.getContext('2d')?.drawImage(sprite, 0, 0, canvas.width, canvas.height)
    sprite.close?.()
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.88))
    return blob ? URL.createObjectURL(blob) : ''
  } catch {
    return ''
  }
}

function clearBackdrop() {
  const canvas = backdropRef.value
  if (!canvas) return
  const context = canvas.getContext('2d')
  context?.clearRect(0, 0, canvas.width, canvas.height)
}

function renderBackdrop() {
  const canvas = backdropRef.value
  const video = player?.template?.$video || player?.video
  if (!canvas || !video?.videoWidth || !video?.videoHeight) return
  const width = 480
  const height = Math.max(180, Math.round(width * video.videoHeight / video.videoWidth))
  if (canvas.width !== width) canvas.width = width
  if (canvas.height !== height) canvas.height = height
  try {
    canvas.getContext('2d')?.drawImage(video, 0, 0, width, height)
  } catch {
    clearBackdrop()
  }
}

function destroyPlayer() {
  const hadPlayer = Boolean(player)
  player?.destroy(true)
  player = null
  if (posterObjectUrl) {
    URL.revokeObjectURL(posterObjectUrl)
    posterObjectUrl = ''
  }
  if (hadPlayer) emit('time-update', 0)
}

async function refreshPlayer() {
  await nextTick()
  createPlayer()
}

function seek(seconds) {
  const value = Number(seconds)
  if (!player || !Number.isFinite(value)) return
  player.currentTime = Math.max(value, 0)
  player.play?.().catch?.(() => {})
}

defineExpose({
  seek
})

onMounted(refreshPlayer)
onBeforeUnmount(() => {
  playerLoadVersion += 1
  destroyPlayer()
})

watch(
  () => [props.src, props.poster, props.thumbnailVttUrl],
  refreshPlayer
)
</script>

<style scoped>
.art-video-player {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: var(--vk-media-surface);
}

.art-video-backdrop {
  position: absolute;
  inset: -44px;
  z-index: 0;
  width: calc(100% + 88px);
  height: calc(100% + 88px);
  object-fit: cover;
  filter: blur(28px) saturate(1.12);
  opacity: 0.42;
  pointer-events: none;
  transform: scale(1.04);
}

.art-video-state {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: grid;
  place-content: center;
  gap: 10px;
  color: var(--vk-media-muted);
  font-size: 13px;
  pointer-events: none;
}

.art-video-state.is-error {
  pointer-events: auto;
}

.art-video-state button {
  justify-self: center;
  padding: 5px 12px;
  border: 1px solid var(--vk-media-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-on-media) 8%, transparent);
  color: var(--vk-on-media);
  cursor: pointer;
}

.art-video-container {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
}

.art-video-container :deep(.art-video-player),
.art-video-container :deep(.artplayer) {
  width: 100%;
  height: 100%;
  background: transparent;
}

.art-video-container :deep(.art-video) {
  object-fit: contain;
}

.art-video-container :deep(.art-bottom),
.art-video-container :deep(.art-control) {
  --art-theme: var(--vk-accent);
}
</style>
