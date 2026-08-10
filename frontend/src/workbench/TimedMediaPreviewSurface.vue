<template>
  <ArtAudioPlayer
    v-if="audio && mediaUrl"
    ref="player"
    :src="mediaUrl"
    :title="content?.title || tab.title"
    :cache-key="tab.id"
    @time-update="$emit('time-update', $event)"
    @playback-change="$emit('playback-change', $event)"
  />
  <ArtVideoPlayer
    v-else-if="mediaUrl"
    ref="player"
    :src="mediaUrl"
    :poster="content?.cover_url || ''"
    :thumbnail-vtt-url="content?.thumbnail_vtt_url || ''"
    @time-update="$emit('time-update', $event)"
  />
  <template v-else-if="content?.cover_url">
    <img class="media-cover-image" :src="content.cover_url" alt="" />
    <div v-if="videoCacheExpired" class="media-cache-expired" role="status">
      本地视频预览已于 {{ videoCacheExpiredLabel }} 清理，文本与摘要仍可阅读。
    </div>
    <div
      v-if="content?.status === 'processing'"
      class="media-preview-loader"
      role="status"
      aria-live="polite"
      aria-label="正在加载视频预览"
    >
      <span class="media-preview-spinner" aria-hidden="true"></span>
    </div>
  </template>
  <div
    v-else-if="content?.status === 'processing' && timedMedia"
    class="media-preview-loader is-empty"
    role="status"
    aria-live="polite"
    aria-label="正在加载媒体预览"
  >
    <span class="media-preview-spinner" aria-hidden="true"></span>
  </div>
  <div v-else class="media-placeholder">
    <SvgMaskIcon :src="movieClapperIcon" :size="40" />
    <span v-if="content?.content_type === 'video'">
      {{ videoCacheExpired ? '本地视频预览已过期，可从右上角“内容操作”重新下载' : '视频文件尚未缓存，可从右上角“内容操作”重新处理' }}
    </span>
  </div>
</template>

<script setup>
import { defineAsyncComponent, ref } from 'vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'

const ArtVideoPlayer = defineAsyncComponent(() => import('./ArtVideoPlayer.vue'))
const ArtAudioPlayer = defineAsyncComponent(() => import('./ArtAudioPlayer.vue'))
const movieClapperIcon = 'movieclapper'

defineProps({
  tab: { type: Object, required: true },
  content: { type: Object, default: null },
  mediaUrl: { type: String, default: '' },
  audio: { type: Boolean, default: false },
  timedMedia: { type: Boolean, default: false },
  videoCacheExpired: { type: Boolean, default: false },
  videoCacheExpiredLabel: { type: String, default: '' },
})

defineEmits(['playback-change', 'time-update'])

const player = ref(null)

function seek(seconds) {
  player.value?.seek?.(seconds)
}

function togglePlayback() {
  return player.value?.togglePlayback?.()
}

defineExpose({
  hasPlayer: () => Boolean(player.value),
  seek,
  togglePlayback,
})
</script>

<style scoped src="./timed-media-preview-surface.css"></style>
