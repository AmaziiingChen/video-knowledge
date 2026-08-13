<template>
  <article
    class="article-reader article-snapshot-reader"
    :class="{
      'remote-wechat-active': remoteVisible,
      'local-html-source-active': localHtml,
    }"
  >
    <div class="article-reader-inner article-reader-snapshot-inner">
      <div class="article-reader-head">
        <div class="article-reader-heading">
          <h2>{{ content?.title || tab.title }}</h2>
        </div>
      </div>
      <p class="article-preview-meta">
        <span>{{ content?.source_name || preview?.author || sourceLabel }}</span>
        <span v-if="content?.source_section">{{ content.source_section }}</span>
        <span v-if="preview?.published_at || content?.published_at">{{ preview?.published_at || content?.published_at }}</span>
        <span v-if="['queued', 'running'].includes(preview?.formatting_status)">{{ preview?.formatting_detail || '正在整理 OCR 文档版式…' }}</span>
        <span v-else-if="wechatArticle && remoteStatus === 'loading'">正在打开公众号原页面…</span>
        <span v-else-if="wechatArticle && remoteStatus === 'failed'">原页面未加载，正在显示缓存正文</span>
      </p>
      <template v-if="preview?.html">
        <ArticlePreviewFrame
          ref="previewFrame"
          :srcdoc="articleHtml"
          :hidden="remoteVisible || localHtmlRemoteVisible"
          :local-html-original="localHtml"
          :title="frameTitle"
          @ready="handleFrameReady"
          @open-find="$emit('open-find')"
          @open-external-link="$emit('open-external-link', $event)"
        />
        <ReportOutlineRail
          v-if="outlineRoot && !remoteVisible && !localHtml"
          :scroll-root="previewFrame?.getFrame?.() || null"
          :content-root="outlineRoot"
          :content-version="articleHtml"
          :report-key="tab.id"
          :heading-selector="articleOutlineHeadingSelector"
          :entry-filter="isArticleOutlineHeading"
          :entry-level="articleOutlineHeadingLevel"
        />
      </template>
      <div v-else-if="shouldShowArticlePreviewLoader(preview)" class="campus-article-loading">
        <span></span><span></span><span></span>
        <p>{{ preview?.loading_label || '正在读取本地正文快照…' }}</p>
      </div>
      <div v-else-if="preview?.loading" class="article-preview-silent-loading" aria-busy="true"></div>
      <div v-else class="article-preview-body" :class="{ 'campus-article-placeholder': isCampus && !articleText }">
        {{ fallbackText }}
      </div>
      <section v-if="attachments.length" class="article-attachment-shelf" aria-label="文章附件">
        <div class="article-attachment-head">
          <strong>附件</strong>
          <span>{{ attachments.length }} 个文件</span>
        </div>
        <button
          v-for="attachment in attachments"
          :key="attachment.url"
          class="article-attachment-row"
          type="button"
          @click="$emit('open-campus-attachment', attachment)"
        >
          <span class="article-attachment-name">{{ attachment.name }}</span>
          <span class="article-attachment-action">{{ attachment.download_type === 'direct' ? '下载' : '打开并验证' }}</span>
        </button>
      </section>
    </div>
  </article>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { shouldShowArticlePreviewLoader } from '../features/library/articlePreviewLoadState.js'
import {
  articleOutlineHeadingSelector,
  createArticleOutlineModel,
} from './articleOutlineModel.js'
import ArticlePreviewFrame from './ArticlePreviewFrame.vue'
import ReportOutlineRail from './ReportOutlineRail.vue'

const props = defineProps({
  tab: { type: Object, required: true },
  content: { type: Object, default: null },
  preview: { type: Object, default: null },
  articleHtml: { type: String, default: '' },
  articleText: { type: String, default: '' },
  sourceLabel: { type: String, default: '' },
  attachments: { type: Array, default: () => [] },
  isCampus: { type: Boolean, default: false },
  wechatArticle: { type: Boolean, default: false },
  remoteStatus: { type: String, default: '' },
  remoteVisible: { type: Boolean, default: false },
  localHtml: { type: Boolean, default: false },
  localHtmlRemoteVisible: { type: Boolean, default: false },
  originalPageUrl: { type: String, default: '' },
})

const emit = defineEmits([
  'open-campus-attachment',
  'open-external-link',
  'open-find',
  'preview-frame-ready',
])

const previewFrame = ref(null)
const outlineRoot = ref(null)
const {
  articleOutlineHeadingLevel,
  isArticleOutlineHeading,
} = createArticleOutlineModel({
  activeArticleTitle: () => props.content?.title || props.tab.title,
})
const frameTitle = computed(() => {
  if (props.originalPageUrl) return '原始网页预览'
  if (props.localHtml) return '原始网页安全快照'
  return '文章正文快照'
})
const fallbackText = computed(() => (
  props.articleText
  || props.preview?.error
  || (props.isCampus
    ? '文章元数据已保存。正文会在打开、分析或提问时读取；如未自动加载，可点击右上角“获取正文”。'
    : '正文已保存，选择右侧总结继续追问。')
))

function handleFrameReady(frameDocument) {
  outlineRoot.value = frameDocument?.body || null
  emit('preview-frame-ready', frameDocument)
}

watch(() => props.articleHtml, (value) => {
  if (!value) outlineRoot.value = null
})

defineExpose({
  getPreviewFrame: () => previewFrame.value?.getFrame?.() || null,
})
</script>

<style scoped src="./article-reader-surface.css"></style>
