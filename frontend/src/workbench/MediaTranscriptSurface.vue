<template>
  <div
    class="media-transcript-splitter"
    role="separator"
    tabindex="0"
    aria-orientation="horizontal"
    aria-label="调整视频与字幕高度"
    :aria-valuemin="Math.round(bounds.min)"
    :aria-valuemax="Math.round(bounds.max)"
    :aria-valuenow="height"
    @pointerdown="$emit('resize-start', $event)"
    @keydown="$emit('resize-keydown', $event)"
  ></div>
  <section
    class="transcript-timeline"
    :class="{ 'is-generating': generating }"
    :aria-busy="generating"
    @wheel.passive="$emit('pause-auto-follow')"
    @touchstart.passive="$emit('pause-auto-follow')"
  >
    <div v-if="generating" class="transcript-generation" role="status" aria-live="polite">
      <div class="transcript-generation-heading">
        <span class="transcript-generation-pulse" aria-hidden="true"></span>
        <div>
          <strong>{{ generationLabel }}</strong>
          <small>{{ generationDescription }}</small>
        </div>
      </div>
      <div class="transcript-generation-lines" aria-hidden="true">
        <div class="transcript-generation-line is-wide"><span>··:··</span><i></i></div>
        <div class="transcript-generation-line is-medium"><span>··:··</span><i></i></div>
        <div class="transcript-generation-line is-long"><span>··:··</span><i></i></div>
        <div class="transcript-generation-line is-short"><span>··:··</span><i></i></div>
      </div>
    </div>
    <template v-else>
      <button
        v-if="!autoFollow"
        class="transcript-follow-button"
        type="button"
        title="回到当前进度"
        aria-label="回到当前进度"
        @click="$emit('resume-auto-follow')"
      >
        <el-icon><Aim /></el-icon>
      </button>
      <button
        v-for="segment in segments"
        :key="segment.position"
        :ref="(element) => $emit('segment-ref', { segment, element })"
        class="timeline-segment"
        type="button"
        :class="{
          approximate: segment.approximate,
          'is-active': segmentActive(segment),
        }"
        :data-start-seconds="segment.start_seconds"
        @click="$emit('select-segment', segment)"
      >
        <span class="timeline-time">{{ formatTimelineTime(segment.start_seconds) }}</span>
        <span class="timeline-text">{{ segment.text }}</span>
      </button>
    </template>
  </section>
</template>

<script setup>
import { Aim } from '@element-plus/icons-vue'
import { formatTimelineTime } from './mediaTranscriptModel.js'

defineProps({
  height: { type: Number, required: true },
  bounds: { type: Object, required: true },
  generating: { type: Boolean, default: false },
  generationLabel: { type: String, default: '' },
  generationDescription: { type: String, default: '' },
  autoFollow: { type: Boolean, default: true },
  segments: { type: Array, default: () => [] },
  segmentActive: { type: Function, required: true },
})

defineEmits([
  'pause-auto-follow',
  'resize-keydown',
  'resize-start',
  'resume-auto-follow',
  'segment-ref',
  'select-segment',
])
</script>

<style scoped src="./media-transcript-surface.css"></style>
