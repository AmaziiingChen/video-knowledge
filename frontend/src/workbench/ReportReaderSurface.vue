<template>
  <article
    ref="scrollRoot"
    class="article-reader report-reader"
    :class="{ 'capture-reader': isCapture }"
    @scroll.passive="$emit('scroll', $event)"
  >
    <div
      class="article-reader-inner report-reader-inner"
      :class="{ 'capture-reader-inner': isCapture }"
    >
      <div
        class="article-reader-head"
        :class="isCapture ? 'capture-reader-head' : 'report-reader-head'"
      >
        <div :class="isCapture ? 'article-reader-heading' : 'report-reader-heading'">
          <span v-if="isCapture" class="capture-reader-kicker">小程序采集</span>
          <h2>{{ heading }}</h2>
          <p :class="isCapture ? 'capture-reader-meta' : 'report-reader-meta'">
            <template v-if="isCapture">
              <span>{{ content?.source_name || '校园论坛' }}</span>
              <span v-if="content?.source_section">{{ content.source_section }}</span>
              <span v-if="content?.published_at">采集于 {{ formatDateTime(content.published_at) }}</span>
            </template>
            <template v-else-if="isExternalMarkdown">
              <span>外部导入</span>
              <span>{{ externalImportKindLabel }}</span>
              <span v-if="content?.created_at">导入于 {{ formatDateTime(content.created_at) }}</span>
            </template>
            <template v-else>
              <span>{{ reportDateLabel }}</span>
              <span v-if="reportGeneratedLabel">{{ reportGeneratedLabel }}</span>
              <span v-if="sourceStats.analyzed">分析 {{ sourceStats.analyzed }} 篇文章</span>
              <span v-if="sourceStats.analyzed || sourceStats.referenced">
                正文引用 {{ sourceStats.referenced }} 篇文章
              </span>
            </template>
          </p>
        </div>
      </div>
      <ReportCoverPreview
        v-if="isReport"
        :content-item-id="String(content?.id || '')"
        :title="reportDisplayTitle"
        :cover-url="content?.cover_url || ''"
        :history="coverHistory"
        :generating="coverGenerating"
        :switching="coverSwitching"
        @select="$emit('select-cover', $event)"
      />
      <div
        v-if="markdownHtml"
        ref="contentRoot"
        class="report-markdown vk-prose"
        :class="{ 'capture-markdown': isCapture }"
        v-html="markdownHtml"
        @click="isCapture ? undefined : handleFootnoteClick($event)"
        @pointerover="isCapture ? undefined : positionFootnotePreview($event)"
        @focusin="isCapture ? undefined : positionFootnotePreview($event)"
      ></div>
      <div v-else class="article-preview-body">{{ loadingLabel }}</div>
    </div>
    <ReportOutlineRail
      :scroll-root="scrollRoot"
      :content-root="contentRoot"
      :content-version="markdownHtml"
      :report-key="tab.id"
    />
    <Transition name="report-footnote-return">
      <button
        v-if="hasFootnoteReturn"
        class="report-footnote-return"
        type="button"
        aria-label="返回引用位置"
        title="返回引用位置"
        @click="returnToFootnoteReference"
      >
        <el-icon><ArrowUp /></el-icon>
        <span>返回引用处</span>
      </button>
    </Transition>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowUp } from '../components/macosSymbolComponents.js'
import { useMarkdownFootnoteNavigation } from '../composables/useMarkdownFootnoteNavigation'
import ReportCoverPreview from './ReportCoverPreview.vue'
import ReportOutlineRail from './ReportOutlineRail.vue'

const props = defineProps({
  mode: { type: String, required: true, validator: (value) => ['capture', 'report', 'markdown'].includes(value) },
  tab: { type: Object, required: true },
  content: { type: Object, default: null },
  markdownHtml: { type: String, default: '' },
  sourceStats: { type: Object, default: () => ({ analyzed: 0, referenced: 0 }) },
  reportDisplayTitle: { type: String, default: '' },
  reportDateLabel: { type: String, default: '' },
  reportGeneratedLabel: { type: String, default: '' },
  externalImportKindLabel: { type: String, default: '' },
  coverHistory: { type: Object, default: () => ({ active_cover_id: '', covers: [] }) },
  coverGenerating: { type: Boolean, default: false },
  coverSwitching: { type: Boolean, default: false },
  formatDateTime: { type: Function, required: true },
})

defineEmits(['scroll', 'select-cover'])

const scrollRoot = ref(null)
const contentRoot = ref(null)
const isCapture = computed(() => props.mode === 'capture')
const isReport = computed(() => props.mode === 'report')
const isExternalMarkdown = computed(() => props.mode === 'markdown')
const heading = computed(() => {
  if (isReport.value) return props.reportDisplayTitle
  return props.content?.title || props.tab.title || ''
})
const loadingLabel = computed(() => {
  if (isCapture.value) return '正在载入采集记录…'
  if (isExternalMarkdown.value) return '正在载入 Markdown 内容…'
  return '正在载入报告内容…'
})
const {
  handleFootnoteClick,
  hasFootnoteReturn,
  positionFootnotePreview,
  returnToFootnoteReference,
} = useMarkdownFootnoteNavigation({
  scrollRoot,
  scopeKey: () => props.tab.id,
})

function focusReader() {
  const reader = scrollRoot.value
  if (!(reader instanceof HTMLElement)) return false
  reader.focus?.({ preventScroll: true })
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  reader.scrollTo?.({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
  return true
}

defineExpose({
  focusReader,
  getContentRoot: () => contentRoot.value,
  getScrollRoot: () => scrollRoot.value,
})
</script>

<style scoped src="./report-reader-surface.css"></style>
