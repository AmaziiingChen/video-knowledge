<template>
  <figure
    v-if="coverUrl"
    class="report-cover-preview"
    :class="{ 'is-generating': generating, 'is-switching': switching }"
    :aria-busy="switching ? 'true' : 'false'"
  >
    <img :src="displayUrl" :alt="`${title}封面`" />
    <template v-if="covers.length > 1">
      <button
        type="button"
        class="report-cover-arrow is-previous"
        title="上一张封面"
        aria-label="上一张封面"
        :disabled="!previousCover"
        @click="select(previousCover)"
      >
        <el-icon><ArrowLeft /></el-icon>
      </button>
      <button
        type="button"
        class="report-cover-arrow is-next"
        title="下一张封面"
        aria-label="下一张封面"
        :disabled="!nextCover"
        @click="select(nextCover)"
      >
        <el-icon><ArrowRight /></el-icon>
      </button>
      <span class="report-cover-count" aria-live="polite">
        {{ activeIndex + 1 }} / {{ covers.length }}
      </span>
    </template>
    <figcaption v-if="generating">
      正在重新生成封面，当前图片会保留到新版本完成
    </figcaption>
  </figure>
  <div
    v-else-if="generating"
    class="report-cover-preview is-empty is-generating"
    role="status"
  >
    正在生成公众号封面…
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowLeft, ArrowRight } from '../components/macosSymbolComponents.js'
import {
  adjacentReportCover,
  reportCoverIndex,
  reportCoverUrl,
  reportCoverVersions,
} from './reportCoverPresentation.js'

const props = defineProps({
  contentItemId: { type: String, required: true },
  title: { type: String, default: '报告' },
  coverUrl: { type: String, default: '' },
  history: { type: Object, default: () => ({ active_cover_id: '', covers: [] }) },
  generating: { type: Boolean, default: false },
  switching: { type: Boolean, default: false },
})

const emit = defineEmits(['select'])
const covers = computed(() => reportCoverVersions(props.history))
const activeIndex = computed(() => reportCoverIndex(props.history))
const displayUrl = computed(() => reportCoverUrl(props.history, props.coverUrl))
const busy = computed(() => props.generating || props.switching)
const previousCover = computed(() => adjacentReportCover(props.history, -1, { busy: busy.value }))
const nextCover = computed(() => adjacentReportCover(props.history, 1, { busy: busy.value }))

function select(cover) {
  if (!cover?.id || !props.contentItemId) return
  emit('select', { contentItemId: props.contentItemId, coverId: cover.id })
}
</script>

<style scoped>
.report-cover-preview {
  position: relative;
  display: grid;
  width: 100%;
  aspect-ratio: 900 / 383;
  margin: 0 0 28px;
  overflow: hidden;
  border: 1px solid var(--vk-divider-subtle);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-center);
}

.report-cover-preview img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.report-cover-arrow,
.report-cover-count {
  position: absolute;
  z-index: 1;
  opacity: 0;
  transition: opacity var(--vk-motion-fast) var(--vk-ease-out);
}

.report-cover-arrow {
  top: 50%;
  display: grid;
  width: 34px;
  height: 34px;
  padding: 0;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--vk-action-fg) 36%, transparent);
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-text) 76%, transparent);
  color: var(--vk-action-fg);
  cursor: pointer;
  transform: translateY(-50%);
}

.report-cover-arrow.is-previous { left: var(--vk-space-cluster); }
.report-cover-arrow.is-next { right: var(--vk-space-cluster); }

.report-cover-arrow:focus-visible {
  opacity: 1;
  outline: none;
  box-shadow: var(--vk-focus-ring);
}

.report-cover-arrow:disabled { cursor: default; }

.report-cover-count {
  right: var(--vk-space-cluster);
  top: var(--vk-space-cluster);
  padding: var(--vk-space-xs) var(--vk-space-control);
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-text) 72%, transparent);
  color: var(--vk-action-fg);
  font-size: var(--vk-type-meta-size);
  line-height: var(--vk-leading-label);
}

.report-cover-preview:hover .report-cover-arrow,
.report-cover-preview:hover .report-cover-count,
.report-cover-preview:focus-within .report-cover-arrow,
.report-cover-preview:focus-within .report-cover-count { opacity: 1; }

.report-cover-preview:hover .report-cover-arrow:disabled,
.report-cover-preview:focus-within .report-cover-arrow:disabled { opacity: 0.34; }
.report-cover-preview.is-switching img { opacity: 0.72; }

.report-cover-preview.is-empty {
  place-items: center;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
}

.report-cover-preview figcaption {
  position: absolute;
  right: var(--vk-space-cluster);
  bottom: var(--vk-space-cluster);
  left: var(--vk-space-cluster);
  padding: var(--vk-space-control) var(--vk-space-cluster);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-text) 82%, transparent);
  color: var(--vk-action-fg);
  font-size: var(--vk-type-meta-size);
  line-height: var(--vk-leading-label);
  text-align: center;
}

@media (hover: none) {
  .report-cover-arrow,
  .report-cover-count { opacity: 1; }
  .report-cover-arrow:disabled { opacity: 0.34; }
}
</style>
