<template>
  <section class="main-canvas">
    <div
      v-if="activeView === 'library'"
      class="workbench-editor-host"
      :class="{ 'no-editor-tabs': !workspaceTabs.length }"
    >
      <WorkspaceTabs
        v-if="workspaceTabs.length"
        :tabs="workspaceTabs"
        :active-tab-id="activeWorkspaceTab?.id || ''"
        allow-reveal
        allow-delete
        @activate="$emit('activate-workspace-tab', $event)"
        @close="$emit('close-workspace-tab', $event)"
        @close-tabs="$emit('close-workspace-tabs', $event)"
        @reveal-tab="$emit('reveal-workspace-tab', $event)"
        @delete-tab="$emit('delete-workspace-tab', $event)"
      />

          <section
            class="content-workspace tab-content-workspace"
            :class="{
              'article-mode': activeContentTab && isArticleTab(activeContentTab.id),
              'report-mode': activeContentTab && isLongformReaderTab(activeContentTab.id),
              'image-mode': activeContentTab && isExternalImageTab(activeContentTab.id),
              'pdf-mode': activeContentTab && isExternalPdfTab(activeContentTab.id),
              'capture-mode': activeContentTab && isMiniProgramCaptureTab(activeContentTab.id),
              'preview-find-open': previewFindOpen
            }"
          >
            <Transition name="content-detail" mode="out-in">
            <div
              v-if="activeContentTab"
              :key="activeContentTab.id"
              ref="contentHero"
              class="content-hero"
              tabindex="-1"
              :class="{
                'media-transcript-layout': hasTranscriptTimeline(activeContentTab.id),
                'xhs-image-text-layout': hasXhsImageTextLayout(activeContentTab.id),
                'is-resizing-media': mediaTranscriptResizing,
                'is-resizing-xhs': xhsImageTextResizing,
              }"
              :style="contentHeroLayoutStyle(activeContentTab.id)"
            >
              <div
                class="content-media-frame"
                :class="{
                  'article-frame': isArticleTab(activeContentTab.id),
                  'report-frame': isLongformReaderTab(activeContentTab.id),
                  'video-frame': isVideoTab(activeContentTab.id),
                  'audio-frame': isAudioTab(activeContentTab.id),
                  'image-frame': isExternalImageTab(activeContentTab.id),
                  'pdf-frame': isExternalPdfTab(activeContentTab.id),
                  'capture-frame': isMiniProgramCaptureTab(activeContentTab.id),
                }"
              >
                <article
                  v-if="isMiniProgramCaptureTab(activeContentTab.id)"
                  ref="reportReader"
                  class="article-reader capture-reader"
                  @scroll.passive="handleReadingScroll"
                >
                  <div class="article-reader-inner report-reader-inner capture-reader-inner">
                    <div class="article-reader-head capture-reader-head">
                      <div class="article-reader-heading">
                        <span class="capture-reader-kicker">小程序采集</span>
                        <h2>{{ contentForTab(activeContentTab.id)?.title || activeContentTab.title }}</h2>
                        <p class="capture-reader-meta">
                          <span>{{ contentForTab(activeContentTab.id)?.source_name || '校园论坛' }}</span>
                          <span v-if="contentForTab(activeContentTab.id)?.source_section">{{ contentForTab(activeContentTab.id).source_section }}</span>
                          <span v-if="contentForTab(activeContentTab.id)?.published_at">采集于 {{ formatDateTime(contentForTab(activeContentTab.id).published_at) }}</span>
                        </p>
                      </div>
                    </div>
                    <div
                      v-if="selectedMarkdownPreview"
                      ref="reportMarkdown"
                      class="report-markdown vk-prose capture-markdown"
                      v-html="selectedMarkdownPreview"
                    ></div>
                    <div v-else class="article-preview-body">正在载入采集记录…</div>
                  </div>
                  <ReportOutlineRail
                    :scroll-root="reportReader"
                    :content-root="reportMarkdown"
                    :content-version="selectedMarkdownPreview"
                    :report-key="activeContentTab.id"
                  />
                </article>
                <article
                  v-else-if="isReportTab(activeContentTab.id) || isExternalMarkdownTab(activeContentTab.id)"
                  ref="reportReader"
                  class="article-reader report-reader"
                  @scroll.passive="handleReadingScroll"
                >
                  <div class="article-reader-inner report-reader-inner">
                    <div class="article-reader-head report-reader-head">
                      <div class="report-reader-heading">
                        <h2>{{ isExternalMarkdownTab(activeContentTab.id) ? contentForTab(activeContentTab.id)?.title || activeContentTab.title : reportDisplayTitle(activeContentTab.id) }}</h2>
                        <p class="report-reader-meta">
                          <template v-if="isExternalMarkdownTab(activeContentTab.id)">
                            <span>外部导入</span>
                            <span>{{ externalImportKindLabel(activeContentTab.id) }}</span>
                            <span v-if="contentForTab(activeContentTab.id)?.created_at">导入于 {{ formatDateTime(contentForTab(activeContentTab.id).created_at) }}</span>
                          </template>
                          <template v-else>
                            <span>{{ reportDateLabel(activeContentTab.id) }}</span>
                            <span v-if="reportGeneratedLabel(activeContentTab.id)">{{ reportGeneratedLabel(activeContentTab.id) }}</span>
                            <span v-if="selectedReportSourceStats.analyzed">分析 {{ selectedReportSourceStats.analyzed }} 篇文章</span>
                            <span v-if="selectedReportSourceStats.analyzed || selectedReportSourceStats.referenced">
                              正文引用 {{ selectedReportSourceStats.referenced }} 篇文章
                            </span>
                          </template>
                        </p>
                      </div>
                    </div>
                    <figure
                      v-if="isReportTab(activeContentTab.id) && contentForTab(activeContentTab.id)?.cover_url"
                      class="report-cover-preview"
                      :class="{
                        'is-generating': isWechatCoverGenerating(activeContentTab.id),
                        'is-switching': isWechatCoverSwitching(activeContentTab.id),
                      }"
                      :aria-busy="isWechatCoverSwitching(activeContentTab.id) ? 'true' : 'false'"
                    >
                      <img
                        :src="reportCoverUrlForTab(activeContentTab.id)"
                        :alt="`${reportDisplayTitle(activeContentTab.id)}封面`"
                      />
                      <template v-if="reportCoverVersionsForTab(activeContentTab.id).length > 1">
                        <button
                          type="button"
                          class="report-cover-arrow is-previous"
                          title="上一张封面"
                          aria-label="上一张封面"
                          :disabled="!canNavigateReportCover(activeContentTab.id, -1)"
                          @click="selectAdjacentReportCover(activeContentTab.id, -1)"
                        >
                          <el-icon><ArrowLeft /></el-icon>
                        </button>
                        <button
                          type="button"
                          class="report-cover-arrow is-next"
                          title="下一张封面"
                          aria-label="下一张封面"
                          :disabled="!canNavigateReportCover(activeContentTab.id, 1)"
                          @click="selectAdjacentReportCover(activeContentTab.id, 1)"
                        >
                          <el-icon><ArrowRight /></el-icon>
                        </button>
                        <span class="report-cover-count" aria-live="polite">
                          {{ reportCoverIndexForTab(activeContentTab.id) + 1 }}
                          /
                          {{ reportCoverVersionsForTab(activeContentTab.id).length }}
                        </span>
                      </template>
                      <figcaption v-if="isWechatCoverGenerating(activeContentTab.id)">
                        正在重新生成封面，当前图片会保留到新版本完成
                      </figcaption>
                    </figure>
                    <div
                      v-else-if="isReportTab(activeContentTab.id) && isWechatCoverGenerating(activeContentTab.id)"
                      class="report-cover-preview is-empty is-generating"
                      role="status"
                    >
                      正在生成公众号封面…
                    </div>
                    <div
                      v-if="selectedMarkdownPreview"
                      ref="reportMarkdown"
                      class="report-markdown vk-prose"
                      v-html="selectedMarkdownPreview"
                      @click="handleReportFootnoteClick"
                      @pointerover="positionFootnotePreview"
                      @focusin="positionFootnotePreview"
                    ></div>
                    <div v-else class="article-preview-body">{{ isExternalMarkdownTab(activeContentTab.id) ? '正在载入 Markdown 内容…' : '正在载入报告内容…' }}</div>
                  </div>
                  <ReportOutlineRail
                    :scroll-root="reportReader"
                    :content-root="reportMarkdown"
                    :content-version="selectedMarkdownPreview"
                    :report-key="activeContentTab.id"
                  />
                </article>
                <article v-else-if="isExternalPdfTab(activeContentTab.id)" class="pdf-reader" aria-label="PDF 原件预览">
                  <iframe
                    v-if="originalMediaUrlForTab(activeContentTab.id)"
                    class="pdf-preview-frame"
                    :src="originalMediaUrlForTab(activeContentTab.id)"
                    :title="`${contentForTab(activeContentTab.id)?.title || '导入 PDF'}原件`"
                  ></iframe>
                  <div v-else class="article-preview-body">正在打开 PDF 原件…</div>
                </article>
                <article v-else-if="isExternalImageTab(activeContentTab.id)" class="image-reader" aria-label="原图预览">
                  <figure class="image-reader-figure">
                    <img
                      v-if="originalMediaUrlForTab(activeContentTab.id)"
                      :src="originalMediaUrlForTab(activeContentTab.id)"
                      :alt="contentForTab(activeContentTab.id)?.title || '导入图片'"
                    />
                  </figure>
                </article>
                <article
                  v-else-if="hasXhsImageTextLayout(activeContentTab.id)"
                  class="xhs-image-reader"
                  aria-label="小红书图文图片"
                >
                  <div
                    ref="xhsGalleryTrack"
                    class="xhs-gallery-track"
                    tabindex="0"
                    aria-label="小红书笔记图片，可左右滚动或使用左右方向键切换"
                    @keydown="handleXhsGalleryKeydown"
                    @scroll.passive="syncXhsGalleryPosition"
                  >
                    <figure
                      v-for="image in articlePreviewForTab(activeContentTab.id).gallery"
                      :key="image.index"
                      class="xhs-gallery-slide"
                    >
                      <img :src="image.url" :alt="`笔记图片 ${image.index}`" loading="lazy" />
                    </figure>
                  </div>
                  <template v-if="xhsGalleryImageCount(activeContentTab.id) > 1">
                    <button
                      class="xhs-gallery-arrow is-previous"
                      type="button"
                      title="上一张图片"
                      aria-label="上一张图片"
                      :disabled="!canNavigateXhsGallery(activeContentTab.id, -1)"
                      @click.stop="scrollXhsGallery(-1)"
                    >
                      <el-icon><ArrowLeft /></el-icon>
                    </button>
                    <button
                      class="xhs-gallery-arrow is-next"
                      type="button"
                      title="下一张图片"
                      aria-label="下一张图片"
                      :disabled="!canNavigateXhsGallery(activeContentTab.id, 1)"
                      @click.stop="scrollXhsGallery(1)"
                    >
                      <el-icon><ArrowRight /></el-icon>
                    </button>
                    <span class="xhs-gallery-count" aria-live="polite">
                      {{ xhsGalleryIndex + 1 }} / {{ xhsGalleryImageCount(activeContentTab.id) }}
                    </span>
                  </template>
                </article>
                <template v-else-if="isArticleTab(activeContentTab.id)">
                <article
                  class="article-reader article-snapshot-reader"
                  :class="{
                    'remote-wechat-active': isWechatRemoteVisible,
                    'local-html-source-active': isLocalHtmlArticleTab(activeContentTab.id),
                  }"
                >
                  <div class="article-reader-inner article-reader-snapshot-inner">
                    <div class="article-reader-head">
                      <div class="article-reader-heading">
                        <h2>{{ contentForTab(activeContentTab.id)?.title || activeContentTab.title }}</h2>
                      </div>
                    </div>
                    <p class="article-preview-meta">
                      <span>{{ contentForTab(activeContentTab.id)?.source_name || articlePreviewForTab(activeContentTab.id)?.author || sourceProviderLabel(contentForTab(activeContentTab.id)?.source_provider) }}</span>
                      <span v-if="contentForTab(activeContentTab.id)?.source_section">{{ contentForTab(activeContentTab.id).source_section }}</span>
                      <span v-if="articlePreviewForTab(activeContentTab.id)?.published_at || contentForTab(activeContentTab.id)?.published_at">{{ articlePreviewForTab(activeContentTab.id)?.published_at || contentForTab(activeContentTab.id)?.published_at }}</span>
                      <span v-if="['queued', 'running'].includes(articlePreviewForTab(activeContentTab.id)?.formatting_status)">{{ articlePreviewForTab(activeContentTab.id)?.formatting_detail || '正在整理 OCR 文档版式…' }}</span>
                      <span v-else-if="isWechatArticleTab(activeContentTab.id) && activeWechatRemotePage?.status === 'loading'">正在打开公众号原页面…</span>
                      <span v-else-if="isWechatArticleTab(activeContentTab.id) && activeWechatRemotePage?.status === 'failed'">原页面未加载，正在显示缓存正文</span>
                    </p>
                    <template v-if="articlePreviewForTab(activeContentTab.id)?.html">
                      <iframe
                        ref="activeArticlePreviewFrame"
                        class="article-preview-frame"
                        :class="{
                          'is-hidden': isWechatRemoteVisible || isLocalHtmlRemoteVisible,
                          'local-html-original-frame': isLocalHtmlArticleTab(activeContentTab.id),
                        }"
                        :srcdoc="articlePreviewHtml(activeContentTab.id)"
                        sandbox="allow-same-origin"
                        referrerpolicy="no-referrer"
                        :title="localHtmlOriginalPageUrl(activeContentTab.id) ? '原始网页预览' : (isLocalHtmlArticleTab(activeContentTab.id) ? '原始网页安全快照' : '文章正文快照')"
                        @load="handleArticlePreviewFrameReady"
                      ></iframe>
                      <ReportOutlineRail
                        v-if="articleOutlineRoot && !isWechatRemoteVisible && !isLocalHtmlArticleTab(activeContentTab.id)"
                        :scroll-root="activeArticlePreviewFrame"
                        :content-root="articleOutlineRoot"
                        :content-version="articlePreviewHtml(activeContentTab.id)"
                        :report-key="activeContentTab.id"
                        :heading-selector="articleOutlineHeadingSelector"
                        :entry-filter="isArticleOutlineHeading"
                        :entry-level="articleOutlineHeadingLevel"
                      />
                    </template>
                    <div
                      v-else-if="shouldShowArticlePreviewLoader(articlePreviewForTab(activeContentTab.id))"
                      class="campus-article-loading"
                    >
                      <span></span><span></span><span></span>
                      <p>{{ articlePreviewForTab(activeContentTab.id)?.loading_label || '正在读取本地正文快照…' }}</p>
                    </div>
                    <div
                      v-else-if="articlePreviewForTab(activeContentTab.id)?.loading"
                      class="article-preview-silent-loading"
                      aria-busy="true"
                    ></div>
                    <div v-else class="article-preview-body" :class="{ 'campus-article-placeholder': isCampusArticleTab(activeContentTab.id) && !articleTextForTab(activeContentTab.id) }">
                      {{ articleTextForTab(activeContentTab.id) || articlePreviewForTab(activeContentTab.id)?.error || (isCampusArticleTab(activeContentTab.id) ? '文章元数据已保存。正文会在打开、分析或提问时读取；如未自动加载，可点击右上角“获取正文”。' : '正文已保存，选择右侧总结继续追问。') }}
                    </div>
                    <section v-if="articleAttachmentsForTab(activeContentTab.id).length" class="article-attachment-shelf" aria-label="文章附件">
                      <div class="article-attachment-head">
                        <strong>附件</strong>
                        <span>{{ articleAttachmentsForTab(activeContentTab.id).length }} 个文件</span>
                      </div>
                      <button
                        v-for="attachment in articleAttachmentsForTab(activeContentTab.id)"
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
                <template v-else-if="isAudioTab(activeContentTab.id) && mediaUrlForTab(activeContentTab.id)">
                  <ArtAudioPlayer
                    ref="activePlayer"
                    :src="mediaUrlForTab(activeContentTab.id)"
                    :title="contentForTab(activeContentTab.id)?.title || activeContentTab.title"
                    :cache-key="activeContentTab.id"
                    @time-update="handlePlayerTimeUpdate"
                    @playback-change="handleAudioPlaybackChange"
                  />
                </template>
                <template v-else-if="mediaUrlForTab(activeContentTab.id)">
                  <ArtVideoPlayer
                    ref="activePlayer"
	                    :src="mediaUrlForTab(activeContentTab.id)"
	                    :poster="contentForTab(activeContentTab.id)?.cover_url || ''"
	                    :thumbnail-vtt-url="contentForTab(activeContentTab.id)?.thumbnail_vtt_url || ''"
	                    @time-update="handlePlayerTimeUpdate"
	                  />
                </template>
                <template v-else-if="contentForTab(activeContentTab.id)?.cover_url">
                  <img
                    :src="contentForTab(activeContentTab.id).cover_url"
                    alt=""
                  />
                  <div v-if="isVideoCacheExpired(activeContentTab.id)" class="media-cache-expired" role="status">
                    本地视频预览已于 {{ formatDateTime(contentForTab(activeContentTab.id)?.video_cache_expired_at) }} 清理，文本与摘要仍可阅读。
                  </div>
                  <div
                    v-if="contentForTab(activeContentTab.id)?.status === 'processing'"
                    class="media-processing-state"
                    aria-live="polite"
                  >
                    <span class="media-processing-spinner" aria-hidden="true"></span>
                    <strong>正在处理视频</strong>
                    <small>{{ processingStageDescription(activeContentTab.id) }}</small>
                    <ol class="media-processing-stages" aria-label="视频处理阶段">
                      <li v-for="stage in processingStages(activeContentTab.id)" :key="stage.key" :class="`is-${stage.status}`">
                        <span aria-hidden="true"></span>{{ stage.label }}
                      </li>
                    </ol>
                  </div>
                </template>
                <div v-else class="media-placeholder">
                  <SvgMaskIcon :src="movieClapperIcon" :size="40" />
                  <span v-if="contentForTab(activeContentTab.id)?.content_type === 'video'">
                    {{ isVideoCacheExpired(activeContentTab.id) ? '本地视频预览已过期，可从右上角“内容操作”重新下载' : '视频文件尚未缓存，可从右上角“内容操作”重新处理' }}
                  </span>
                </div>

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

                <div
                  class="content-overlay-actions"
                >
                  <ReadingProgressControl
                    v-if="showReadingProgress"
                    class="content-overlay-secondary-action"
                    :class="{ 'is-suppressed': previewFindOpen }"
                    :progress="activeReadingProgress"
                    :character-count="activeReadingCharacterCount"
                    :remaining-minutes="estimatedRemainingReadingMinutes"
                  />
                  <PreviewFindBar
                    :available="Boolean(activeContentTab)"
                    :open="previewFindOpen && Boolean(activeContentTab)"
                    :query="previewFindQuery"
                    :match-count="previewFindMatchCount"
                    :active-match-index="previewFindActiveIndex"
                    :truncated="previewFindTruncated"
                    :focus-request="previewFindFocusRequest"
                    @update:query="updatePreviewFindQuery"
                    @previous="navigatePreviewFind(-1)"
                    @next="navigatePreviewFind(1)"
                    @open="openPreviewFind"
                    @close="closePreviewFind"
                  />
                  <div
                    class="content-overlay-secondary-actions"
                    :class="{ 'is-suppressed': previewFindOpen }"
                  >
                  <button
                    v-if="isAudioTab(activeContentTab.id)"
                    class="content-fact-button"
                    type="button"
                    :aria-label="isAudioPlaying ? '暂停音频' : '播放音频'"
                    :title="isAudioPlaying ? '暂停音频' : '播放音频'"
                    @click="toggleActiveAudioPlayback"
                  >
                    <SvgMaskIcon :src="isAudioPlaying ? pauseFillIcon : playFillIcon" :size="15" />
                  </button>
                  <el-popover
                    v-model:visible="contentActionsOpen"
                    placement="bottom-end"
                    :width="320"
                    trigger="hover"
                    :show-after="90"
                    :hide-after="180"
                    :show-arrow="false"
                    transition="content-action-pop"
                    popper-class="content-action-popover"
                  >
                    <template #reference>
                      <button class="content-fact-button" type="button" aria-label="内容操作">
                        <SvgMaskIcon :src="ellipsisIcon" :size="15" />
                      </button>
                    </template>
                    <div class="content-action-menu">
                      <div class="content-action-menu-heading">内容操作</div>
                      <button
                        type="button"
                        v-if="hasRemoteSource(activeContentTab.id)"
                        @click="$emit('copy-text', sourceUrlForTab(activeContentTab.id), '链接已复制'); contentActionsOpen = false"
                      >复制原链接</button>
                      <button
                        v-if="hasRemoteSource(activeContentTab.id)"
                        type="button"
                        @click="$emit('open-external-link', sourceUrlForTab(activeContentTab.id)); contentActionsOpen = false"
                      >在外部浏览器打开</button>
                      <button
                        v-if="canOpenWechatRemotePage"
                        type="button"
                        :disabled="activeWechatRemotePage?.status === 'loading'"
                        @click="toggleWechatRemotePage(); contentActionsOpen = false"
                      >{{ wechatRemoteActionLabel }}</button>
                      <button
                        v-if="isArticleTab(activeContentTab.id) && textReadinessForTab(activeContentTab.id)?.retryable"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('retry-source-text', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >{{ textReadinessForTab(activeContentTab.id).status === 'needs_fetch' ? '获取正文' : '重试正文' }}</button>
                      <button
                        v-if="contentForTab(activeContentTab.id)?.status === 'failed'"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('retry-content-processing', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >重新处理</button>
                      <button
                        v-if="canReprocessLocalSource(activeContentTab.id)"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('reprocess-local-source', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >{{ localReprocessLabel(activeContentTab.id) }}</button>
                      <button
                        v-if="contentForTab(activeContentTab.id)?.original_file_path"
                        type="button"
                        @click="$emit('open-original-file', contentForTab(activeContentTab.id).original_file_path); contentActionsOpen = false"
                      >打开原始文件</button>
                      <button
                      v-if="canRetranscribeMedia(activeContentTab.id)"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('retranscribe-video', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >{{ isAudioTab(activeContentTab.id) ? '重新转写音频' : '重新转写视频' }}</button>
                      <button
                        v-if="canFetchExternalSubtitle(activeContentTab.id)"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('fetch-external-subtitle', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >尝试获取外挂字幕</button>
                      <button
                        v-if="canRefreshSourceContext(activeContentTab.id)"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('refresh-source-context', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >补采互动与评论</button>
                      <button
                        v-if="canDownloadVideo(activeContentTab.id)"
                        type="button"
                        :disabled="retryingContentId === contentForTab(activeContentTab.id)?.id"
                        @click="$emit('redownload-video', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >{{ isVideoCacheExpired(activeContentTab.id) ? '重新下载视频' : '下载视频' }}</button>
                      <button
                      v-if="isTimedMediaTab(activeContentTab.id)"
                      type="button"
                      :disabled="!timelineSegmentsForTab(activeContentTab.id).length"
                      @click="exportVideoSubtitles(activeContentTab.id); contentActionsOpen = false"
                      >导出字幕 / 转写 (.txt)</button>
                      <button
                        v-if="isReportTab(activeContentTab.id)"
                        type="button"
                        :disabled="isWechatCoverGenerating(activeContentTab.id) || isWechatCoverSwitching(activeContentTab.id)"
                        @click="requestWechatCoverGeneration(activeContentTab.id); contentActionsOpen = false"
                      >{{ contentForTab(activeContentTab.id)?.cover_url ? '重新生成 AI 封面' : '生成 AI 封面' }}</button>
                      <button
                        v-if="isReportTab(activeContentTab.id) && contentForTab(activeContentTab.id)?.cover_url"
                        type="button"
                        :disabled="isWechatCoverGenerating(activeContentTab.id) || isWechatCoverSwitching(activeContentTab.id)"
                        @click="$emit('replan-wechat-cover', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >重新策划封面主题</button>
                      <button
                        v-if="isReportTab(activeContentTab.id)"
                        type="button"
                        :disabled="isWechatCoverSwitching(activeContentTab.id)"
                        @click="$emit('create-wechat-draft', contentForTab(activeContentTab.id)); contentActionsOpen = false"
                      >{{ wechatPublishingConfigured ? '存入公众号草稿' : '配置公众号草稿发布' }}</button>
                      <button
                        v-if="contentForTab(activeContentTab.id)"
                        class="is-danger"
                        type="button"
                        @click="contentActionsOpen = false; $emit('delete-content', contentForTab(activeContentTab.id))"
                      >移入回收站</button>
                      <div class="content-action-menu-details">
                        <div
                          v-for="detail in contentDetailRows(activeContentTab.id)"
                          :key="detail.label"
                          :class="{ 'is-url': detail.kind === 'url', 'is-path': detail.kind === 'path' }"
                        >
                          <span>{{ detail.label }}</span>
                          <button
                            v-if="detail.kind === 'path'"
                            class="content-detail-path"
                            type="button"
                            :title="detail.title || detail.value"
                            @click="$emit('reveal-path', detail.value)"
                          >{{ detail.value }}</button>
                          <button
                            v-else-if="detail.kind === 'url'"
                            class="content-detail-path content-detail-url"
                            type="button"
                            :title="detail.title || detail.value"
                            @click="$emit('open-external-link', detail.value)"
                          >{{ detail.value }}</button>
                          <strong v-else :title="detail.title || detail.value">{{ detail.value }}</strong>
                        </div>
                      </div>
                    </div>
                  </el-popover>
                  </div>
                </div>
                </div>
                <div
                  v-if="hasXhsImageTextLayout(activeContentTab.id)"
                  class="xhs-image-text-splitter"
                  role="separator"
                  tabindex="0"
                  aria-orientation="horizontal"
                  aria-label="调整图片与正文高度"
                  :aria-valuemin="Math.round(verticalContentBounds().min)"
                  :aria-valuemax="Math.round(verticalContentBounds().max)"
                  :aria-valuenow="xhsImageTextHeight"
                  @pointerdown="startXhsImageTextResize"
                  @keydown="handleXhsImageTextKeydown"
                ></div>
                <section v-if="hasXhsImageTextLayout(activeContentTab.id)" class="xhs-text-reader" aria-label="小红书笔记正文">
                  <div class="xhs-text-reader-inner">
                    <h2>{{ articlePreviewForTab(activeContentTab.id)?.title || contentForTab(activeContentTab.id)?.title || activeContentTab.title }}</h2>
                    <iframe
                      v-if="articlePreviewForTab(activeContentTab.id)?.html"
                      ref="activeArticlePreviewFrame"
                      class="article-preview-frame xhs-article-preview-frame"
                      :srcdoc="articlePreviewHtml(activeContentTab.id)"
                      sandbox="allow-same-origin"
                      referrerpolicy="no-referrer"
                      title="小红书笔记正文"
                      @load="handleArticlePreviewFrameReady"
                    ></iframe>
                    <div
                      v-else-if="shouldShowArticlePreviewLoader(articlePreviewForTab(activeContentTab.id))"
                      class="campus-article-loading"
                    >
                      <span></span><span></span><span></span>
                      <p>{{ articlePreviewForTab(activeContentTab.id)?.loading_label || '正在读取小红书笔记正文…' }}</p>
                    </div>
                    <div v-else-if="articlePreviewForTab(activeContentTab.id)?.loading" class="article-preview-silent-loading" aria-busy="true"></div>
                    <div v-else class="article-preview-body">
                      {{ articleTextForTab(activeContentTab.id) || articlePreviewForTab(activeContentTab.id)?.error || '正文已保存，选择右侧总结继续追问。' }}
                    </div>
                  </div>
                </section>
              <div
                v-if="hasTranscriptTimeline(activeContentTab.id)"
                class="media-transcript-splitter"
                role="separator"
                tabindex="0"
                aria-orientation="horizontal"
                aria-label="调整视频与字幕高度"
                :aria-valuemin="Math.round(verticalContentBounds().min)"
                :aria-valuemax="Math.round(verticalContentBounds().max)"
                :aria-valuenow="mediaTranscriptHeight"
                @pointerdown="startMediaTranscriptResize"
                @keydown="handleMediaTranscriptKeydown"
              ></div>
              <section
                v-if="hasTranscriptTimeline(activeContentTab.id)"
                class="transcript-timeline"
                @wheel.passive="pauseTranscriptAutoFollow"
                @touchstart.passive="pauseTranscriptAutoFollow"
              >
                <button
                  v-if="!transcriptAutoFollow"
                  class="transcript-follow-button"
                  type="button"
                  title="回到当前进度"
                  aria-label="回到当前进度"
                  @click="resumeTranscriptAutoFollow"
                >
                  <el-icon><Aim /></el-icon>
                </button>
                <button
                  v-for="segment in timelineSegmentsForTab(activeContentTab.id)"
                  :key="segment.position"
                  :ref="(el) => setTimelineSegmentRef(activeContentTab.id, segment, el)"
                  class="timeline-segment"
                  type="button"
                  :class="{
                    approximate: segment.approximate,
                    'is-active': isTimelineSegmentActive(activeContentTab.id, segment)
                  }"
                  :data-start-seconds="segment.start_seconds"
                  @click="handleTimelineSegmentClick(activeContentTab.id, segment.start_seconds)"
                >
                  <span class="timeline-time">{{ formatTimelineTime(segment.start_seconds) }}</span>
                  <span class="timeline-text">{{ segment.text }}</span>
                </button>
              </section>
            </div>
            <div v-else key="empty-content" class="content-hero">
              <div class="content-media-frame empty-frame">
                <div class="media-placeholder workspace-empty-state">
                  <SvgMaskIcon :src="questionPageIcon" :size="42" />
                  <span>选择资料后，可在右侧助手中基于原文提问</span>
                </div>
              </div>
            </div>
            </Transition>

            <webview
              v-for="page in openedWechatRemotePages"
              :key="`${page.contentItemId}:${page.loadAttempt}`"
              :ref="(element) => setWechatRemoteWebview(page.contentItemId, element)"
              class="article-remote-page"
              :class="{ 'is-hidden': !isWechatRemotePageVisible(page) }"
              :src="page.sourceUrl"
              partition="persist:knowledgehub-wechat-preview"
              webpreferences="contextIsolation=yes, nodeIntegration=no"
              @did-finish-load="handleWechatRemotePageLoaded(page.contentItemId, $event)"
              @did-fail-load="handleWechatRemotePageFailed(page.contentItemId, $event)"
              @console-message="handleWechatRemoteConsoleMessage(page.contentItemId, $event)"
            ></webview>
            <webview
              v-if="isLocalHtmlRemoteVisible"
              :key="`${activeLocalHtmlRemotePage.contentItemId}:${activeLocalHtmlRemotePage.sourceUrl}`"
              ref="activeLocalHtmlRemoteWebview"
              class="article-remote-page"
              :src="activeLocalHtmlRemotePage.sourceUrl"
              partition="persist:knowledgehub-local-html-preview"
              webpreferences="contextIsolation=yes, nodeIntegration=no"
              @did-finish-load="handleLocalHtmlRemotePageLoaded"
              @did-fail-load="handleLocalHtmlRemotePageFailed(activeLocalHtmlRemotePage.contentItemId, $event)"
              @found-in-page="handleLocalHtmlRemoteFoundInPage"
              @console-message="handleLocalHtmlRemoteConsoleMessage(activeLocalHtmlRemotePage.contentItemId, $event)"
            ></webview>
            <ReportOutlineRail
              v-if="activeRemoteOutline.entries.length > 1 && activeRemoteOutlineWebview"
              :scroll-root="activeRemoteOutlineWebview"
              :remote-entries="activeRemoteOutline.entries"
              :remote-active-id="activeRemoteOutline.activeId"
              :on-remote-select="scrollToRemoteOutlineEntry"
              :report-key="activeRemoteOutlineKey"
              :content-version="activeRemoteOutlineVersion"
              aria-label="原文目录"
            />

            <Teleport to="body">
              <Transition name="reader-selection-action">
                <button
                  v-if="selectedTextAction"
                  class="reader-selection-ask"
                  type="button"
                  :style="selectedTextActionStyle"
                  aria-label="围绕选中文本提问"
                  title="围绕选中文本提问"
                  @pointerdown.prevent
                  @click="askAboutSelectedText"
                >
                  问 AI
                </button>
              </Transition>
            </Teleport>

          </section>
    </div>

  <section
    v-else-if="activeView === 'prompts'"
    class="editor-surface prompt-editor-surface"
    @keydown.meta.s.prevent="saveCurrentPrompt"
    @keydown.ctrl.s.prevent="saveCurrentPrompt"
  >
    <WorkspaceTabs
      v-if="promptWorkspaceTabs.length"
      :tabs="promptWorkspaceTabs"
      :active-tab-id="activePromptTabId"
      @activate="$emit('activate-prompt-tab', $event)"
      @close="$emit('close-prompt-tab', $event)"
      @close-tabs="$emit('close-prompt-tabs', $event)"
    />

    <div v-if="activePromptTabId" v-loading="promptWorkspaceLoading" class="prompt-editor-main">
      <div class="prompt-function-bar">
        <div class="prompt-usage" aria-label="提示词使用说明">
          <strong>使用说明</strong>
          <span v-if="isSystemPromptEditor" class="prompt-system-readonly">系统角色 · 只读核验</span>
          <span v-else-if="isPromptContextEditor" class="prompt-system-readonly">任务上下文 · 只读核验</span>
          <span><b>入口</b>{{ activePromptContract.entry }}</span>
          <span><b>输入</b>{{ activePromptContract.input }}</span>
          <span><b>输出</b>{{ activePromptContract.output }}</span>
          <span v-if="activePromptContract.variables.length" class="prompt-contract-variables">
            <b>变量</b><code v-for="variable in activePromptContract.variables" :key="variable">{{ variable }}</code>
            <em>删除变量后，运行时仍会附加必要输入</em>
          </span>
        </div>
        <div class="prompt-editor-actions">
          <span v-if="currentPromptDirty" class="prompt-editor-dirty">未保存</span>
          <el-button
            v-if="!isReadOnlyPromptEditor && !isReportPromptEditor && selectedPromptTemplateId && !selectedPromptTemplate?.is_active"
            class="prompt-activate-button"
            size="small"
            :loading="activatingPromptTemplate"
            @click="$emit('activate-prompt-template', selectedPromptTemplateId)"
          >
            设为启用
          </el-button>
          <el-button
            v-if="!isReadOnlyPromptEditor && (selectedPromptTemplateId || selectedWechatReportPrompt)"
            class="prompt-reset-button"
            size="small"
            :disabled="currentPromptSaving"
            @click="requestPromptReset"
          >
            <el-icon><Refresh /></el-icon>
            恢复默认
          </el-button>
          <el-button
            v-if="!isReadOnlyPromptEditor"
            class="prompt-save-button"
            size="small"
            type="primary"
            aria-keyshortcuts="Meta+S Control+S"
            :loading="currentPromptSaving"
            :disabled="!canSaveCurrentPrompt"
            @click="saveCurrentPrompt"
          >
            保存
          </el-button>
        </div>
      </div>

      <el-input
        class="prompt-editor-text"
        :model-value="isReportPromptEditor ? wechatReportPromptText : promptEditorText"
        type="textarea"
        resize="none"
        :name="isReportPromptEditor ? 'wechat-report-prompt' : 'prompt-template-content'"
        autocomplete="off"
        :aria-label="isReportPromptEditor ? '报告提示词' : '提示词内容'"
        :placeholder="isReportPromptEditor ? '编辑报告提示词…' : '编辑当前提示词…'"
        :readonly="isReadOnlyPromptEditor"
        @update:model-value="updateCurrentPromptText"
      />
    </div>
    <div v-else class="prompt-editor-empty">
      <SvgMaskIcon :src="appendPageIcon" :size="42" />
      <strong>从左侧文件树打开提示词</strong>
      <span>提示词会在标签页中打开，可同时编辑多个文件。</span>
    </div>
  </section>

  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import katex from 'katex'
import {
  Aim,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Refresh,
} from '@element-plus/icons-vue'
import { promptTaskContracts, promptTemplateDisplayName } from '../config/promptInterface'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import { useMarkdownFootnoteNavigation } from '../composables/useMarkdownFootnoteNavigation'
import movieClapperIcon from '../../assets/movieclapper.svg'
import appendPageIcon from '../../assets/append.page.svg'
import questionPageIcon from '../../assets/questionmark.text.page.svg'
import playFillIcon from '../../assets/play.fill.svg'
import pauseFillIcon from '../../assets/pause.fill.svg'
import ellipsisIcon from '../../assets/ellipsis.svg'
import { clearPreviewTextHighlights, highlightPreviewText } from '../utils/previewTextSearch'
import {
  readableCharacterCount,
  reportBodyHtmlForCharacterCount,
} from '../utils/reportReadingStats'
import {
  readingProgressFromScroll,
  remainingReadingMinutes,
} from './readingProgress.js'
import { shouldClaimReaderFocus } from './readerPointerFocus.js'
import { shouldShowArticlePreviewLoader } from '../features/library/articlePreviewLoadState.js'
import {
  clampVerticalContentSplit,
  verticalContentSplitBounds,
} from './splitterDragState.js'
import {
  parseWechatRemoteSelectionMessage,
  wechatRemoteSelectionBridgeScript,
} from './wechatRemoteSelection.js'
import {
  parseRemoteReadingProgressMessage,
  remoteReadingProgressBridgeScript,
} from './remoteReadingProgress.js'
import {
  parseRemoteOutlineMessage,
  remoteOutlineBridgeScript,
} from './remoteOutlineBridge.js'
import PreviewFindBar from './PreviewFindBar.vue'
import ReadingProgressControl from './ReadingProgressControl.vue'
import ReportOutlineRail from './ReportOutlineRail.vue'
import WorkspaceTabs from './WorkspaceTabs.vue'

const ArtVideoPlayer = defineAsyncComponent(() => import('./ArtVideoPlayer.vue'))
const ArtAudioPlayer = defineAsyncComponent(() => import('./ArtAudioPlayer.vue'))
const props = defineProps({
  activeView: { type: String, required: true },
  workspaceTabs: { type: Array, default: () => [] },
  activeWorkspaceTab: { type: Object, default: null },
  promptWorkspaceTabs: { type: Array, default: () => [] },
  activePromptTabId: { type: String, default: '' },
  selectedContentItem: { type: Object, default: null },
  selectedModel: { type: String, default: 'small' },
  useCache: { type: Boolean, default: true },
  modelProfileOptions: { type: Array, default: () => [] },
  running: { type: Boolean, default: false },
  result: { type: Object, required: true },
  parsedUrl: { type: Object, default: null },
  mediaPreviewUrl: { type: String, default: '' },
  selectedMarkdownPreview: { type: String, default: '' },
  selectedMarkdownSizeBytes: { type: Number, default: 0 },
  selectedMarkdownPath: { type: String, default: '' },
  selectedReportSourceStats: { type: Object, default: () => ({ analyzed: 0, referenced: 0 }) },
  promptTaskType: { type: String, default: 'summary' },
  promptTemplates: { type: Array, default: () => [] },
  selectedPromptTemplateId: { type: String, default: '' },
  loadingPrompts: { type: Boolean, default: false },
  promptEditorText: { type: String, default: '' },
  promptEditorName: { type: String, default: '' },
  savingPromptTemplate: { type: Boolean, default: false },
  activatingPromptTemplate: { type: Boolean, default: false },
  wechatReportGroups: { type: Array, default: () => [] },
  wechatReportPrompts: { type: Array, default: () => [] },
  selectedWechatReportPromptGroupId: { type: String, default: '' },
  selectedWechatReportPromptType: { type: String, default: 'group_context' },
  wechatReportPromptText: { type: String, default: '' },
  loadingWechatReportPrompts: { type: Boolean, default: false },
  savingWechatReportPrompt: { type: Boolean, default: false },
  workspaceTabById: { type: Function, required: true },
  contentForTab: { type: Function, required: true },
  resultForTab: { type: Function, required: true },
  mediaUrlForTab: { type: Function, required: true },
  originalMediaUrlForTab: { type: Function, required: true },
  transcriptForTab: { type: Function, required: true },
  articlePreviewForTab: { type: Function, required: true },
  sourceProviderLabel: { type: Function, required: true },
  formatDuration: { type: Function, required: true },
  formatDateTime: { type: Function, required: true },
  promptTaskLabel: { type: Function, required: true },
  formatBytes: { type: Function, required: true },
  roundedProgress: { type: Function, required: true },
  statusLabel: { type: Function, required: true },
  stepLabel: { type: Function, required: true },
  batchTaskName: { type: Function, required: true },
  formatSeconds: { type: Function, required: true },
  retryingContentId: { type: String, default: null },
  wechatPublishingConfigured: { type: Boolean, default: false },
  wechatCoverGeneratingContentIds: { type: Array, default: () => [] },
  wechatCoverSwitchingContentIds: { type: Array, default: () => [] },
  wechatCoverHistoryForContent: { type: Function, required: true },
})

const emit = defineEmits([
  'update:selectedModel',
  'update:useCache',
  'update:promptEditorText',
  'update:promptEditorName',
  'update:promptTaskType',
  'load-prompts',
  'select-prompt-template',
  'new-prompt-template',
  'activate-prompt-template',
  'delete-prompt-template',
  'save-prompt',
  'reset-prompt',
  'update:selectedWechatReportPromptGroupId',
  'update:selectedWechatReportPromptType',
  'update:wechat-report-prompt-text',
  'save-wechat-report-prompt',
  'copy-text',
  'open-external-link',
  'retry-source-text',
  'open-campus-attachment',
  'retry-content-processing',
  'reprocess-local-source',
  'open-original-file',
  'reveal-path',
  'retranscribe-video',
  'fetch-external-subtitle',
  'refresh-source-context',
  'redownload-video',
  'activate-workspace-tab',
  'close-workspace-tab',
  'close-workspace-tabs',
  'reveal-workspace-tab',
  'delete-workspace-tab',
  'activate-prompt-tab',
  'close-prompt-tab',
  'close-prompt-tabs',
  'ask-about-selection',
  'generate-wechat-cover',
  'regenerate-wechat-cover',
  'replan-wechat-cover',
  'select-wechat-cover',
  'create-wechat-draft',
  'delete-content',
])

const activePlayer = ref(null)
const isAudioPlaying = ref(false)
const contentHero = ref(null)
const reportReader = ref(null)
const reportMarkdown = ref(null)
const activeArticlePreviewFrame = ref(null)
const activeLocalHtmlRemoteWebview = ref(null)
const xhsGalleryTrack = ref(null)
const articleOutlineRoot = ref(null)
const contentActionsOpen = ref(false)
const previewFindOpen = ref(false)
const previewFindQuery = ref('')
const previewFindMatchCount = ref(0)
const previewFindActiveIndex = ref(-1)
const previewFindTruncated = ref(false)
const previewFindFocusRequest = ref(0)
const selectedTextAction = ref(null)
const readingProgress = ref(0)
const readingCharacterCount = ref(0)
let previewFindHighlightRoot = null
let previewFindMatches = []
let previewFindRefreshFrame = 0
let previewFindRestoreFocus = null
let localHtmlRemoteFindRequestId = null
let removeDesktopPreviewFindListener = null
let articlePreviewSelectionDocument = null
let selectedTextPointerIsDown = false
let selectedTextActionRevealFrame = 0
let readingProgressRefreshFrame = 0
let readingProgressFrameDocument = null
const wechatRemotePages = reactive({})
const localHtmlRemoteFailures = reactive({})
const remoteReadingProgressByKey = reactive({})
const remoteOutlines = reactive({})

const {
  clearFootnoteReturn,
  handleFootnoteClick: handleReportFootnoteClick,
  hasFootnoteReturn,
  positionFootnotePreview,
  returnToFootnoteReference,
} = useMarkdownFootnoteNavigation({
  scrollRoot: reportReader,
  scopeKey: () => activeContentTab.value?.id || '',
})
const wechatRemoteWebviews = new Map()
const wechatRemoteLoadTimers = new Map()
function wechatRemoteScrollbarCss() {
  const muted = getComputedStyle(document.documentElement).getPropertyValue('--vk-muted').trim()
  return `
    * { scrollbar-width: thin; scrollbar-color: transparent transparent; }
    *::-webkit-scrollbar { width: 6px !important; height: 6px !important; }
    *::-webkit-scrollbar-track,
    *::-webkit-scrollbar-corner { background: transparent !important; }
    *::-webkit-scrollbar-thumb {
      border: 2px solid transparent !important;
      border-radius: 999px !important;
      background: transparent !important;
      background-clip: padding-box !important;
    }
    *:hover::-webkit-scrollbar-thumb {
      background: color-mix(in srgb, ${muted} 26%, transparent) !important;
      background-clip: padding-box !important;
    }
  `
}
const selectedTextActionStyle = computed(() => {
  const rect = selectedTextAction.value?.rect
  if (!rect) return {}
  const actionWidth = 64
  const actionHeight = 32
  const horizontalMargin = 10
  const opensAbove = rect.top - actionHeight - 8 >= horizontalMargin
  const left = Math.max(horizontalMargin, Math.min(window.innerWidth - actionWidth - horizontalMargin, rect.right - actionWidth))
  const top = opensAbove ? rect.top - actionHeight - 8 : Math.min(window.innerHeight - actionHeight - horizontalMargin, rect.bottom + 8)
  return {
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`,
    '--reader-selection-origin': opensAbove ? 'center bottom' : 'center top',
    '--reader-selection-tail-top': opensAbove ? 'auto' : '-4px',
    '--reader-selection-tail-bottom': opensAbove ? '-4px' : 'auto',
  }
})
const activePromptWorkspaceTab = computed(() => (
  props.promptWorkspaceTabs.find((tab) => tab.id === props.activePromptTabId) || null
))
const isSystemPromptEditor = computed(() => activePromptWorkspaceTab.value?.kind === 'system')
const isPromptContextEditor = computed(() => activePromptWorkspaceTab.value?.kind === 'context')
const isReadOnlyPromptEditor = computed(() => isSystemPromptEditor.value || isPromptContextEditor.value)
const isReportPromptEditor = computed(() => props.promptTaskType === 'wechat_reports')
const selectedPromptTemplate = computed(() => {
  return props.promptTemplates.find((template) => template.id === props.selectedPromptTemplateId) || null
})
const selectedWechatReportPrompt = computed(() => {
  return props.wechatReportPrompts.find((item) => (
    item.group_id === props.selectedWechatReportPromptGroupId
    && item.report_type === props.selectedWechatReportPromptType
  )) || null
})
const activePromptContract = computed(() => promptTaskContracts[props.promptTaskType] || {
  entry: '知识处理流程',
  input: '当前任务材料',
  output: 'AI 生成内容',
  variables: []
})
const standardPromptDirty = computed(() => {
  if (isReadOnlyPromptEditor.value) return false
  if (isReportPromptEditor.value) return false
  if (!selectedPromptTemplate.value) {
    return Boolean(props.promptEditorName.trim() || props.promptEditorText.trim())
  }
  return props.promptEditorName !== promptTemplateDisplayName(selectedPromptTemplate.value)
    || props.promptEditorText !== selectedPromptTemplate.value.template
})
const reportPromptDirty = computed(() => {
  if (!isReportPromptEditor.value || !selectedWechatReportPrompt.value) return false
  return props.wechatReportPromptText !== selectedWechatReportPrompt.value.template
})
const currentPromptDirty = computed(() => (
  isReportPromptEditor.value ? reportPromptDirty.value : standardPromptDirty.value
))
const canSaveCurrentPrompt = computed(() => {
  if (!currentPromptDirty.value) return false
  if (isReportPromptEditor.value) {
    return Boolean(selectedWechatReportPrompt.value && props.wechatReportPromptText.trim())
  }
  return Boolean(props.promptEditorName.trim() && props.promptEditorText.trim())
})
const promptWorkspaceLoading = computed(() => (
  isReportPromptEditor.value ? props.loadingWechatReportPrompts : props.loadingPrompts
))
const currentPromptSaving = computed(() => (
  isReportPromptEditor.value ? props.savingWechatReportPrompt : props.savingPromptTemplate
))

function updateCurrentPromptText(value) {
  if (isReadOnlyPromptEditor.value) return
  emit(isReportPromptEditor.value ? 'update:wechat-report-prompt-text' : 'update:promptEditorText', value)
}

function saveCurrentPrompt() {
  if (!canSaveCurrentPrompt.value || currentPromptSaving.value) return
  emit(isReportPromptEditor.value ? 'save-wechat-report-prompt' : 'save-prompt')
}

function requestPromptReset() {
  if (currentPromptSaving.value) return
  emit('reset-prompt')
}

const mediaTranscriptHeight = ref(readStoredVerticalSplit('knowledgehub.media-transcript-height.v1'))
const mediaTranscriptResizing = ref(false)
const xhsImageTextHeight = ref(readStoredVerticalSplit('knowledgehub.xhs-image-text-height.v1'))
const xhsImageTextResizing = ref(false)
const xhsGalleryIndex = ref(0)
const currentPlaybackTime = ref(0)
const activeTimelineKey = ref('')
const transcriptAutoFollow = ref(true)
const timelineSegmentRefs = new Map()
let transcriptScrollTimer = null
let mediaTranscriptResizeStart = null
let xhsImageTextResizeStart = null
let contentHeroResizeObserver = null

function readStoredVerticalSplit(key) {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isFinite(value) ? Math.max(25, Math.min(75, value)) : 56
  } catch {
    return 56
  }
}

const activeContentTab = computed(() => {
  if (props.activeWorkspaceTab) return props.activeWorkspaceTab
  if (!props.selectedContentItem?.id) return null
  return {
    id: `content:${props.selectedContentItem.id}`,
    type: 'content',
    content_item_id: props.selectedContentItem.id,
    title: props.selectedContentItem.title || props.selectedContentItem.canonical_source_id || '未命名内容',
    source_provider: props.selectedContentItem.source_provider,
    status: props.selectedContentItem.status,
  }
})

function processingStages(tabId) {
  const task = props.resultForTab(tabId) || {}
  const progress = task.progress || {}
  const complete = (key, fallback) => Boolean(fallback || Number(progress[key] || 0) >= 100)
  const active = (keys) => keys.includes(task.step)
  return [
    { key: 'download', label: '视频预览', status: complete('download', task.video_path) ? 'done' : active(['download', 'info', 'parse']) ? 'active' : 'pending' },
    { key: 'transcript', label: '字幕 / 转写', status: complete('transcribe', task.transcript) ? 'done' : active(['extract_audio', 'transcribe']) ? 'active' : 'pending' },
    { key: 'summary', label: 'AI 总结', status: complete('summarize', task.summary) ? 'done' : active(['summarize', 'save']) ? 'active' : 'pending' },
  ]
}

function processingStageDescription(tabId) {
  const task = props.resultForTab(tabId) || {}
  if (task.step === 'download') return task.download_transfer?.detail || '正在下载视频预览…'
  if (task.step === 'extract_audio') return '视频已下载，正在提取音频…'
  if (task.step === 'transcribe') return task.transcript ? '字幕已就绪，正在整理转写…' : '正在获取字幕或进行转写…'
  if (task.step === 'summarize') return '字幕已就绪，正在生成 AI 总结…'
  if (task.step === 'save') return '正在保存字幕与总结…'
  if (task.status === 'queued') return '已加入后台队列，等待前序视频完成…'
  return '正在准备下载、字幕和总结。'
}

const activeWechatContent = computed(() => {
  const tab = activeContentTab.value
  if (!tab || !isWechatArticleTab(tab.id)) return null
  return props.contentForTab(tab.id) || null
})

const canEmbedWechatPage = computed(() => Boolean(window.knowledgeHubDesktop))
const canOpenWechatRemotePage = computed(() => Boolean(
  canEmbedWechatPage.value
  && /^https:\/\/mp\.weixin\.qq\.com\//.test(String(activeWechatContent.value?.source_url || ''))
))
const activeWechatRemotePage = computed(() => {
  const contentItemId = activeWechatContent.value?.id
  return contentItemId ? wechatRemotePages[contentItemId] || null : null
})
const openedWechatRemotePages = computed(() => Object.values(wechatRemotePages))
const isWechatRemoteVisible = computed(() => (
  Boolean(activeWechatRemotePage.value && isWechatRemotePageVisible(activeWechatRemotePage.value))
))
const activeLocalHtmlRemotePage = computed(() => {
  const tabId = activeContentTab.value?.id || ''
  const sourceUrl = localHtmlOriginalPageUrl(tabId)
  if (!canEmbedWechatPage.value || !tabId || !sourceUrl || localHtmlRemoteFailures[tabId]) return null
  return { contentItemId: tabId, sourceUrl }
})
const isLocalHtmlRemoteVisible = computed(() => Boolean(activeLocalHtmlRemotePage.value))
const activeRemoteOutlineKey = computed(() => {
  if (isWechatRemoteVisible.value) return `wechat:${activeWechatContent.value?.id || ''}`
  if (isLocalHtmlRemoteVisible.value) return `local-html:${activeContentTab.value?.id || ''}`
  return ''
})
const activeRemoteOutline = computed(() => (
  remoteOutlines[activeRemoteOutlineKey.value] || { entries: [], activeId: '' }
))
const activeRemoteOutlineVersion = computed(() => (
  `${activeRemoteOutlineKey.value}:${activeRemoteOutline.value.entries.map((entry) => entry.id).join('|')}`
))
const activeRemoteOutlineWebview = computed(() => {
  if (isWechatRemoteVisible.value) return wechatRemoteWebviews.get(activeWechatContent.value?.id) || null
  if (isLocalHtmlRemoteVisible.value) return activeLocalHtmlRemoteWebview.value || null
  return null
})
function activeRemoteReadingProgressKey() {
  if (isWechatRemoteVisible.value) return `wechat:${activeWechatContent.value?.id || ''}`
  if (isLocalHtmlRemoteVisible.value) return `local-html:${activeContentTab.value?.id || ''}`
  return ''
}
const activeRemoteReadingProgress = computed(() => {
  const key = activeRemoteReadingProgressKey()
  return key ? remoteReadingProgressByKey[key] || null : null
})
const supportsReadingProgress = computed(() => {
  const tab = activeContentTab.value
  if (!tab) return false
  if (isWechatRemoteVisible.value || isLocalHtmlRemoteVisible.value) return true
  return isArticleTab(tab.id)
    || isReportTab(tab.id)
    || isExternalMarkdownTab(tab.id)
    || isMiniProgramCaptureTab(tab.id)
})
const showReadingProgress = computed(() => (
  supportsReadingProgress.value && activeReadingCharacterCount.value > 0
))
const estimatedRemainingReadingMinutes = computed(() => (
  remainingReadingMinutes(activeReadingCharacterCount.value, activeReadingProgress.value)
))
const activeReadingProgress = computed(() => (
  activeRemoteReadingProgress.value?.progress ?? readingProgress.value
))
const activeReadingCharacterCount = computed(() => (
  activeRemoteReadingProgress.value?.characterCount ?? readingCharacterCount.value
))
const wechatRemoteActionLabel = computed(() => {
  if (isWechatRemoteVisible.value) return '查看缓存正文'
  if (activeWechatRemotePage.value?.status === 'ready') return '在软件内打开原文'
  if (activeWechatRemotePage.value?.status === 'failed') return '重新加载软件内原文'
  if (activeWechatRemotePage.value?.status === 'loading') return '正在打开原文'
  return '在软件内打开原文'
})

watch(
  () => activeContentTab.value?.id || '',
  () => {
    currentPlaybackTime.value = 0
    isAudioPlaying.value = false
    activeTimelineKey.value = ''
    transcriptAutoFollow.value = true
    clearSelectedTextAction()
    detachReadingProgressFrame()
    readingProgress.value = 0
    readingCharacterCount.value = 0
    scheduleReadingProgressRefresh()
  }
)

watch(
  () => [isWechatRemoteVisible.value, isLocalHtmlRemoteVisible.value],
  () => scheduleReadingProgressRefresh(),
  { flush: 'post' }
)

watch(
  () => props.workspaceTabs.map((tab) => tab.content_item_id || '').join('|'),
  () => {
    const openContentIds = new Set(props.workspaceTabs.map((tab) => tab.content_item_id).filter(Boolean))
    const openTabIds = new Set(props.workspaceTabs.map((tab) => String(tab.id || '')).filter(Boolean))
    for (const contentItemId of Object.keys(wechatRemotePages)) {
      if (openContentIds.has(contentItemId)) continue
      clearWechatRemoteLoadTimer(contentItemId)
      delete wechatRemotePages[contentItemId]
      wechatRemoteWebviews.delete(contentItemId)
      delete remoteReadingProgressByKey[`wechat:${contentItemId}`]
      delete remoteOutlines[`wechat:${contentItemId}`]
    }
    for (const key of Object.keys(remoteReadingProgressByKey)) {
      if (!key.startsWith('local-html:')) continue
      if (!openTabIds.has(key.slice('local-html:'.length))) delete remoteReadingProgressByKey[key]
    }
    for (const key of Object.keys(remoteOutlines)) {
      if (!key.startsWith('local-html:')) continue
      if (!openTabIds.has(key.slice('local-html:'.length))) delete remoteOutlines[key]
    }
  }
)

watch(
  () => [
    activeContentTab.value?.id || '',
    currentPlaybackTime.value,
    timelineSegmentsForTab(activeContentTab.value?.id).length
  ],
  () => {
    activeTimelineKey.value = findActiveTimelineKey(activeContentTab.value?.id)
  },
  { flush: 'post' }
)

watch(() => activeContentTab.value?.id, () => {
  clearFootnoteReturn()
  xhsGalleryIndex.value = 0
  void nextTick(() => xhsGalleryTrack.value?.scrollTo({ left: 0, behavior: 'auto' }))
})

watch(activeTimelineKey, () => {
  scheduleActiveTranscriptScroll()
}, { flush: 'post' })

watch(previewFindQuery, () => {
  if (isLocalHtmlRemoteVisible.value && previewFindOpen.value) return
  schedulePreviewFindRefresh()
})

watch(
  () => [
    activeContentTab.value?.id || '',
    props.selectedMarkdownPreview,
    activeContentTab.value ? articleTextForTab(activeContentTab.value.id) : '',
    activeContentTab.value ? props.articlePreviewForTab(activeContentTab.value.id)?.html || '' : '',
    activeContentTab.value ? timelineSegmentsForTab(activeContentTab.value.id).map((segment) => segment.text).join('|') : '',
  ],
  () => {
    schedulePreviewFindRefresh()
    scheduleReadingProgressRefresh()
  },
  { flush: 'post' }
)

onBeforeUnmount(() => {
  stopMediaTranscriptResize()
  stopXhsImageTextResize()
  contentHeroResizeObserver?.disconnect()
  contentHeroResizeObserver = null
  for (const contentItemId of wechatRemoteLoadTimers.keys()) clearWechatRemoteLoadTimer(contentItemId)
  wechatRemoteWebviews.clear()
  if (transcriptScrollTimer) {
    clearTimeout(transcriptScrollTimer)
    transcriptScrollTimer = null
  }
  if (previewFindRefreshFrame) {
    window.cancelAnimationFrame(previewFindRefreshFrame)
    previewFindRefreshFrame = 0
  }
  if (selectedTextActionRevealFrame) {
    window.cancelAnimationFrame(selectedTextActionRevealFrame)
    selectedTextActionRevealFrame = 0
  }
  if (readingProgressRefreshFrame) {
    window.cancelAnimationFrame(readingProgressRefreshFrame)
    readingProgressRefreshFrame = 0
  }
  detachReadingProgressFrame()
  clearPreviewFindHighlights()
  window.removeEventListener('keydown', handlePreviewFindShortcut, true)
  document.removeEventListener('selectionchange', handleDocumentSelectionChange)
  document.removeEventListener('pointerdown', handleSelectedTextPointerDown, true)
  document.removeEventListener('pointerup', handleSelectedTextPointerUp, true)
  document.removeEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  articlePreviewSelectionDocument?.removeEventListener('selectionchange', handleArticlePreviewSelectionChange)
  articlePreviewSelectionDocument?.removeEventListener('pointerdown', handleSelectedTextPointerDown, true)
  articlePreviewSelectionDocument?.removeEventListener('pointerup', handleSelectedTextPointerUp, true)
  articlePreviewSelectionDocument?.removeEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  articlePreviewSelectionDocument = null
  removeDesktopPreviewFindListener?.()
  removeDesktopPreviewFindListener = null
  timelineSegmentRefs.clear()
})

onMounted(() => {
  constrainVerticalContentSplits()
  if (typeof ResizeObserver === 'function') {
    contentHeroResizeObserver = new ResizeObserver(() => constrainVerticalContentSplits())
    if (contentHero.value) contentHeroResizeObserver.observe(contentHero.value)
  }
  window.addEventListener('keydown', handlePreviewFindShortcut, true)
  document.addEventListener('selectionchange', handleDocumentSelectionChange)
  document.addEventListener('pointerdown', handleSelectedTextPointerDown, true)
  document.addEventListener('pointerup', handleSelectedTextPointerUp, true)
  document.addEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  removeDesktopPreviewFindListener = window.knowledgeHubDesktop?.onPreviewFind?.(handleDesktopPreviewFindShortcut) || null
  scheduleReadingProgressRefresh()
})

watch(contentHero, (element, previousElement) => {
  if (previousElement) contentHeroResizeObserver?.unobserve(previousElement)
  if (element) {
    contentHeroResizeObserver?.observe(element)
    constrainVerticalContentSplits()
  }
}, { flush: 'post' })

function contentDetailRows(tabId) {
  const content = props.contentForTab(tabId)
  const tab = props.workspaceTabById(tabId)
  const sourceUrl = sourceUrlForTab(tabId)
  const sourceMetadata = content?.source_metadata || {}
  const readableText = readerTextForMetadata(tabId)
  const isTimedMedia = isTimedMediaTab(tabId)
  const isCurrentDocument = String(content?.id || '') === String(props.selectedContentItem?.id || '')
  const markdownPath = isCurrentDocument
    ? String(props.selectedMarkdownPath || content?.markdown_draft_path || '')
    : String(content?.markdown_draft_path || '')
  const rows = [
    { label: '来源', value: props.sourceProviderLabel(content?.source_provider) },
    { label: '字符数', value: formatReadableCharacterCount(readableText), title: '按当前可阅读正文统计，不含空白字符' },
    ...(!isTimedMedia ? [{
      label: '文档大小',
      value: formatDocumentSize(content),
      title: '当前本地 Markdown 文档的实际 UTF-8 字节大小',
    }] : []),
    ...(isTimedMedia && content?.duration_seconds ? [{ label: '时长', value: props.formatDuration(content.duration_seconds) }] : []),
    ...(sourceMetadata.file_format ? [{ label: '格式', value: String(sourceMetadata.file_format) }] : []),
    ...(sourceMetadata.file_size_bytes ? [{ label: '原件大小', value: props.formatBytes(sourceMetadata.file_size_bytes) }] : []),
    ...(sourceMetadata.width && sourceMetadata.height ? [{ label: '尺寸', value: `${sourceMetadata.width} × ${sourceMetadata.height}` }] : []),
    ...(sourceMetadata.page_count ? [{ label: '页数', value: `${sourceMetadata.page_count} 页` }] : []),
    ...(sourceMetadata.video_codec ? [{ label: '视频编码', value: String(sourceMetadata.video_codec) }] : []),
    ...(sourceMetadata.audio_codec ? [{ label: '音频编码', value: String(sourceMetadata.audio_codec) }] : []),
    ...(sourceMetadata.sample_rate ? [{ label: '采样率', value: `${(Number(sourceMetadata.sample_rate) / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} kHz` }] : []),
    ...(sourceMetadata.channels ? [{ label: '声道', value: Number(sourceMetadata.channels) === 1 ? '单声道' : `${sourceMetadata.channels} 声道` }] : []),
    { label: '导入时间', value: props.formatDateTime(content?.created_at || tab?.opened_at) },
    { label: '修改时间', value: props.formatDateTime(content?.updated_at || tab?.opened_at) },
    ...(markdownPath ? [{ label: '文件位置', value: markdownPath, title: markdownPath, kind: 'path' }] : []),
    ...(hasRemoteSource(tabId) ? [{ label: '原文链接', value: sourceUrl, title: sourceUrl, kind: 'url' }] : []),
  ]
  return rows
}

function canRetranscribeMedia(tabId) {
  const content = props.contentForTab(tabId)
  if (!isTimedMediaTab(tabId)) return false
  if (content?.source_provider === 'local_file') return Boolean(content?.original_file_path)
  return Boolean(props.resultForTab(tabId)?.video_path || content.video_path)
}

function canFetchExternalSubtitle(tabId) {
  const content = props.contentForTab(tabId)
  return content?.content_type === 'video' && content?.source_provider === 'bilibili' && Boolean(content?.source_url)
}

function canRefreshSourceContext(tabId) {
  const content = props.contentForTab(tabId)
  return ['bilibili', 'douyin', 'xiaohongshu'].includes(content?.source_provider)
    && Boolean(content?.source_url)
}

function isVideoCacheExpired(tabId) {
  const content = props.contentForTab(tabId)
  return content?.content_type === 'video' && content?.video_cache_status === 'expired'
}

function canDownloadVideo(tabId) {
  const content = props.contentForTab(tabId)
  return content?.content_type === 'video'
    && content?.source_provider !== 'local_file'
    && !content?.video_path
    && hasRemoteSource(tabId)
}

function textReadinessForTab(tabId) {
  return props.contentForTab(tabId)?.text_readiness || null
}

function isArticleTab(tabId) {
  return ['article', 'forum_post'].includes(props.contentForTab(tabId)?.content_type) || isLocalHtmlArticleTab(tabId)
}

function isLocalHtmlArticleTab(tabId) {
  const content = props.contentForTab(tabId)
  if (content?.source_provider !== 'local_file' || content?.content_type !== 'document') return false
  const format = String(content?.source_metadata?.file_format || '').toUpperCase()
  const filename = String(content?.source_metadata?.file_name || '')
  return ['HTML', 'HTM', 'XHTML'].includes(format) || /\.x?html?$/i.test(filename)
}

function localHtmlOriginalPageUrl(tabId) {
  if (!isLocalHtmlArticleTab(tabId)) return ''
  const sourceUrl = String(props.contentForTab(tabId)?.source_metadata?.original_source_url || '').trim()
  return /^https:\/\//iu.test(sourceUrl) ? sourceUrl : ''
}

function handleLocalHtmlRemotePageFailed(contentItemId, event) {
  if (Number(event?.errorCode) === -3) return
  localHtmlRemoteFailures[contentItemId] = true
}

async function handleLocalHtmlRemotePageLoaded(event) {
  const webview = event?.target || activeLocalHtmlRemoteWebview.value
  try {
    await webview?.executeJavaScript?.(remoteReadingProgressBridgeScript(
      readableCharacterCount(readerTextForMetadata(activeContentTab.value?.id))
    ))
  } catch {
    // The original source remains usable if the optional progress bridge is refused.
  }
  try {
    await webview?.executeJavaScript?.(remoteOutlineBridgeScript())
  } catch {
    // A source page without readable headings simply has no outline rail.
  }
  if (previewFindOpen.value) schedulePreviewFindRefresh()
}

function handleLocalHtmlRemoteConsoleMessage(contentItemId, event) {
  const webview = activeLocalHtmlRemoteWebview.value
  if (!webview || event?.target !== webview || !isLocalHtmlRemoteVisible.value) return
  const outline = parseRemoteOutlineMessage(event?.message)
  if (outline && String(contentItemId) === String(activeContentTab.value?.id || '')) {
    applyRemoteOutlineMessage(`local-html:${contentItemId}`, outline)
    return
  }
  const progress = parseRemoteReadingProgressMessage(event?.message)
  if (!progress || String(contentItemId) !== String(activeContentTab.value?.id || '')) return
  remoteReadingProgressByKey[`local-html:${contentItemId}`] = progress
}

function handleLocalHtmlRemoteFoundInPage(event) {
  const result = event?.result
  if (!result || result.requestId !== localHtmlRemoteFindRequestId) return
  previewFindMatchCount.value = Number(result.matches) || 0
  previewFindActiveIndex.value = Math.max(-1, (Number(result.activeMatchOrdinal) || 0) - 1)
  previewFindTruncated.value = false
}

function isXiaohongshuArticleTab(tabId) {
  const content = props.contentForTab(tabId)
  return content?.source_provider === 'xiaohongshu' && content?.content_type === 'article'
}

function hasXhsImageTextLayout(tabId) {
  return isXiaohongshuArticleTab(tabId) && Boolean(props.articlePreviewForTab(tabId)?.gallery?.length)
}

function xhsGalleryImageCount(tabId) {
  return props.articlePreviewForTab(tabId)?.gallery?.length || 0
}

function canNavigateXhsGallery(tabId, direction) {
  const next = xhsGalleryIndex.value + direction
  return next >= 0 && next < xhsGalleryImageCount(tabId)
}

function contentHeroLayoutStyle(tabId) {
  if (hasTranscriptTimeline(tabId)) return { '--media-height': `${mediaTranscriptHeight.value}%` }
  if (hasXhsImageTextLayout(tabId)) return { '--xhs-image-height': `${xhsImageTextHeight.value}%` }
  return null
}

function scrollXhsGallery(direction) {
  const track = xhsGalleryTrack.value
  if (!track) return
  const count = xhsGalleryImageCount(activeContentTab.value?.id)
  const next = Math.max(0, Math.min(Math.max(0, count - 1), xhsGalleryIndex.value + direction))
  if (next === xhsGalleryIndex.value) return
  xhsGalleryIndex.value = next
  track.scrollTo({ left: next * track.clientWidth, behavior: 'smooth' })
}

function syncXhsGalleryPosition() {
  const track = xhsGalleryTrack.value
  if (!track || track.clientWidth <= 0) return
  const count = xhsGalleryImageCount(activeContentTab.value?.id)
  xhsGalleryIndex.value = Math.max(0, Math.min(Math.max(0, count - 1), Math.round(track.scrollLeft / track.clientWidth)))
}

function handleXhsGalleryKeydown(event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  scrollXhsGallery(event.key === 'ArrowLeft' ? -1 : 1)
}

function articlePreviewHtml(tabId) {
  const preview = props.articlePreviewForTab(tabId)
  // The live page is shown in the isolated webview above.  When it cannot be
  // reached (including offline), retain a readable, persisted body snapshot
  // instead of rendering a browser-saved HTML shell whose CSS asset folder may
  // not have been imported alongside the .html file.
  if (isLocalHtmlArticleTab(tabId)) return preview?.html || preview?.source_html || ''
  return preview?.html || ''
}

function isVideoTab(tabId) {
  return props.contentForTab(tabId)?.content_type === 'video'
}

function isAudioTab(tabId) {
  return props.contentForTab(tabId)?.content_type === 'audio'
}

function isTimedMediaTab(tabId) {
  return isVideoTab(tabId) || isAudioTab(tabId)
}

function isImageTab(tabId) {
  return props.contentForTab(tabId)?.content_type === 'image'
}

function canReprocessLocalSource(tabId) {
  return props.contentForTab(tabId)?.source_provider === 'local_file' && !isTimedMediaTab(tabId)
}

function localReprocessLabel(tabId) {
  const type = props.contentForTab(tabId)?.content_type
  if (type === 'image') return '重新识别图片文字'
  const source = String(props.contentForTab(tabId)?.source_name || '')
  if (source.includes('PDF')) return '重新识别 PDF'
  if (source.includes('HTML')) return '重新提取 HTML 正文'
  if (source.includes('Word')) return '重新提取 Word 正文'
  return '重新提取原文件'
}

function isCampusArticleTab(tabId) {
  return props.contentForTab(tabId)?.source_provider === 'campus'
}

function isWechatArticleTab(tabId) {
  return props.contentForTab(tabId)?.source_provider === 'wechat'
}

function clearWechatRemoteLoadTimer(contentItemId) {
  const timer = wechatRemoteLoadTimers.get(contentItemId)
  if (!timer) return
  window.clearTimeout(timer)
  wechatRemoteLoadTimers.delete(contentItemId)
}

function scheduleWechatRemoteLoadTimeout(contentItemId) {
  clearWechatRemoteLoadTimer(contentItemId)
  const timer = window.setTimeout(() => {
    const page = wechatRemotePages[contentItemId]
    if (!page || page.status !== 'loading') return
    page.status = 'failed'
    page.visible = false
  }, 15000)
  wechatRemoteLoadTimers.set(contentItemId, timer)
}

function setWechatRemoteWebview(contentItemId, webview) {
  if (webview) wechatRemoteWebviews.set(contentItemId, webview)
  else wechatRemoteWebviews.delete(contentItemId)
}

function isWechatRemotePageVisible(page) {
  return Boolean(
    page?.visible
    && page.status === 'ready'
    && page.contentItemId === activeWechatContent.value?.id
  )
}

async function handleWechatRemotePageLoaded(contentItemId, event) {
  const page = wechatRemotePages[contentItemId]
  const webview = event?.target || wechatRemoteWebviews.get(contentItemId)
  if (!page || !webview || page.sourceUrl !== webview.src) return
  try {
    await webview.insertCSS(wechatRemoteScrollbarCss())
  } catch {
    // The original page remains readable when a particular guest page rejects injected CSS.
  }
  try {
    await webview.executeJavaScript(wechatRemoteSelectionBridgeScript())
  } catch {
    // The page remains readable even when its guest renderer rejects the optional selection bridge.
  }
  try {
    const tabId = props.workspaceTabs.find((tab) => (
      String(tab.content_item_id || '') === String(contentItemId)
    ))?.id || activeContentTab.value?.id
    await webview.executeJavaScript(remoteReadingProgressBridgeScript(
      readableCharacterCount(readerTextForMetadata(tabId))
    ))
  } catch {
    // Progress is supplemental; do not let it block the original-page preview.
  }
  try {
    await webview.executeJavaScript(remoteOutlineBridgeScript())
  } catch {
    // A source page without readable headings simply has no outline rail.
  }
  if (wechatRemoteWebviews.get(contentItemId) !== webview) return
  clearWechatRemoteLoadTimer(contentItemId)
  page.status = 'ready'
}

function handleWechatRemoteConsoleMessage(contentItemId, event) {
  const webview = wechatRemoteWebviews.get(contentItemId)
  if (!webview || event?.target !== webview || !isWechatRemotePageVisible(wechatRemotePages[contentItemId])) return
  const outline = parseRemoteOutlineMessage(event?.message)
  if (outline) {
    applyRemoteOutlineMessage(`wechat:${contentItemId}`, outline)
    return
  }
  const progress = parseRemoteReadingProgressMessage(event?.message)
  if (progress) {
    remoteReadingProgressByKey[`wechat:${contentItemId}`] = progress
    return
  }
  const selection = parseWechatRemoteSelectionMessage(event?.message)
  if (!selection) return
  if (selection.kind === 'clear') {
    clearSelectedTextAction()
    return
  }

  const content = props.contentForTab(activeContentTab.value?.id)
  if (!content?.id || String(content.id) !== String(contentItemId)) return
  const webviewRect = webview.getBoundingClientRect?.()
  if (!webviewRect) return
  selectedTextAction.value = {
    text: selection.text,
    contentItemId: String(content.id),
    contentTitle: content.title || activeContentTab.value?.title || '当前内容',
    source: 'wechat-remote',
    rect: {
      left: webviewRect.left + selection.rect.left,
      top: webviewRect.top + selection.rect.top,
      right: webviewRect.left + selection.rect.right,
      bottom: webviewRect.top + selection.rect.bottom,
      width: selection.rect.right - selection.rect.left,
      height: selection.rect.bottom - selection.rect.top,
    },
  }
}

function applyRemoteOutlineMessage(key, message) {
  if (message.kind === 'outline') {
    remoteOutlines[key] = {
      entries: message.entries,
      activeId: message.activeId,
    }
    return
  }
  if (message.kind === 'active' && remoteOutlines[key]) {
    remoteOutlines[key].activeId = message.activeId
  }
}

function scrollToRemoteOutlineEntry(entry) {
  const webview = activeRemoteOutlineWebview.value
  const id = String(entry?.id || '')
  if (!webview?.executeJavaScript || !id) return
  void webview.executeJavaScript(
    `window.__knowledgeHubRemoteOutlineScrollTo?.(${JSON.stringify(id)})`
  ).catch(() => {})
}

function handleWechatRemotePageFailed(contentItemId, event) {
  if (event?.target && event.target !== wechatRemoteWebviews.get(contentItemId)) return
  if (Number(event?.errorCode) === -3) return
  const page = wechatRemotePages[contentItemId]
  if (!page) return
  clearWechatRemoteLoadTimer(contentItemId)
  page.status = 'failed'
  page.visible = false
}

function toggleWechatRemotePage() {
  const content = activeWechatContent.value
  if (!content || !canOpenWechatRemotePage.value) return
  clearSelectedTextAction()
  const existing = wechatRemotePages[content.id]
  if (!existing) {
    wechatRemotePages[content.id] = {
      contentItemId: content.id,
      sourceUrl: content.source_url,
      status: 'loading',
      visible: true,
      loadAttempt: 0,
    }
    scheduleWechatRemoteLoadTimeout(content.id)
    return
  }
  if (existing.status === 'loading') return
  if (existing.status === 'failed') {
    reloadWechatRemotePage(existing)
    return
  }
  existing.visible = !existing.visible
}

function reloadWechatRemotePage(page) {
  if (!page?.sourceUrl) return
  page.visible = true
  page.status = 'loading'
  scheduleWechatRemoteLoadTimeout(page.contentItemId)
  const webview = wechatRemoteWebviews.get(page.contentItemId)
  if (webview && typeof webview.reload === 'function') {
    webview.reload()
    return
  }
  page.loadAttempt += 1
}

function isReportTab(tabId) {
  const content = props.contentForTab(tabId)
  return !isMiniProgramCaptureTab(tabId)
    && (content?.source_provider === 'wechat_report' || content?.content_type === 'report')
}

function isExternalMarkdownTab(tabId) {
  const content = props.contentForTab(tabId)
  return ['local_markdown', 'local_file'].includes(content?.source_provider)
    && content?.content_type === 'document'
    && !isLocalHtmlArticleTab(tabId)
    && !isExternalPdfTab(tabId)
}

function isExternalPdfTab(tabId) {
  const content = props.contentForTab(tabId)
  if (content?.source_provider !== 'local_file' || content?.content_type !== 'document') return false
  return String(content?.source_name || '').includes('PDF')
    || /\.pdf$/iu.test(String(content?.original_file_path || ''))
}

function isExternalImageTab(tabId) {
  const content = props.contentForTab(tabId)
  return content?.source_provider === 'local_file' && content?.content_type === 'image'
}

function hasRemoteSource(tabId) {
  return /^https?:\/\//iu.test(sourceUrlForTab(tabId))
}

function sourceUrlForTab(tabId) {
  const content = props.contentForTab(tabId)
  const storedSourceUrl = String(content?.source_url || '')
  if (/^https?:\/\//iu.test(storedSourceUrl)) return storedSourceUrl
  const originalSourceUrl = String(content?.source_metadata?.original_source_url || '')
  return /^https?:\/\//iu.test(originalSourceUrl) ? originalSourceUrl : ''
}

function externalImportKindLabel(tabId) {
  const label = String(props.contentForTab(tabId)?.source_name || '').replace(/^外部\s*/u, '').trim()
  return label || 'Markdown 文档'
}

function isLongformReaderTab(tabId) {
  return isReportTab(tabId) || isExternalMarkdownTab(tabId)
}

function isWechatCoverGenerating(tabId) {
  const contentItemId = String(props.contentForTab(tabId)?.id || '')
  return Boolean(contentItemId && props.wechatCoverGeneratingContentIds.includes(contentItemId))
}

function isWechatCoverSwitching(tabId) {
  const contentItemId = String(props.contentForTab(tabId)?.id || '')
  return Boolean(
    contentItemId
    && props.wechatCoverSwitchingContentIds.includes(contentItemId)
  )
}

function reportCoverHistoryForTab(tabId) {
  const contentItemId = String(props.contentForTab(tabId)?.id || '')
  return props.wechatCoverHistoryForContent(contentItemId) || {
    active_cover_id: '',
    covers: [],
  }
}

function reportCoverVersionsForTab(tabId) {
  const covers = reportCoverHistoryForTab(tabId).covers
  return Array.isArray(covers) ? covers : []
}

function reportCoverIndexForTab(tabId) {
  const history = reportCoverHistoryForTab(tabId)
  const covers = reportCoverVersionsForTab(tabId)
  const index = covers.findIndex((item) => item.id === history.active_cover_id)
  return index >= 0 ? index : Math.max(0, covers.length - 1)
}

function reportCoverUrlForTab(tabId) {
  const covers = reportCoverVersionsForTab(tabId)
  const selected = covers[reportCoverIndexForTab(tabId)]
  return selected?.url || props.contentForTab(tabId)?.cover_url || ''
}

function canNavigateReportCover(tabId, direction) {
  if (
    isWechatCoverGenerating(tabId)
    || isWechatCoverSwitching(tabId)
  ) return false
  const nextIndex = reportCoverIndexForTab(tabId) + Number(direction || 0)
  return nextIndex >= 0 && nextIndex < reportCoverVersionsForTab(tabId).length
}

function selectAdjacentReportCover(tabId, direction) {
  if (!canNavigateReportCover(tabId, direction)) return
  const contentItemId = String(props.contentForTab(tabId)?.id || '')
  const nextIndex = reportCoverIndexForTab(tabId) + Number(direction || 0)
  const cover = reportCoverVersionsForTab(tabId)[nextIndex]
  if (!contentItemId || !cover?.id) return
  emit('select-wechat-cover', {
    contentItemId,
    coverId: cover.id,
  })
}

function requestWechatCoverGeneration(tabId) {
  const content = props.contentForTab(tabId)
  if (!content) return
  emit(content.cover_url ? 'regenerate-wechat-cover' : 'generate-wechat-cover', content)
}

const articleOutlineHeadingSelector = 'h1, h2, h3, h4, .article-section-heading'

function normalizedOutlineText(value) {
  return String(value || '').replace(/\s+/gu, ' ').trim()
}

function isArticleOutlineHeading(element, text) {
  const normalized = normalizedOutlineText(text)
  if (normalized.length < 2 || normalized.length > 84) return false
  // The reader already renders the article title and metadata above the
  // iframe. Do not make a duplicated page H1 into a navigation waypoint.
  const title = normalizedOutlineText(props.contentForTab(activeContentTab.value?.id)?.title)
  if (title && normalized === title) return false
  if (/^(?:原文内容|图片文字\s*\d*|微信公众号|微信公众平台|校园论坛)$/u.test(normalized)) return false
  if (element.closest('table, figure, figcaption, [data-wechat-image-ocr]')) return false
  return true
}

function articleOutlineHeadingLevel(element) {
  const tag = String(element?.tagName || '').toUpperCase()
  // The rail intentionally communicates two levels. Treat captured H1/H2 as
  // primary sections and H3/H4 or recovered numbered text as children.
  return ['H1', 'H2'].includes(tag) ? 2 : 3
}

function isMiniProgramCaptureTab(tabId) {
  const content = props.contentForTab(tabId)
  return content?.source_provider === 'wechat_miniprogram'
    && ['forum_capture', 'report'].includes(content?.content_type)
}

function reportTypeLabel(tabId) {
  const title = props.contentForTab(tabId)?.title || ''
  return title.includes('周报') ? '周报' : '日报'
}

function reportDisplayTitle(tabId) {
  const rawTitle = props.contentForTab(tabId)?.title || props.workspaceTabById(tabId)?.title || ''
  const groupName = rawTitle.includes('｜') ? rawTitle.split('｜').pop()?.trim() : ''
  return groupName ? `${groupName}${reportTypeLabel(tabId)}` : rawTitle
}

function reportDateLabel(tabId) {
  const title = props.contentForTab(tabId)?.title || props.workspaceTabById(tabId)?.title || ''
  const dates = title.match(/\d{4}-\d{2}-\d{2}/g) || []
  if (!dates.length) return '生成报告'
  const formatDate = (value, showYear) => {
    const [year, month, day] = value.split('-').map(Number)
    return `${showYear ? `${year}年` : ''}${month}月${day}日`
  }
  if (dates.length === 1) return formatDate(dates[0], true)
  const sameYear = dates[0].slice(0, 4) === dates[1].slice(0, 4)
  return `${formatDate(dates[0], true)}—${formatDate(dates[1], !sameYear)}`
}

function reportGeneratedLabel(tabId) {
  const timestamp = props.contentForTab(tabId)?.created_at || props.workspaceTabById(tabId)?.opened_at
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return ''
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `生成于 ${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${hour}:${minute}`
}

function articleTextForTab(tabId) {
  return props.transcriptForTab(tabId) || ''
}

function articleAttachmentsForTab(tabId) {
  const attachments = props.articlePreviewForTab(tabId)?.attachments
  return Array.isArray(attachments) ? attachments : []
}

function previewFindRoot() {
  const tab = activeContentTab.value
  if (!tab) return null
  if (isWechatRemoteVisible.value || isLocalHtmlRemoteVisible.value) return null
  if (isArticleTab(tab.id) && props.articlePreviewForTab(tab.id)?.html) {
    return activeArticlePreviewFrame.value?.contentDocument?.body || null
  }
  if (isReportTab(tab.id) || isExternalMarkdownTab(tab.id) || isMiniProgramCaptureTab(tab.id)) {
    return contentHero.value?.querySelector('.report-markdown') || null
  }
  if (hasTranscriptTimeline(tab.id)) return contentHero.value?.querySelector('.transcript-timeline') || null
  return contentHero.value?.querySelector('.article-preview-body') || null
}

function updatePreviewFindActiveMatch(index, { scroll = false } = {}) {
  for (const match of previewFindMatches) match.classList.remove('preview-find-active')
  if (!previewFindMatches.length) {
    previewFindActiveIndex.value = -1
    return
  }
  const nextIndex = (index + previewFindMatches.length) % previewFindMatches.length
  const match = previewFindMatches[nextIndex]
  match.classList.add('preview-find-active')
  previewFindActiveIndex.value = nextIndex
  if (scroll) {
    seekMediaToPreviewFindMatch(match)
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    match.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center', inline: 'nearest' })
  }
}

function seekMediaToPreviewFindMatch(match) {
  const tab = activeContentTab.value
  if (!tab || !hasTranscriptTimeline(tab.id)) return
  const startSeconds = Number(match.closest('.timeline-segment')?.dataset.startSeconds)
  if (!Number.isFinite(startSeconds)) return
  handleTimelineSegmentClick(tab.id, startSeconds)
}

function clearPreviewFindHighlights() {
  if (previewFindHighlightRoot) clearPreviewTextHighlights(previewFindHighlightRoot)
  previewFindHighlightRoot = null
  previewFindMatches = []
  previewFindMatchCount.value = 0
  previewFindActiveIndex.value = -1
  previewFindTruncated.value = false
}

function clearLocalHtmlRemoteFind({ clearSelection = false } = {}) {
  const webview = activeLocalHtmlRemoteWebview.value
  if (!webview?.stopFindInPage) return
  try {
    webview.stopFindInPage(clearSelection ? 'clearSelection' : 'keepSelection')
  } catch {
    // The remote page may have just been detached while tabs are switching.
  }
  localHtmlRemoteFindRequestId = null
}

function refreshLocalHtmlRemoteFind() {
  const query = previewFindQuery.value.trim()
  const webview = activeLocalHtmlRemoteWebview.value
  previewFindMatchCount.value = 0
  previewFindActiveIndex.value = -1
  previewFindTruncated.value = false
  if (!query || !webview?.findInPage) {
    clearLocalHtmlRemoteFind({ clearSelection: !query })
    return
  }
  try {
    localHtmlRemoteFindRequestId = webview.findInPage(query, {
      forward: true,
      findNext: false,
      matchCase: false,
    })
  } catch {
    localHtmlRemoteFindRequestId = null
  }
}

function updatePreviewFindQuery(query) {
  previewFindQuery.value = query
  // The isolated original-page preview has its own DOM.  Query it directly
  // from the input event so matching is live; Enter remains navigation only.
  if (previewFindOpen.value && isLocalHtmlRemoteVisible.value) {
    refreshLocalHtmlRemoteFind()
  }
}

function refreshPreviewFind() {
  previewFindRefreshFrame = 0
  if (!previewFindOpen.value) return
  if (isLocalHtmlRemoteVisible.value) {
    clearPreviewFindHighlights()
    refreshLocalHtmlRemoteFind()
    return
  }
  const root = previewFindRoot()
  if (previewFindHighlightRoot && previewFindHighlightRoot !== root) clearPreviewTextHighlights(previewFindHighlightRoot)
  previewFindHighlightRoot = root
  const highlighted = highlightPreviewText(root, previewFindQuery.value)
  previewFindMatches = highlighted.matches
  previewFindTruncated.value = highlighted.truncated
  previewFindMatchCount.value = previewFindMatches.length
  updatePreviewFindActiveMatch(0)
}

function schedulePreviewFindRefresh() {
  if (!previewFindOpen.value) return
  if (previewFindRefreshFrame) window.cancelAnimationFrame(previewFindRefreshFrame)
  previewFindRefreshFrame = window.requestAnimationFrame(refreshPreviewFind)
}

function openPreviewFind() {
  if (!activeContentTab.value) return
  if (!previewFindOpen.value) {
    previewFindRestoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const selectedText = window.getSelection?.()?.toString().trim() || ''
    if (!previewFindQuery.value && selectedText && selectedText.length <= 120) previewFindQuery.value = selectedText
    previewFindOpen.value = true
  }
  previewFindFocusRequest.value += 1
  schedulePreviewFindRefresh()
}

function closePreviewFind() {
  previewFindOpen.value = false
  previewFindQuery.value = ''
  clearLocalHtmlRemoteFind({ clearSelection: true })
  clearPreviewFindHighlights()
  const target = previewFindRestoreFocus?.isConnected ? previewFindRestoreFocus : contentHero.value
  previewFindRestoreFocus = null
  target?.focus?.({ preventScroll: true })
}

function handleDocumentSelectionChange() {
  if (isWechatRemoteVisible.value) {
    clearSelectedTextAction()
    return
  }
  if (selectedTextPointerIsDown) {
    clearSelectedTextAction()
    return
  }
  captureReadableSelection(window.getSelection?.(), document)
}

function handleArticlePreviewSelectionChange(event) {
  const frameDocument = event?.target
  if (selectedTextPointerIsDown) {
    clearSelectedTextAction()
    return
  }
  captureReadableSelection(frameDocument?.defaultView?.getSelection?.(), frameDocument)
}

function handleSelectedTextPointerDown(event) {
  // The floating action is teleported to ``body``. Its pointerdown therefore
  // reaches this document-level capture listener before the button's own
  // handler. Preserve the captured quote so its click can hand it to the
  // assistant instead of clearing the action one event too early.
  if (event?.target instanceof Element && event.target.closest('.reader-selection-ask')) return
  if (shouldClaimReaderFocus(event?.target)) {
    contentHero.value?.focus({ preventScroll: true })
  }
  selectedTextPointerIsDown = true
  if (selectedTextActionRevealFrame) {
    window.cancelAnimationFrame(selectedTextActionRevealFrame)
    selectedTextActionRevealFrame = 0
  }
  clearSelectedTextAction()
}

function handleSelectedTextPointerUp(event) {
  selectedTextPointerIsDown = false
  const ownerDocument = event?.currentTarget?.defaultView ? event.currentTarget : document
  if (selectedTextActionRevealFrame) window.cancelAnimationFrame(selectedTextActionRevealFrame)
  selectedTextActionRevealFrame = window.requestAnimationFrame(() => {
    selectedTextActionRevealFrame = 0
    if (isWechatRemoteVisible.value) return
    captureReadableSelection(ownerDocument.defaultView?.getSelection?.(), ownerDocument)
  })
}

function handleSelectedTextPointerCancel() {
  selectedTextPointerIsDown = false
  clearSelectedTextAction()
}

function captureReadableSelection(selection, ownerDocument) {
  if (!selection || selection.isCollapsed || !selection.rangeCount) {
    clearSelectedTextAction()
    return
  }
  const range = selection.getRangeAt(0)
  const quote = String(selection.toString() || '').trim()
  const text = quote.replace(/\s+/gu, ' ').trim()
  const tab = activeContentTab.value
  const content = tab ? props.contentForTab(tab.id) : null
  if (!text || !content?.id || text.length < 2 || !selectionBelongsToReader(range, ownerDocument)) {
    clearSelectedTextAction()
    return
  }
  const rangeRect = range.getBoundingClientRect()
  if (!rangeRect.width && !rangeRect.height) {
    clearSelectedTextAction()
    return
  }
  const frame = activeArticlePreviewFrame.value
  const isFrameSelection = ownerDocument && frame?.contentDocument === ownerDocument
  const frameRect = isFrameSelection ? frame.getBoundingClientRect() : null
  selectedTextAction.value = {
    text: text.slice(0, 12000),
    contentItemId: String(content.id),
    contentTitle: content.title || tab?.title || '当前内容',
    rect: isFrameSelection && frameRect
      ? {
          left: frameRect.left + rangeRect.left,
          top: frameRect.top + rangeRect.top,
          width: rangeRect.width,
          height: rangeRect.height,
          right: frameRect.left + rangeRect.right,
          bottom: frameRect.top + rangeRect.bottom,
        }
      : rangeRect,
  }
}

function selectionBelongsToReader(range, ownerDocument) {
  const container = range.commonAncestorContainer
  const element = container?.nodeType === Node.ELEMENT_NODE ? container : container?.parentElement
  if (!element || element.nodeType !== Node.ELEMENT_NODE) return false
  if (ownerDocument && activeArticlePreviewFrame.value?.contentDocument === ownerDocument) return ownerDocument.body.contains(element)
  return Boolean(element.closest('.report-markdown, .article-preview-body, .transcript-timeline'))
}

function clearSelectedTextAction() {
  selectedTextAction.value = null
}

function askAboutSelectedText() {
  const selection = selectedTextAction.value
  if (!selection) return
  emit('ask-about-selection', {
    contentItemId: selection.contentItemId,
    contentTitle: selection.contentTitle,
    text: selection.text,
  })
  window.getSelection?.()?.removeAllRanges()
  activeArticlePreviewFrame.value?.contentDocument?.defaultView?.getSelection?.()?.removeAllRanges()
  if (selection.source === 'wechat-remote') {
    const webview = wechatRemoteWebviews.get(selection.contentItemId)
    void webview?.executeJavaScript?.('window.getSelection?.().removeAllRanges()').catch(() => {})
  }
  clearSelectedTextAction()
}

function navigatePreviewFind(direction) {
  if (!previewFindQuery.value.trim()) return
  if (isLocalHtmlRemoteVisible.value) {
    const webview = activeLocalHtmlRemoteWebview.value
    if (!webview?.findInPage) return
    try {
      localHtmlRemoteFindRequestId = webview.findInPage(previewFindQuery.value.trim(), {
        forward: direction >= 0,
        findNext: true,
        matchCase: false,
      })
    } catch {
      localHtmlRemoteFindRequestId = null
    }
    return
  }
  if (!previewFindMatches.length) return
  updatePreviewFindActiveMatch(previewFindActiveIndex.value + direction, { scroll: true })
}

function handleReadingScroll(event) {
  refreshReadingProgress(event?.currentTarget)
}

function handleArticlePreviewFrameScroll() {
  refreshReadingProgress(readingProgressFrameDocument?.scrollingElement || null)
}

function detachReadingProgressFrame() {
  if (!readingProgressFrameDocument) return
  readingProgressFrameDocument.defaultView?.removeEventListener('scroll', handleArticlePreviewFrameScroll)
  readingProgressFrameDocument = null
}

function attachReadingProgressFrame(frameDocument) {
  if (readingProgressFrameDocument === frameDocument) return
  detachReadingProgressFrame()
  readingProgressFrameDocument = frameDocument
  frameDocument.defaultView?.addEventListener('scroll', handleArticlePreviewFrameScroll, { passive: true })
}

function activeReadingScrollRoot() {
  const tab = activeContentTab.value
  if (!tab || !supportsReadingProgress.value) return null
  if (isArticleTab(tab.id)) return activeArticlePreviewFrame.value?.contentDocument?.scrollingElement || null
  return reportReader.value
}

function refreshReadingProgress(scrollRoot = null) {
  const tab = activeContentTab.value
  if (!tab || !supportsReadingProgress.value) {
    readingProgress.value = 0
    readingCharacterCount.value = 0
    return
  }
  if (isWechatRemoteVisible.value || isLocalHtmlRemoteVisible.value) return
  const root = scrollRoot || activeReadingScrollRoot()
  if (root) {
    readingProgress.value = readingProgressFromScroll(root)
  }
  readingCharacterCount.value = readableCharacterCount(readerTextForMetadata(tab.id))
}

function scheduleReadingProgressRefresh() {
  if (readingProgressRefreshFrame) window.cancelAnimationFrame(readingProgressRefreshFrame)
  readingProgressRefreshFrame = window.requestAnimationFrame(() => {
    readingProgressRefreshFrame = 0
    refreshReadingProgress()
  })
}

function handleArticlePreviewFrameReady(event) {
  const frameDocument = event?.target?.contentDocument
  if (!frameDocument) return
  articlePreviewSelectionDocument?.removeEventListener('selectionchange', handleArticlePreviewSelectionChange)
  articlePreviewSelectionDocument?.removeEventListener('pointerdown', handleSelectedTextPointerDown, true)
  articlePreviewSelectionDocument?.removeEventListener('pointerup', handleSelectedTextPointerUp, true)
  articlePreviewSelectionDocument?.removeEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  articlePreviewSelectionDocument = frameDocument
  attachReadingProgressFrame(frameDocument)
  frameDocument.addEventListener('selectionchange', handleArticlePreviewSelectionChange)
  frameDocument.addEventListener('pointerdown', handleSelectedTextPointerDown, true)
  frameDocument.addEventListener('pointerup', handleSelectedTextPointerUp, true)
  frameDocument.addEventListener('pointercancel', handleSelectedTextPointerCancel, true)
  articleOutlineRoot.value = isArticleTab(activeContentTab.value?.id) ? frameDocument.body : null
  renderArticlePreviewMath(frameDocument)
  frameDocument.removeEventListener('keydown', handleArticlePreviewFrameKeydown)
  frameDocument.addEventListener('keydown', handleArticlePreviewFrameKeydown)
  frameDocument.removeEventListener('click', handleArticlePreviewLinkClick)
  frameDocument.addEventListener('click', handleArticlePreviewLinkClick)
  frameDocument.removeEventListener('auxclick', handleArticlePreviewLinkClick)
  frameDocument.addEventListener('auxclick', handleArticlePreviewLinkClick)
  if (!frameDocument.getElementById('knowledgehub-preview-find-styles')) {
    const rootStyle = getComputedStyle(document.documentElement)
    const highlight = rootStyle.getPropertyValue('--vk-highlight').trim()
    const accent = rootStyle.getPropertyValue('--vk-accent').trim()
    const accentStrong = rootStyle.getPropertyValue('--vk-accent-strong').trim()
    const style = frameDocument.createElement('style')
    style.id = 'knowledgehub-preview-find-styles'
    style.textContent = `
      mark.preview-find-highlight { background: color-mix(in srgb, ${highlight} 42%, transparent); color: inherit; border-radius: 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
      mark.preview-find-highlight.preview-find-active { background: color-mix(in srgb, ${accent} 48%, transparent); outline: 1px solid color-mix(in srgb, ${accentStrong} 52%, transparent); }
    `
    frameDocument.head?.append(style)
  }
  schedulePreviewFindRefresh()
  scheduleReadingProgressRefresh()
}

function renderArticlePreviewMath(frameDocument) {
  const nodes = frameDocument.querySelectorAll('.article-math[data-latex]')
  for (const node of nodes) {
    const expression = String(node.dataset.latex || '').trim()
    if (!expression || expression.length > 4000 || node.dataset.rendered === 'true') continue
    try {
      // MathML is rendered natively inside the sandboxed srcdoc iframe. It
      // keeps the same KaTeX parser used elsewhere without allowing scripts,
      // stylesheets or model-supplied HTML into the document.
      node.innerHTML = katex.renderToString(expression, {
        displayMode: node.dataset.display === 'block',
        throwOnError: false,
        strict: 'warn',
        trust: false,
        maxExpand: 1000,
        maxSize: 20,
        output: 'mathml'
      })
      node.dataset.rendered = 'true'
    } catch {
      // Keep the sanitized LaTeX text as a readable fallback.
    }
  }
}

function handleArticlePreviewLinkClick(event) {
  if (event.type === 'click' && event.button !== 0) return
  if (event.type === 'auxclick' && event.button !== 1) return
  const target = event?.target
  const anchor = target?.closest?.('a[href]') || target?.parentElement?.closest?.('a[href]')
  if (!anchor) return
  let url
  try {
    url = new URL(anchor.href)
  } catch {
    return
  }
  if (!['http:', 'https:'].includes(url.protocol)) return
  event.preventDefault()
  event.stopPropagation()
  emit('open-external-link', url.toString())
}

function isFindShortcut(event) {
  return Boolean((event.metaKey || event.ctrlKey) && !event.altKey && String(event.key || '').toLocaleLowerCase() === 'f')
}

function focusLibrarySearch() {
  const input = document.querySelector('input[name="library-search"]')
  input?.focus({ preventScroll: true })
  input?.select?.()
}

function isPreviewFocusTarget(target) {
  if (!(target instanceof Element)) return false
  return Boolean(target.closest('.workbench-editor-host'))
}

function handlePreviewFindShortcut(event) {
  if (!isFindShortcut(event)) return
  const target = event.target instanceof Element ? event.target : document.activeElement
  if (target instanceof Element && target.closest('.file-sidebar')) {
    event.preventDefault()
    focusLibrarySearch()
    return
  }
  if (props.activeView === 'library' && isPreviewFocusTarget(target)) {
    event.preventDefault()
    openPreviewFind()
  }
}

function handleDesktopPreviewFindShortcut() {
  const target = document.activeElement
  if (target instanceof Element && target.closest('.file-sidebar')) {
    focusLibrarySearch()
    return
  }
  if (props.activeView === 'library' && isPreviewFocusTarget(target)) openPreviewFind()
}

function handleArticlePreviewFrameKeydown(event) {
  if (!isFindShortcut(event)) return
  event.preventDefault()
  openPreviewFind()
}

function readerTextForMetadata(tabId) {
  const content = props.contentForTab(tabId)
  if (!content) return ''

  if (isTimedMediaTab(tabId)) {
    return sourceBodyForCharacterCount(
      timelineSegmentsForTab(tabId).map((segment) => segment.text).join('\n')
        || props.transcriptForTab(tabId),
      ['视频字幕或转写', '原始转写文本', '字幕', '转写'],
    )
  }

  if (isExternalImageTab(tabId)) {
    return sourceBodyForCharacterCount(props.transcriptForTab(tabId), ['原文内容', 'OCR 正文'])
  }

  if (isArticleTab(tabId)) {
    const parsedBody = sourceBodyForCharacterCount(
      props.transcriptForTab(tabId),
      ['原文内容', '文章正文', '正文内容'],
    )
    if (parsedBody) return parsedBody
    return activeArticlePreviewFrame.value?.contentDocument?.body?.innerText || ''
  }

  if (isReportTab(tabId) || isExternalMarkdownTab(tabId)) {
    return plainTextFromHtml(
      reportBodyHtmlForCharacterCount(props.selectedMarkdownPreview)
    )
  }

  if (isMiniProgramCaptureTab(tabId)) {
    return reportMarkdown.value?.innerText || plainTextFromHtml(props.selectedMarkdownPreview)
  }

  return props.transcriptForTab(tabId)
}

function sourceBodyForCharacterCount(markdown, headings) {
  const source = String(markdown || '').replace(/^---\s*\n[\s\S]*?\n---\s*\n?/u, '')
  const section = headings
    .map((heading) => heading.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'))
    .join('|')
  if (!section) return source
  const matched = new RegExp(`^##\\s+(?:${section})\\s*$\\n([\\s\\S]*?)(?=^##\\s+|(?![\\s\\S]))`, 'imu').exec(source)
  return (matched?.[1] || source)
    .replace(/^>\s*外部导入.*$/gmu, '')
    .replace(/^\[打开原始文件\]\([^\n]+\)$/gmu, '')
    .trim()
}

function plainTextFromHtml(html) {
  if (!html) return ''
  const template = document.createElement('template')
  template.innerHTML = html
  return template.content.textContent || ''
}

function formatReadableCharacterCount(value) {
  const count = readableCharacterCount(value)
  return count ? `${count.toLocaleString('zh-CN')} 字` : '—'
}

function formatDocumentSize(content) {
  const isCurrentDocument = String(content?.id || '') === String(props.selectedContentItem?.id || '')
  const liveMarkdownSize = isCurrentDocument ? Number(props.selectedMarkdownSizeBytes || 0) : 0
  const storedMarkdownSize = Number(content?.markdown_size_bytes || 0)
  const markdownSize = liveMarkdownSize || storedMarkdownSize
  return markdownSize > 0 ? props.formatBytes(markdownSize) : '—'
}

function timelineSegmentsForTab(tabId) {
  const content = props.contentForTab(tabId)
  const segments = content?.transcript_segments || []
  const normalizedSegments = segments.map((segment, index) => ({
    position: segment.position ?? index,
    start_seconds: segment.start_seconds,
    text: segment.text || '',
    approximate: Boolean(segment.approximate),
  })).filter((segment) => segment.text)
  if (normalizedSegments.length) return normalizedSegments

  // A task response can reach the renderer a fraction earlier than the
  // cache-detail hydration. Keep the transcript visible in that narrow window
  // instead of making the user wait for the final AI summary or a reload.
  const transcript = String(props.transcriptForTab(tabId) || '').trim()
  return transcript
    ? [{ position: 0, start_seconds: 0, text: transcript, approximate: true }]
    : []
}

function hasTranscriptTimeline(tabId) {
  // A source document can expose its text through transcriptForTab for search
  // and reader metadata. That text is not timed media, so it must never turn
  // a Markdown/report reader into the timed-media transcript workspace.
  return (isVideoTab(tabId) || isAudioTab(tabId)) && timelineSegmentsForTab(tabId).length > 0
}

function verticalContentBounds() {
  return verticalContentSplitBounds(contentHero.value?.clientHeight || 0)
}

function clampVerticalContentHeight(value) {
  return clampVerticalContentSplit(value, contentHero.value?.clientHeight || 0)
}

function constrainVerticalContentSplits() {
  mediaTranscriptHeight.value = clampVerticalContentHeight(mediaTranscriptHeight.value)
  xhsImageTextHeight.value = clampVerticalContentHeight(xhsImageTextHeight.value)
}

function persistVerticalContentSplit(key, value) {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    // The current layout remains usable when storage is unavailable.
  }
}

function startMediaTranscriptResize(event) {
  const container = contentHero.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  if (rect.height <= 0) return
  event.preventDefault()
  stopMediaTranscriptResize()
  lockTextSelection()
  mediaTranscriptResizeStart = {
    top: rect.top,
    height: rect.height,
    pointerId: event.pointerId,
    element: event.currentTarget,
  }
  mediaTranscriptResizing.value = true
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', resizeMediaTranscript)
  window.addEventListener('pointerup', stopMediaTranscriptResize)
  window.addEventListener('pointercancel', stopMediaTranscriptResize)
}

function resizeMediaTranscript(event) {
  if (!mediaTranscriptResizeStart || event.pointerId !== mediaTranscriptResizeStart.pointerId) return
  event.preventDefault()
  const offset = event.clientY - mediaTranscriptResizeStart.top
  const next = Math.round((offset / mediaTranscriptResizeStart.height) * 100)
  mediaTranscriptHeight.value = clampVerticalContentHeight(next)
}

function stopMediaTranscriptResize(event, shouldPersist = event?.type === 'pointerup') {
  if (event?.pointerId !== undefined && mediaTranscriptResizeStart && event.pointerId !== mediaTranscriptResizeStart.pointerId) return
  window.removeEventListener('pointermove', resizeMediaTranscript)
  window.removeEventListener('pointerup', stopMediaTranscriptResize)
  window.removeEventListener('pointercancel', stopMediaTranscriptResize)
  const resizeStart = mediaTranscriptResizeStart
  mediaTranscriptResizeStart = null
  if (resizeStart?.element?.hasPointerCapture?.(resizeStart.pointerId)) {
    resizeStart.element.releasePointerCapture?.(resizeStart.pointerId)
  }
  const wasResizing = mediaTranscriptResizing.value
  mediaTranscriptResizing.value = false
  unlockTextSelection()
  if (shouldPersist && wasResizing) {
    persistVerticalContentSplit('knowledgehub.media-transcript-height.v1', mediaTranscriptHeight.value)
  }
}

function handleMediaTranscriptKeydown(event) {
  const bounds = verticalContentBounds()
  let next = mediaTranscriptHeight.value
  if (event.key === 'ArrowUp') next -= 5
  else if (event.key === 'ArrowDown') next += 5
  else if (event.key === 'Home') next = bounds.min
  else if (event.key === 'End') next = bounds.max
  else return
  event.preventDefault()
  mediaTranscriptHeight.value = clampVerticalContentHeight(next)
  persistVerticalContentSplit('knowledgehub.media-transcript-height.v1', mediaTranscriptHeight.value)
}

function startXhsImageTextResize(event) {
  const container = contentHero.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  if (rect.height <= 0) return
  event.preventDefault()
  stopXhsImageTextResize()
  lockTextSelection()
  xhsImageTextResizeStart = {
    top: rect.top,
    height: rect.height,
    pointerId: event.pointerId,
    element: event.currentTarget,
  }
  xhsImageTextResizing.value = true
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', resizeXhsImageText)
  window.addEventListener('pointerup', stopXhsImageTextResize)
  window.addEventListener('pointercancel', stopXhsImageTextResize)
}

function resizeXhsImageText(event) {
  if (!xhsImageTextResizeStart || event.pointerId !== xhsImageTextResizeStart.pointerId) return
  event.preventDefault()
  const offset = event.clientY - xhsImageTextResizeStart.top
  const next = Math.round((offset / xhsImageTextResizeStart.height) * 100)
  xhsImageTextHeight.value = clampVerticalContentHeight(next)
}

function stopXhsImageTextResize(event, shouldPersist = event?.type === 'pointerup') {
  if (event?.pointerId !== undefined && xhsImageTextResizeStart && event.pointerId !== xhsImageTextResizeStart.pointerId) return
  window.removeEventListener('pointermove', resizeXhsImageText)
  window.removeEventListener('pointerup', stopXhsImageTextResize)
  window.removeEventListener('pointercancel', stopXhsImageTextResize)
  const resizeStart = xhsImageTextResizeStart
  xhsImageTextResizeStart = null
  if (resizeStart?.element?.hasPointerCapture?.(resizeStart.pointerId)) {
    resizeStart.element.releasePointerCapture?.(resizeStart.pointerId)
  }
  const wasResizing = xhsImageTextResizing.value
  xhsImageTextResizing.value = false
  unlockTextSelection()
  if (shouldPersist && wasResizing) {
    persistVerticalContentSplit('knowledgehub.xhs-image-text-height.v1', xhsImageTextHeight.value)
  }
}

function handleXhsImageTextKeydown(event) {
  const bounds = verticalContentBounds()
  let next = xhsImageTextHeight.value
  if (event.key === 'ArrowUp') next -= 5
  else if (event.key === 'ArrowDown') next += 5
  else if (event.key === 'Home') next = bounds.min
  else if (event.key === 'End') next = bounds.max
  else return
  event.preventDefault()
  xhsImageTextHeight.value = clampVerticalContentHeight(next)
  persistVerticalContentSplit('knowledgehub.xhs-image-text-height.v1', xhsImageTextHeight.value)
}

function lockTextSelection() {
  window.getSelection?.()?.removeAllRanges()
  document.body.classList.add('workspace-resizing')
}

function unlockTextSelection() {
  document.body.classList.remove('workspace-resizing')
}

function handlePlayerTimeUpdate(seconds) {
  const value = Number(seconds)
  currentPlaybackTime.value = Number.isFinite(value) ? value : 0
}

function handleAudioPlaybackChange(playing) {
  isAudioPlaying.value = Boolean(playing)
}

function toggleActiveAudioPlayback() {
  if (!isAudioTab(activeContentTab.value?.id)) return
  void activePlayer.value?.togglePlayback?.()
}

function isTimelineSegmentActive(tabId, segment) {
  return timelineSegmentKey(tabId, segment) === activeTimelineKey.value
}

function findActiveTimelineKey(tabId) {
  if (!tabId || tabId !== activeContentTab.value?.id) return ''
  const segments = timelineSegmentsForTab(tabId)
  const current = currentPlaybackTime.value
  const activeSegment = segments.find((segment, index) => {
    const start = Number(segment.start_seconds)
    if (!Number.isFinite(start) || current < start) return false
    const nextStart = Number(segments[index + 1]?.start_seconds)
    return Number.isFinite(nextStart) ? current < nextStart : true
  })
  return activeSegment ? timelineSegmentKey(tabId, activeSegment) : ''
}

function timelineSegmentKey(tabId, segment) {
  return `${tabId}:${segment.position}`
}

function setTimelineSegmentRef(tabId, segment, el) {
  const key = timelineSegmentKey(tabId, segment)
  if (el) {
    timelineSegmentRefs.set(key, el)
  } else {
    timelineSegmentRefs.delete(key)
  }
}

function scheduleActiveTranscriptScroll() {
  if (!transcriptAutoFollow.value || !activeTimelineKey.value) return
  if (transcriptScrollTimer) clearTimeout(transcriptScrollTimer)
  transcriptScrollTimer = setTimeout(async () => {
    transcriptScrollTimer = null
    await nextTick()
    if (!transcriptAutoFollow.value) return
    timelineSegmentRefs.get(activeTimelineKey.value)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center'
    })
  }, 90)
}

function pauseTranscriptAutoFollow() {
  transcriptAutoFollow.value = false
}

function resumeTranscriptAutoFollow() {
  transcriptAutoFollow.value = true
  scheduleActiveTranscriptScroll()
}

function handleTimelineSegmentClick(tabId, seconds) {
  const value = Number(seconds)
  if (Number.isFinite(value)) {
    currentPlaybackTime.value = value
    activeTimelineKey.value = findActiveTimelineKey(tabId)
  }
  transcriptAutoFollow.value = true
  scheduleActiveTranscriptScroll()
  seekMedia(tabId, seconds)
}

function seekMedia(tabId, seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value)) return
  if (tabId !== activeContentTab.value?.id) return
  activePlayer.value?.seek(value)
}

function seekToTimestamp(seconds) {
  const tab = activeContentTab.value
  if (!tab || isArticleTab(tab.id) || !activePlayer.value) return false
  const value = Number(seconds)
  if (!Number.isFinite(value) || value < 0) return false
  handleTimelineSegmentClick(tab.id, value)
  return true
}

function focusSourceReader() {
  const reader = reportReader.value || contentHero.value?.querySelector('.article-reader')
  if (!(reader instanceof HTMLElement)) return false
  reader.focus?.({ preventScroll: true })
  reader.scrollTo?.({ top: 0, behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  return true
}

defineExpose({
  seekToTimestamp,
  focusSourceReader,
})

function formatTimelineTime(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value)) return '--:--'
  const total = Math.max(0, Math.floor(value))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

function exportVideoSubtitles(tabId) {
  const segments = timelineSegmentsForTab(tabId)
  if (!segments.length) return
  const lines = segments.map((segment) => `[${formatTimelineTime(segment.start_seconds)}] ${segment.text.trim()}`)
  const title = String(props.contentForTab(tabId)?.title || '字幕').trim()
  const filename = `${(title || '字幕').replace(/[\\/:*?"<>|]+/gu, '-').slice(0, 80)}-字幕.txt`
  const url = URL.createObjectURL(new Blob([`\uFEFF${lines.join('\n').trimEnd()}\n`], { type: 'text/plain;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
</script>

<style scoped>
.main-canvas {
  height: 100%;
  min-width: 0;
  margin: 0;
  overflow-y: auto;
  padding: 0;
  background: var(--vk-bg-center);
  color: var(--vk-text);
}

.canvas-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  min-height: 30px;
  margin: 0;
  padding: 4px 8px;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
}

.canvas-toolbar-actions-only {
  justify-content: flex-end;
}

.canvas-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.workspace-tool-surface {
  position: relative;
  display: grid;
  grid-template-rows: minmax(280px, 1fr) auto;
  gap: 0;
  margin: 0;
  padding-inline: 0;
  min-height: 100%;
}

.workbench-editor-host {
  position: relative;
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: 36px minmax(0, 1fr);
  margin: 0;
  padding-inline: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: var(--vk-bg-center);
}

.workbench-editor-host.no-editor-tabs {
  grid-template-rows: minmax(0, 1fr);
}

.workbench-editor-host.no-editor-tabs .tab-content-workspace {
  grid-row: 1;
}

.tab-content-workspace {
  position: relative;
  z-index: 0;
  grid-row: 2;
  min-height: 0;
  height: 100%;
  margin: 0;
  overflow: hidden;
  padding: 0;
  border-radius: 0;
  background: var(--vk-bg-center);
}

.content-workspace {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0;
  height: 100%;
  margin: 0;
  padding-inline: 0;
  min-height: 0;
}

.content-hero {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
  height: auto;
  min-height: 0;
  margin: 0;
  overflow: hidden;
  padding-inline: 0;
}

.content-hero.media-transcript-layout {
  display: grid;
  grid-template-rows:
    minmax(min(150px, calc(50% - 4px)), var(--media-height, 56%))
    8px
    minmax(min(160px, calc(50% - 4px)), 1fr);
}

.content-hero.xhs-image-text-layout {
  display: grid;
  grid-template-rows:
    minmax(min(150px, calc(50% - 4px)), var(--xhs-image-height, 56%))
    8px
    minmax(min(160px, calc(50% - 4px)), 1fr);
}

.content-hero.media-transcript-layout.is-resizing-media {
  user-select: none;
}

.content-hero.xhs-image-text-layout.is-resizing-xhs {
  user-select: none;
}

.content-hero.media-transcript-layout,
.content-hero.media-transcript-layout .content-media-frame,
.content-hero.media-transcript-layout .media-transcript-splitter,
.content-hero.media-transcript-layout .transcript-timeline,
.content-hero.xhs-image-text-layout,
.content-hero.xhs-image-text-layout .content-media-frame,
.content-hero.xhs-image-text-layout .xhs-image-text-splitter,
.content-hero.xhs-image-text-layout .xhs-text-reader {
  border-radius: 0;
}

.content-hero.media-transcript-layout .content-media-frame {
  height: 100%;
  max-height: none;
  aspect-ratio: auto;
  /* Video, splitter and transcript form one continuous workbench region,
     rather than a rounded media card placed above a text panel. */
}

/* Both media players render an inner root. Keep every media surface square so
   video and audio join the shared splitter without inner rounded corners. */
.content-hero.media-transcript-layout .content-media-frame :deep(.art-video-player),
.content-hero.media-transcript-layout .content-media-frame :deep(.art-video-container),
.content-hero.media-transcript-layout .content-media-frame :deep(.artplayer),
.content-hero.media-transcript-layout .content-media-frame :deep(.art-audio-player),
.content-hero.media-transcript-layout .content-media-frame :deep(.art-audio-waveform) {
  border-radius: 0;
}

.content-hero.xhs-image-text-layout .content-media-frame {
  height: 100%;
  max-height: none;
  aspect-ratio: auto;
  /* The dedicated splitter owns the only visible boundary between image and
     text. The generic media-frame bottom border would create a duplicate. */
  border-bottom: 0;
}

.content-media-frame {
  flex: 0 0 auto;
  width: 100%;
  aspect-ratio: 900 / 383;
  max-height: 50vh;
}

.content-workspace.article-mode .content-hero,
.content-workspace.report-mode .content-hero,
.content-workspace.image-mode .content-hero,
.content-workspace.pdf-mode .content-hero,
.content-workspace.capture-mode .content-hero {
  flex: 1 1 auto;
}

.content-workspace.report-mode,
.content-workspace.report-mode .content-hero,
.content-media-frame.report-frame,
.content-workspace.report-mode .report-reader,
.content-workspace.image-mode,
.content-workspace.image-mode .content-hero,
.content-media-frame.image-frame,
.content-workspace.image-mode .image-reader,
.content-workspace.pdf-mode,
.content-workspace.pdf-mode .content-hero,
.content-media-frame.pdf-frame,
.content-workspace.pdf-mode .pdf-reader,
.content-workspace.capture-mode,
.content-workspace.capture-mode .content-hero,
.content-media-frame.capture-frame,
.content-workspace.capture-mode .capture-reader {
  background: var(--vk-bg-panel);
}

.content-media-frame.article-frame,
.content-media-frame.report-frame,
.content-media-frame.image-frame,
.content-media-frame.pdf-frame,
.content-media-frame.capture-frame {
  flex: 1 1 auto;
  min-height: 0;
  aspect-ratio: auto;
  max-height: none;
}

.content-media-frame.image-frame {
  border: 0;
  border-radius: 0;
}

.content-media-frame.pdf-frame {
  border: 0;
  border-radius: 0;
}

/* Audio is a workbench media surface, even before transcription is ready.
   It must never fall back to the rounded generic media-card treatment. */
.content-media-frame.audio-frame {
  /* app.css retains a late global media-frame radius for older readers.
     Audio is deliberately a square workbench surface, so override it here. */
  border-radius: 0 !important;
}

.content-media-frame.audio-frame :deep(.art-audio-player),
.content-media-frame.audio-frame :deep(.art-audio-waveform) {
  border-radius: 0 !important;
}

.media-transcript-splitter,
.xhs-image-text-splitter {
  position: relative;
  z-index: 4;
  /* Keep the generous 8px drag target, but render the same 1px divider used
     by the left and right workbench panes. */
  height: 8px;
  margin: 0;
  cursor: row-resize;
  background: var(--vk-bg-center);
  touch-action: none;
}

.media-transcript-splitter::before,
.xhs-image-text-splitter::before {
  content: "";
  position: absolute;
  top: calc(50% - 0.5px);
  right: 0;
  left: 0;
  height: 1px;
  background: var(--vk-border);
  transition: background-color var(--vk-motion-standard) ease;
}

.media-transcript-splitter:focus-visible,
.xhs-image-text-splitter:focus-visible {
  outline: none;
}

.media-transcript-splitter:focus-visible::before,
.xhs-image-text-splitter:focus-visible::before,
.is-resizing-xhs .xhs-image-text-splitter::before,
.is-resizing-media .media-transcript-splitter::before {
  background: var(--vk-accent);
}

@media (hover: hover) and (pointer: fine) {
  .xhs-image-text-splitter:hover::before,
  .media-transcript-splitter:hover::before {
    background: var(--vk-accent);
  }
}

.content-media-frame,
.media-frame {
  position: relative;
  min-height: 0;
  margin: 0;
  padding-inline: 0;
  display: flex;
  align-items: stretch;
  justify-content: center;
  overflow: hidden;
  border: 0;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
}

/* A timed-media player is absolutely positioned. The preview frame, rather
   than the surrounding workspace, must be its containing block so waveform
   and transcript remain two rows of the same grid. */
.content-media-frame {
  border-radius: 0;
}

.media-frame {
  min-height: clamp(260px, 42vh, 560px);
  display: grid;
  place-items: center;
  border-radius: var(--vk-radius-surface);
}

.content-media-frame video,
.content-media-frame img,
.media-frame video {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  max-height: none;
  object-fit: contain;
  background: transparent;
}

.media-processing-state {
  position: absolute;
  z-index: 3;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 8px;
  align-items: center;
  width: min(360px, calc(100% - 36px));
  padding: 10px 12px;
  color: var(--vk-on-media);
  background: color-mix(in srgb, var(--vk-media-surface) 88%, transparent);
  border: 1px solid var(--vk-media-border);
  border-radius: 10px;
  box-shadow: 0 10px 28px color-mix(in srgb, var(--vk-media-surface) 22%, transparent);
  backdrop-filter: blur(10px);
}

.media-processing-state strong {
  font-size: 13px;
  line-height: 18px;
}

.media-processing-state small {
  grid-column: 2;
  color: var(--vk-media-muted);
  font-size: 12px;
  line-height: 17px;
}

.media-processing-stages {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin: 2px 0 0;
  padding: 0;
  color: var(--vk-media-subtle);
  font-size: 11px;
  line-height: 15px;
  list-style: none;
}

.media-processing-stages li { display: inline-flex; align-items: center; gap: 4px; }
.media-processing-stages li > span { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.media-processing-stages .is-active { color: var(--vk-on-media); }
.media-processing-stages .is-done { color: color-mix(in srgb, var(--vk-accent) 72%, var(--vk-on-media)); }

.media-cache-expired {
  position: absolute;
  z-index: 3;
  right: 18px;
  bottom: 18px;
  max-width: min(430px, calc(100% - 36px));
  padding: 10px 12px;
  color: var(--vk-on-media);
  font-size: 12px;
  line-height: 1.5;
  background: color-mix(in srgb, var(--vk-media-surface) 88%, transparent);
  border: 1px solid var(--vk-media-border);
  border-radius: 10px;
  box-shadow: 0 10px 28px color-mix(in srgb, var(--vk-media-surface) 22%, transparent);
  backdrop-filter: blur(10px);
}

.media-processing-spinner {
  width: 15px;
  height: 15px;
  border: 2px solid var(--vk-media-spinner);
  border-top-color: var(--vk-on-media);
  border-radius: 50%;
  animation: media-processing-spin 0.8s linear infinite;
}

@keyframes media-processing-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .media-processing-spinner { animation: none; }
}

.article-reader {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  color: var(--vk-reader-text);
  background: var(--vk-reader-canvas);
}

.article-reader-inner {
  width: min(var(--vk-reader-width), 100%);
  min-height: 100%;
  height: 100%;
  margin: 0 auto;
  padding: 24px 30px 34px;
}

.article-reader-snapshot-inner {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 0;
  padding-bottom: 0;
  padding-right: 0;
  padding-left: 0;
}

.article-snapshot-reader {
  overflow: hidden;
}

.article-reader-snapshot-inner > .article-reader-head,
.article-reader-snapshot-inner > .article-preview-meta,
.article-reader-snapshot-inner > .article-preview-body {
  box-sizing: border-box;
  width: min(820px, 100%);
  margin-right: auto;
  margin-left: auto;
  padding-right: 30px;
  padding-left: 30px;
}

.remote-wechat-active .article-reader-head,
.remote-wechat-active .article-preview-meta {
  display: none;
}

.local-html-source-active {
  background: var(--vk-bg-center);
}

.local-html-source-active .article-reader-head,
.local-html-source-active .article-preview-meta {
  display: none;
}

.local-html-source-active .article-reader-snapshot-inner {
  height: 100%;
}

.report-reader-inner {
  width: min(var(--vk-reader-width), 100%);
  padding-top: 28px;
  background: var(--vk-reader-surface);
}

.report-reader-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--vk-space-panel);
  margin-bottom: 22px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--vk-divider-subtle);
}

.report-reader-heading {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.report-reader-kicker {
  color: var(--vk-reader-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.article-reader-head.report-reader-head h2 {
  margin: 0;
  font-size: clamp(24px, 3vw, 30px);
  color: var(--vk-reader-text);
  font-family: var(--vk-reader-font);
  font-weight: 680;
  line-height: 1.25;
  letter-spacing: -0.025em;
}

.report-reader-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0;
  margin: 0;
  color: var(--vk-reader-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  letter-spacing: var(--vk-tracking-meta);
}

.report-reader-meta span + span::before {
  content: "·";
  margin: 0 7px;
  color: color-mix(in srgb, var(--vk-reader-muted) 58%, transparent);
}

.image-reader {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--vk-bg-center);
}

.image-reader-figure {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.image-reader-figure img {
  display: block;
  width: 100%;
  max-width: none;
  height: auto;
  max-height: none;
}

.pdf-reader {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: var(--vk-bg-center);
}

.pdf-preview-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  background: var(--vk-bg-center);
}

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

.report-cover-arrow.is-previous {
  left: var(--vk-space-cluster);
}

.report-cover-arrow.is-next {
  right: var(--vk-space-cluster);
}

.report-cover-arrow:focus-visible {
  opacity: 1;
  outline: none;
  box-shadow: var(--vk-focus-ring);
}

.report-cover-arrow:disabled {
  cursor: default;
}

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
.report-cover-preview:focus-within .report-cover-count {
  opacity: 1;
}

.report-cover-preview:hover .report-cover-arrow:disabled,
.report-cover-preview:focus-within .report-cover-arrow:disabled {
  opacity: 0.34;
}

.report-cover-preview.is-switching img {
  opacity: 0.72;
}

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
  .report-cover-count {
    opacity: 1;
  }

  .report-cover-arrow:disabled {
    opacity: 0.34;
  }
}

.capture-reader-inner {
  padding-top: 24px;
}

.capture-reader-head {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--vk-divider-subtle);
}

.capture-reader-kicker {
  color: var(--vk-muted);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.06em;
}

.capture-reader-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  letter-spacing: var(--vk-tracking-meta);
}

.capture-reader-meta span + span::before {
  content: "·";
  margin: 0 7px;
  color: color-mix(in srgb, var(--vk-muted) 54%, transparent);
}

.capture-markdown :deep(h2) {
  margin-top: 1.4em;
}

.report-markdown {
  width: 100%;
  max-width: none;
  padding-bottom: 32px;
  white-space: normal;
  color: var(--vk-reader-text);
  font-family: var(--vk-reader-font);
  font-size: var(--vk-reader-size);
  line-height: var(--vk-reader-leading);
}

.report-footnote-return {
  position: absolute;
  right: var(--vk-space-panel);
  bottom: var(--vk-space-panel);
  z-index: 7;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-xs);
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 76%, transparent);
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-bg-panel) 86%, transparent);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
  backdrop-filter: blur(18px) saturate(1.15);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  font-weight: 600;
  cursor: pointer;
  will-change: opacity, transform;
  transition:
    background-color var(--vk-motion-fast) var(--vk-ease-out),
    border-color var(--vk-motion-fast) var(--vk-ease-out),
    color var(--vk-motion-fast) var(--vk-ease-out),
    box-shadow var(--vk-motion-fast) var(--vk-ease-out);
}

.report-footnote-return :deep(.el-icon) {
  font-size: 14px;
}

.report-footnote-return:hover,
.report-footnote-return:focus-visible {
  outline: none;
  border-color: color-mix(in srgb, var(--vk-accent) 44%, var(--vk-border));
  background: var(--vk-bg-panel);
  color: var(--vk-accent-strong);
}

.report-footnote-return:focus-visible {
  box-shadow: var(--vk-focus-ring), 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
}

.report-footnote-return-enter-active,
.report-footnote-return-leave-active {
  transition: opacity 180ms var(--vk-ease-out), transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
}

.report-footnote-return-enter-from,
.report-footnote-return-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.96);
}

.report-markdown :deep(p) {
  margin: 0 0 0.5em;
}

.report-markdown :deep(h1),
.report-markdown :deep(h2),
.report-markdown :deep(h3),
.report-markdown :deep(h4) {
  margin: 1em 0 0.42em;
  line-height: 1.3;
}

.report-markdown :deep([data-markdown-heading]) {
  position: relative;
}

.report-markdown :deep([data-markdown-heading]::before) {
  content: attr(data-markdown-heading);
  position: absolute;
  bottom: 0.2em;
  left: -31px;
  width: 25px;
  color: color-mix(in srgb, var(--vk-muted) 70%, transparent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1;
  text-align: right;
}

.report-markdown :deep(ul),
.report-markdown :deep(ol) {
  margin: 0 0 0.55em;
  padding-left: 1.35em;
}

.report-markdown :deep(li) {
  margin: 0.14em 0;
}

.report-markdown :deep(li > p) {
  margin: 0;
}

.report-markdown :deep(li + li) {
  margin-top: 0.2em;
}

.report-markdown :deep(blockquote) {
  margin: 0 0 0.72em;
  padding: 0.1em 0 0.1em 14px;
  border-left: 3px solid color-mix(in srgb, var(--vk-reader-accent) 72%, var(--vk-border));
  color: var(--vk-reader-text);
}

.report-markdown :deep(blockquote > :last-child) {
  margin-bottom: 0;
}

.report-markdown :deep(code) {
  padding: 0.12em 0.36em;
  border: 1px solid color-mix(in srgb, var(--vk-divider-subtle) 86%, transparent);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-hover) 64%, var(--vk-bg-panel));
  color: var(--vk-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.88em;
  line-height: inherit;
}

.report-markdown :deep(pre) {
  margin: 0 0 0.8em;
  padding: 14px 16px;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  border: 1px solid var(--vk-divider-subtle);
  border-radius: var(--vk-radius-structural);
  background: color-mix(in srgb, var(--vk-bg-panel) 68%, var(--vk-bg-center));
  color: var(--vk-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.86em;
  line-height: 1.65;
  tab-size: 2;
  white-space: pre;
}

.report-markdown :deep(pre code) {
  display: block;
  min-width: max-content;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: inherit;
}

.report-markdown :deep(hr) {
  height: 1px;
  margin: 1.05em 0;
  border: 0;
  background: var(--vk-divider-subtle);
}

.report-markdown :deep(.markdown-table-scroll) {
  width: 100%;
  margin: 0.9em 0 1.1em;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  border: 1px solid var(--vk-divider-subtle);
  border-radius: var(--vk-radius-structural);
  background: color-mix(in srgb, var(--vk-bg-panel) 78%, transparent);
}

.report-markdown :deep(table) {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  color: var(--vk-text);
  font-size: 0.92em;
  line-height: 1.55;
}

.report-markdown :deep(th),
.report-markdown :deep(td) {
  min-width: 7.5em;
  padding: 0.58em 0.72em;
  border-right: 1px solid var(--vk-divider-subtle);
  border-bottom: 1px solid var(--vk-divider-subtle);
  text-align: left;
  vertical-align: top;
}

.report-markdown :deep(th) {
  color: var(--vk-text);
  background: color-mix(in srgb, var(--vk-bg-panel) 60%, var(--vk-bg-center));
  font-weight: var(--vk-weight-strong);
}

.report-markdown :deep(tr:last-child td) {
  border-bottom: 0;
}

.report-markdown :deep(th:last-child),
.report-markdown :deep(td:last-child) {
  border-right: 0;
}

.report-markdown :deep(p:empty) {
  display: none;
}

.report-markdown :deep(.katex-display) {
  max-width: 100%;
  margin: 0.9em 0;
  padding: 2px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.report-markdown :deep(.katex) {
  color: currentColor;
  font-size: 1em;
}

.article-reader-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.article-reader-head h2 {
  min-width: 0;
  margin: 0 0 8px;
  font-family: "Songti SC", "STSong", "SimSun", "NSimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif;
  font-size: 1.25rem;
  line-height: 1.35;
  font-weight: 700;
  letter-spacing: var(--vk-tracking-display);
}

.article-reader-heading {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.article-preview-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 0 0 18px;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  letter-spacing: var(--vk-tracking-meta);
}

.article-preview-meta span + span::before {
  content: "·";
  margin: 0 7px;
  color: color-mix(in srgb, var(--vk-muted) 54%, transparent);
}

.xhs-image-reader {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: var(--vk-bg-center);
}

.xhs-gallery-track {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow-x: auto;
  overflow-y: hidden;
  overscroll-behavior-inline: contain;
  scroll-snap-type: x mandatory;
  scrollbar-width: none;
}

.xhs-gallery-track::-webkit-scrollbar { display: none; }
.xhs-gallery-track:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--vk-accent); }

.xhs-gallery-arrow,
.xhs-gallery-count {
  position: absolute;
  z-index: 2;
}

.xhs-gallery-arrow {
  top: 50%;
  display: grid;
  width: 32px;
  height: 32px;
  padding: 0;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--vk-border) 88%, transparent);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 92%, transparent);
  color: var(--vk-text);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  transition: opacity var(--vk-motion-fast) var(--vk-ease-out), background-color var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out);
}

.xhs-gallery-arrow.is-previous { left: var(--vk-space-cluster); }
.xhs-gallery-arrow.is-next { right: var(--vk-space-cluster); }

.xhs-gallery-arrow:hover:not(:disabled) {
  background: var(--vk-bg-panel);
  opacity: 1;
}

.xhs-gallery-arrow:active:not(:disabled) {
  transform: translateY(-50%) scale(0.97);
}

.xhs-gallery-arrow:focus-visible {
  outline: none;
  opacity: 1;
  pointer-events: auto;
  box-shadow: var(--vk-focus-ring);
}

.xhs-gallery-arrow:disabled {
  cursor: default;
  opacity: 0.28;
}

.xhs-gallery-count {
  right: var(--vk-space-cluster);
  bottom: var(--vk-space-cluster);
  padding: var(--vk-space-xs) var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-border) 80%, transparent);
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-bg-panel) 90%, transparent);
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  font-variant-numeric: tabular-nums;
  line-height: var(--vk-leading-label);
  opacity: 0;
  transition: opacity var(--vk-motion-fast) var(--vk-ease-out);
}

/* Gallery controls are discoverable exactly where they apply: hovering the
   image surface. Keyboard users receive the same controls on focus. */
@media (hover: hover) and (pointer: fine) {
  .xhs-image-reader:hover .xhs-gallery-arrow,
  .xhs-image-reader:hover .xhs-gallery-count,
  .xhs-gallery-track:focus-visible ~ .xhs-gallery-arrow,
  .xhs-gallery-track:focus-visible ~ .xhs-gallery-count {
    opacity: 0.78;
    pointer-events: auto;
  }

  .xhs-image-reader:hover .xhs-gallery-arrow:hover:not(:disabled) {
    opacity: 1;
  }

  .xhs-image-reader:hover .xhs-gallery-arrow:disabled {
    opacity: 0.28;
  }
}

@media (hover: none) {
  .xhs-gallery-arrow,
  .xhs-gallery-count {
    opacity: 0.78;
  }

  .xhs-gallery-arrow {
    pointer-events: auto;
  }
}

.xhs-gallery-slide {
  display: grid;
  flex: 0 0 100%;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  margin: 0;
  place-items: center;
  scroll-snap-align: start;
}

.xhs-gallery-slide img {
  display: block;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  /* The gallery is constrained by both side panes and the vertical splitter.
     Keep the complete source image visible as any of those dimensions change. */
  object-fit: contain;
  background: var(--vk-bg-center);
}

.xhs-text-reader {
  display: flex;
  min-height: 0;
  overflow: hidden;
  background: var(--vk-bg-center);
}

.xhs-text-reader-inner {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  width: 100%;
  min-height: 0;
  margin: 0;
  padding: 22px 0 0;
}

.xhs-text-reader h2 {
  flex: 0 0 auto;
  box-sizing: border-box;
  width: min(820px, 100%);
  min-width: 0;
  margin: 0 auto 14px;
  padding: 0 30px;
  color: var(--vk-text);
  font-family: "Songti SC", "STSong", "SimSun", "NSimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif;
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: var(--vk-tracking-display);
}

.xhs-text-reader .article-preview-frame {
  min-height: 0;
  height: 100%;
}

.campus-article-loading {
  width: min(760px, calc(100% - 60px));
  margin: 10px auto 0;
  color: var(--vk-muted);
  font-size: 12px;
}

.campus-article-loading span {
  display: block;
  height: 9px;
  margin-bottom: 11px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--vk-divider-subtle) 74%, transparent);
  animation: campus-preview-pulse 1.35s ease-in-out infinite alternate;
}

.campus-article-loading span:nth-child(1) { width: 92%; }
.campus-article-loading span:nth-child(2) { width: 78%; }
.campus-article-loading span:nth-child(3) { width: 56%; }

.campus-article-loading p {
  margin: 18px 0 0;
}

.campus-article-placeholder {
  min-height: 150px;
  padding: 22px 24px;
  border: 1px dashed color-mix(in srgb, var(--vk-border) 76%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--vk-bg-panel) 72%, transparent);
  color: var(--vk-muted);
}

.article-attachment-shelf {
  flex: 0 0 auto;
  width: min(820px, 100%);
  margin: 14px auto 0;
  padding: 14px 30px 18px;
  border-top: 1px solid var(--vk-divider-subtle);
  background: color-mix(in srgb, var(--vk-bg-panel) 82%, transparent);
}

.article-attachment-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 7px;
}

.article-attachment-head strong {
  font-size: 12px;
  font-weight: 680;
}

.article-attachment-head span {
  color: var(--vk-muted);
  font-size: 11px;
}

.article-attachment-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  min-height: 34px;
  padding: 6px 0;
  border: 0;
  border-top: 1px solid color-mix(in srgb, var(--vk-divider-subtle) 72%, transparent);
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  cursor: pointer;
}

.article-attachment-name {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.article-attachment-action {
  flex: 0 0 auto;
  color: var(--vk-accent-strong);
  font-size: 11px;
  font-weight: 650;
}

.article-attachment-row:hover .article-attachment-name,
.article-attachment-row:focus-visible .article-attachment-name {
  color: var(--vk-accent-strong);
}

@keyframes campus-preview-pulse {
  from { opacity: 0.42; }
  to { opacity: 0.92; }
}

.article-preview-body {
  max-width: 780px;
  white-space: pre-wrap;
  color: color-mix(in srgb, var(--vk-text) 90%, var(--vk-muted));
  font-size: var(--vk-type-reading-size);
  line-height: 1.75;
}

.article-preview-frame {
  display: block;
  flex: 1 1 auto;
  width: 100%;
  min-height: 360px;
  border: 0;
  background: transparent;
}

.article-preview-frame.local-html-original-frame {
  min-height: 0;
  background: var(--vk-bg-center);
}

.article-preview-frame.is-hidden,
.article-remote-page.is-hidden {
  display: none;
}

.reader-selection-ask {
  position: fixed;
  z-index: 60;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid color-mix(in srgb, var(--vk-accent) 34%, var(--vk-border));
  border-radius: 999px;
  background: var(--vk-bg-panel);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, #fff 48%, transparent),
    0 10px 24px color-mix(in srgb, var(--vk-text) 14%, transparent);
  color: var(--vk-accent-strong);
  font: inherit;
  font-size: var(--vk-type-label-size);
  font-weight: 650;
  letter-spacing: var(--vk-tracking-meta);
  white-space: nowrap;
  cursor: pointer;
  touch-action: manipulation;
  user-select: none;
  isolation: isolate;
  transform-origin: var(--reader-selection-origin, center top);
  transition:
    border-color 120ms ease,
    background-color 120ms ease,
    box-shadow 120ms ease,
    transform 100ms ease-out;
  will-change: opacity, transform;
}

.reader-selection-ask::after {
  position: absolute;
  right: 13px;
  top: var(--reader-selection-tail-top);
  bottom: var(--reader-selection-tail-bottom);
  z-index: -1;
  width: 8px;
  height: 8px;
  border-right: inherit;
  border-bottom: inherit;
  background: inherit;
  content: '';
  transform: rotate(45deg);
}

.reader-selection-ask:hover,
.reader-selection-ask:focus-visible {
  outline: none;
  border-color: var(--vk-accent);
  background: color-mix(in srgb, var(--vk-accent) 10%, var(--vk-bg-panel));
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, #fff 52%, transparent),
    0 12px 26px color-mix(in srgb, var(--vk-text) 17%, transparent);
}

.reader-selection-ask:active {
  transform: scale(.97);
}

.reader-selection-action-enter-active,
.reader-selection-action-leave-active {
  transform-origin: var(--reader-selection-origin, center bottom);
}

.reader-selection-action-enter-active {
  animation: reader-selection-bubble-grow 180ms cubic-bezier(.2, .8, .2, 1) both;
}

.reader-selection-action-leave-active {
  transition: opacity 100ms ease, transform 100ms ease;
}

.reader-selection-action-leave-to {
  opacity: 0;
  transform: scale(.94);
}

@keyframes reader-selection-bubble-grow {
  0% {
    opacity: 0;
    transform: scale(.68);
  }

  100% {
    opacity: 1;
    transform: scale(1);
  }
}

.article-remote-page {
  position: absolute;
  inset: 0;
  /* Electron needs flex here so the webview's shadow-DOM iframe tracks this host's height. */
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  flex: none;
  z-index: 2;
  background: var(--vk-reader-surface);
}


.content-overlay-actions {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 6px;
  opacity: 1;
  pointer-events: auto;
  transition: opacity 0.14s ease;
}

@media (hover: hover) and (pointer: fine) {
  .content-media-frame .content-overlay-actions {
    opacity: 0;
    pointer-events: none;
  }

  .content-media-frame:hover .content-overlay-actions {
    opacity: 1;
    pointer-events: auto;
  }

  /* Remote original-page previews are sibling Electron webviews, so they do
     not participate in the media frame's hover tree.  Keep their controls on
     the exact same hover contract instead of pinning a second toolbar. */
  .content-workspace:has(.article-remote-page:not(.is-hidden):hover) .content-overlay-actions,
  .content-overlay-actions:hover {
    opacity: 1;
    pointer-events: auto;
  }

  .content-media-frame :deep(.preview-find-trigger:not(.is-active)) {
    opacity: 0;
    pointer-events: none;
    transform: scale(.92);
  }

  .content-media-frame:hover :deep(.preview-find-trigger:not(.is-active)),
  .content-workspace:has(.article-remote-page:not(.is-hidden):hover) :deep(.preview-find-trigger:not(.is-active)),
  .content-media-frame :deep(.preview-find-anchor:focus-within .preview-find-trigger:not(.is-active)) {
    opacity: 1;
    pointer-events: auto;
    transform: none;
  }

  .content-overlay-actions:focus-within {
    opacity: 1;
    pointer-events: auto;
  }
}

.content-overlay-secondary-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.content-overlay-secondary-action.is-suppressed,
.content-overlay-secondary-actions.is-suppressed {
  display: none;
}

.report-markdown :deep(mark.preview-find-highlight),
.article-preview-body :deep(mark.preview-find-highlight),
.transcript-timeline :deep(mark.preview-find-highlight) {
  padding: 0 1px;
  border-radius: 2px;
  background: var(--vk-highlight-surface);
  color: inherit;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

.report-markdown :deep(mark.preview-find-highlight.preview-find-active),
.article-preview-body :deep(mark.preview-find-highlight.preview-find-active),
.transcript-timeline :deep(mark.preview-find-highlight.preview-find-active) {
  background: color-mix(in srgb, var(--vk-accent) 54%, var(--vk-bg-panel));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--vk-accent-strong) 50%, transparent);
}

:global(.content-action-popover) {
  z-index: 3000 !important;
  padding: 7px !important;
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, var(--vk-bg-panel)) !important;
  border-radius: 10px !important;
  /* A small action menu needs a denser material than the larger preview chrome:
     its text must stay legible when it overlaps a dense article or report. */
  background: var(--vk-surface-raised) !important;
  background:
    linear-gradient(
      145deg,
      color-mix(in srgb, var(--vk-bg-panel) 88%, var(--vk-bg-center)) 0%,
      color-mix(in srgb, var(--vk-bg-panel) 94%, transparent) 100%
    ) !important;
  box-shadow:
    0 18px 40px color-mix(in srgb, var(--vk-text) 18%, transparent),
    0 3px 9px color-mix(in srgb, var(--vk-text) 8%, transparent),
    inset 0 1px 0 color-mix(in srgb, var(--vk-bg-panel) 68%, transparent) !important;
  backdrop-filter: blur(28px) saturate(150%) brightness(1.04);
  -webkit-backdrop-filter: blur(28px) saturate(150%) brightness(1.04);
  transform-origin: right top;
}

:global(.content-action-pop-enter-active) {
  transition:
    opacity 150ms var(--vk-ease-out),
    scale 150ms var(--vk-ease-out);
}

:global(.content-action-pop-leave-active) {
  transition:
    opacity 100ms var(--vk-ease-out),
    scale 100ms var(--vk-ease-out);
}

:global(.content-action-pop-enter-from) {
  opacity: 0;
  scale: 0.96;
}

:global(.content-action-pop-leave-to) {
  opacity: 0;
  scale: 0.98;
}

:global(.content-action-popover .el-popper__arrow::before) {
  background: color-mix(in srgb, var(--vk-bg-panel) 74%, transparent) !important;
}

.content-action-menu-heading {
  padding: 3px 7px 5px;
  color: var(--vk-muted);
  font-size: 11px;
}

.content-action-menu > button {
  width: 100%;
  padding: 7px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.content-action-menu > button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--vk-accent) 10%, transparent);
  color: var(--vk-accent-strong);
}

.content-action-menu > button.is-danger {
  margin-top: 5px;
  color: var(--vk-danger);
}

.content-action-menu > button.is-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--vk-danger) 10%, transparent);
  color: var(--vk-danger);
}

.content-action-menu > button:disabled {
  color: var(--vk-muted);
  cursor: default;
}

.content-action-menu-details {
  display: grid;
  gap: 5px;
  margin-top: 6px;
  padding: 9px 7px 3px;
  border-top: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
}

.content-action-menu-details > div {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
  font-size: 11px;
}

.content-action-menu-details span {
  color: var(--vk-muted);
  line-height: 1.45;
}

.content-action-menu-details strong {
  color: var(--vk-text);
  font-weight: 500;
  text-align: right;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.content-action-menu-details > div.is-url,
.content-action-menu-details > div.is-path {
  margin-top: 2px;
}

.content-action-menu-details > div.is-url strong,
.content-action-menu-details > div.is-path .content-detail-path {
  color: var(--vk-muted);
  font-size: 10px;
}

.content-detail-path {
  min-width: 0;
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
  font: inherit;
  line-height: 1.45;
  text-align: right;
  text-decoration: underline;
  text-decoration-color: transparent;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content-detail-path:hover {
  color: var(--vk-text);
  text-decoration-color: currentColor;
}

.transcript-timeline {
  min-height: 0;
  height: 100%;
  max-height: none;
  position: relative;
  display: grid;
  align-content: start;
  overflow-y: auto;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
  scroll-behavior: smooth;
  scrollbar-gutter: stable;
}

.transcript-follow-button {
  position: sticky;
  top: 8px;
  z-index: 2;
  justify-self: end;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  margin: 8px 8px -36px 0;
  border: 1px solid color-mix(in srgb, var(--vk-accent) 22%, transparent);
  border-radius: 5px;
  background: color-mix(in srgb, var(--vk-surface-raised) 82%, transparent);
  color: var(--vk-accent-strong);
  box-shadow: 0 6px 18px color-mix(in srgb, var(--vk-text) 8%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease,
    transform var(--vk-motion-standard) var(--vk-ease-out);
}

@media (hover: hover) and (pointer: fine) {
  .transcript-follow-button:hover {
    border-color: color-mix(in srgb, var(--vk-accent) 42%, transparent);
    background: color-mix(in srgb, var(--vk-surface-raised) 96%, transparent);
    transform: translateY(-1px);
  }
}

.timeline-segment {
  width: 100%;
  min-width: 0;
  position: relative;
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  gap: 8px;
  padding: 7px 10px;
  border: 0;
  border-left: 3px solid transparent;
  border-bottom: 1px solid var(--vk-border);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--vk-motion-standard) ease,
    border-left-color var(--vk-motion-standard) ease,
    color var(--vk-motion-standard) ease,
    box-shadow var(--vk-motion-standard) ease;
}

.timeline-segment:hover {
  background: var(--vk-bg-hover);
}

.timeline-segment.is-active {
  border-left-color: var(--vk-accent-strong);
  background: color-mix(in srgb, var(--vk-accent) 13%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--vk-accent) 10%, transparent);
}

.timeline-segment.approximate .timeline-time {
  color: var(--vk-muted);
}

.timeline-segment.is-active .timeline-time {
  color: var(--vk-accent-strong);
}

.timeline-segment.is-active .timeline-text {
  color: var(--vk-text);
}

.timeline-time {
  color: var(--vk-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.timeline-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1.45;
}

.content-fact-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.content-fact-button {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 76%, transparent);
  color: var(--vk-muted);
  cursor: pointer;
  transition:
    transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color var(--vk-motion-standard) ease,
    color var(--vk-motion-standard) ease,
    box-shadow var(--vk-motion-standard) ease;
}

.content-fact-button:hover:not(:disabled),
.content-fact-button:focus-visible {
  outline: 0;
  background: var(--vk-bg-panel);
  color: var(--vk-accent-strong);
  transform: scale(1.02);
  box-shadow:
    0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent),
    0 2px 4px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.content-fact-button:focus-visible {
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--vk-accent) 22%, transparent),
    0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent),
    0 2px 4px color-mix(in srgb, var(--vk-text) 5%, transparent);
}

.content-fact-button :deep(.el-icon),
.content-fact-button :deep(.svg-mask-icon) {
  font-size: 15px;
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), filter var(--vk-motion-standard) ease;
}

.content-fact-button:hover:not(:disabled) :deep(.el-icon),
.content-fact-button:hover:not(:disabled) :deep(.svg-mask-icon),
.content-fact-button:focus-visible :deep(.el-icon),
.content-fact-button:focus-visible :deep(.svg-mask-icon) {
  transform: scale(1.15);
  filter: drop-shadow(0 2px 4px color-mix(in srgb, var(--vk-accent-strong) 28%, transparent));
}

.content-fact-button:disabled {
  opacity: 0.35;
  cursor: default;
}

.media-stage {
  display: block;
  margin: 0;
}

.media-placeholder {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 10px;
  color: var(--vk-muted);
}

.media-placeholder span {
  max-width: 280px;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
}

.empty-frame {
  flex: 1 1 auto;
  max-height: none;
  aspect-ratio: auto;
}

.workspace-empty-state {
  gap: var(--vk-space-cluster);
  color: color-mix(in srgb, var(--vk-muted) 84%, var(--vk-accent-strong));
}

.workspace-empty-state span {
  max-width: 320px;
  color: var(--vk-muted);
  font-size: var(--vk-type-body-size);
  line-height: var(--vk-leading-body);
}

.tool-panel {
  padding: 12px;
  border: 0;
  border-bottom: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
  box-shadow: none;
}

.panel-title {
  margin-bottom: 14px;
}

.panel-title.inline,
.editor-titlebar,
.editor-row-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.panel-title h2 {
  margin: 4px 0 0;
  color: var(--vk-text);
  font-size: 14px;
  line-height: 1.22;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  color: var(--vk-muted);
  font-size: 12px;
  font-weight: 500;
}

.editor-surface {
  height: 100%;
  min-height: 100%;
  border: 0;
  border-radius: var(--vk-radius-surface);
  overflow: hidden;
  background: var(--vk-bg-center);
  color: var(--vk-text);
}

.prompt-editor-surface {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
}

.prompt-editor-breadcrumb {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--vk-space-xs);
  padding: 0 var(--vk-space-panel);
  overflow: hidden;
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  white-space: nowrap;
}

.prompt-editor-breadcrumb i {
  color: color-mix(in srgb, var(--vk-muted) 54%, transparent);
  font-style: normal;
}

.prompt-editor-breadcrumb strong {
  color: var(--vk-text);
  font-weight: 600;
}

.prompt-breadcrumb-leaf {
  min-width: 0;
  overflow: hidden;
  color: var(--vk-text);
  text-overflow: ellipsis;
}

.prompt-editor-breadcrumb small {
  flex: 0 0 auto;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
}

.editor-titlebar {
  min-height: 35px;
  align-items: center;
  padding: 4px 10px;
  border-bottom: 1px solid var(--vk-border);
  color: var(--vk-text);
  background: var(--vk-bg-hover);
  font-size: 12px;
  font-weight: 500;
}

.editor-titlebar-actions,
.editor-row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.editor-empty {
  min-height: 320px;
  display: grid;
  place-items: center;
  color: var(--vk-muted);
  font-size: 13px;
}

.editor-list {
  display: grid;
}

.editor-row {
  display: grid;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--vk-border);
}

.editor-row:hover {
  background: var(--vk-bg-hover);
}

.editor-row-head > div {
  min-width: 0;
}

.editor-row-head strong {
  display: block;
  color: var(--vk-text);
  font-size: 13px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.editor-row-head span {
  display: block;
  margin-top: 3px;
  color: var(--vk-muted);
  font-size: 12px;
  line-height: 1.35;
}

.prompt-editor-pane {
  position: relative;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: 216px minmax(0, 1fr);
  padding: 0;
}

.template-rail-collapsed .prompt-editor-pane {
  grid-template-columns: 42px minmax(0, 1fr);
}

.prompt-template-rail {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: 40px minmax(0, 1fr);
  overflow: hidden;
  border-right: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
}

.prompt-template-rail-header {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-xs);
  padding: 0 var(--vk-space-sm) 0 var(--vk-space-control);
  border-bottom: 1px solid var(--vk-border);
}

.template-rail-collapsed .prompt-template-rail-header {
  justify-content: center;
  padding: 0;
}

.prompt-template-rail-title,
.prompt-template-rail-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--vk-space-xs);
}

.prompt-template-rail-title strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: 600;
}

.prompt-template-rail-title small {
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
}

.prompt-rail-icon-button {
  width: var(--vk-control-height-compact);
  height: var(--vk-control-height-compact);
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
}

.prompt-rail-icon-button:hover {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.prompt-rail-icon-button:focus-visible,
.prompt-shortcut-item:focus-visible {
  outline: none;
  box-shadow: var(--vk-focus-ring);
}

.prompt-template-list {
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 2px;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--vk-space-sm) var(--vk-space-xs);
}

.prompt-shortcut-item {
  width: 100%;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-xs);
  padding: 0 var(--vk-space-sm);
  border: 0;
  border-radius: var(--vk-radius-compact);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.prompt-shortcut-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-template-current {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-accent) 14%, transparent);
  color: var(--vk-accent-strong);
  font-size: var(--vk-type-micro-size);
  font-weight: 600;
  line-height: 18px;
  padding: 0 var(--vk-space-xs);
}

.prompt-shortcut-item:hover,
.prompt-shortcut-item.active {
  background: var(--vk-selected-bg);
  color: var(--vk-selected-fg);
}

.report-prompt-blank {
  display: grid;
  grid-row: 1 / -1;
  min-height: 100%;
  place-items: center;
  padding: var(--vk-space-page);
  color: var(--vk-muted);
  font-size: var(--vk-type-body-size);
  text-align: center;
}

.prompt-editor-main {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.prompt-function-bar {
  min-width: 0;
  min-height: 42px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--vk-space-sm);
  padding: var(--vk-space-micro) var(--vk-space-control);
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
}

.prompt-usage {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--vk-space-micro) var(--vk-space-cluster);
  color: var(--vk-text);
  font-size: var(--vk-type-meta-size);
  line-height: 1.4;
}

.prompt-usage > strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: 600;
}

.prompt-usage span {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-micro);
}

.prompt-usage b {
  color: var(--vk-muted);
  font-weight: 500;
}

.prompt-usage code {
  color: var(--vk-accent-strong);
  font-family: var(--vk-font-mono);
  font-size: inherit;
}

.prompt-usage em {
  color: var(--vk-muted);
  font-style: normal;
}

.prompt-editor-header {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--vk-space-control);
  min-height: 56px;
  padding: var(--vk-space-sm) var(--vk-space-control);
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-center);
}

.prompt-editor-name-field {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(120px, 420px);
  align-items: center;
  gap: var(--vk-space-sm);
}

.prompt-editor-name-field > span {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-weight: 500;
}

.prompt-editor-static-name {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.prompt-editor-static-name strong {
  min-width: 0;
  overflow: hidden;
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-editor-static-name span {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.prompt-editor-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: var(--vk-space-xs);
  min-width: 0;
}

.prompt-editor-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.prompt-editor-name {
  width: 100%;
  min-width: 0;
}

.prompt-editor-name :deep(.el-input__wrapper) {
  min-height: var(--vk-control-height-default);
  border-radius: var(--vk-radius-control);
  background: var(--vk-bg-panel);
  box-shadow: 0 0 0 1px var(--vk-border) inset;
}

.prompt-editor-name :deep(.el-input__inner) {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: 600;
}

.prompt-editor-dirty {
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-micro);
  color: var(--vk-warning);
  font-size: var(--vk-type-meta-size);
  font-weight: 500;
  white-space: nowrap;
}

.prompt-editor-dirty::before {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  content: '';
}

.prompt-save-button {
  min-width: 58px;
}

.prompt-save-button:deep(.el-button),
.prompt-save-button,
.prompt-reset-button:deep(.el-button),
.prompt-reset-button {
  border-radius: var(--vk-radius-control);
}

.prompt-reset-button { min-width: 84px; }

.prompt-activate-button {
  border-radius: var(--vk-radius-control);
}

.prompt-editor-empty {
  grid-row: 1 / -1;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: var(--vk-space-sm);
  min-height: 0;
  padding: var(--vk-space-page);
  color: var(--vk-muted);
  text-align: center;
}

.prompt-editor-empty :deep(.svg-mask-icon) { color: var(--vk-accent-strong); opacity: 0.72; }
.prompt-editor-empty strong { color: var(--vk-text); font-size: var(--vk-type-body-size); font-weight: 600; }
.prompt-editor-empty span { font-size: var(--vk-type-label-size); }

.prompt-contract-strip {
  min-width: 0;
  min-height: 40px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--vk-space-xs) var(--vk-space-panel);
  padding: var(--vk-space-xs) var(--vk-space-panel);
  border-bottom: 1px solid var(--vk-border);
  background: var(--vk-bg-quiet);
  color: var(--vk-text);
  font-size: var(--vk-type-meta-size);
  line-height: 1.4;
}

.prompt-contract-strip span {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-micro);
}

.prompt-contract-strip b {
  color: var(--vk-muted);
  font-weight: 500;
}

.prompt-contract-strip code {
  color: var(--vk-accent-strong);
  font-family: var(--vk-font-mono);
  font-size: inherit;
}

.prompt-contract-strip em {
  color: var(--vk-muted);
  font-style: normal;
}

.prompt-editor-text {
  min-height: 0;
  height: 100%;
}

.prompt-editor-text :deep(.el-textarea__inner) {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  border-color: var(--vk-border);
  border-radius: var(--vk-radius-surface);
  border-width: 0;
  background: var(--vk-bg-panel);
  color: var(--vk-text);
  font-family: var(--vk-font-mono);
  font-size: var(--vk-type-body-size);
  line-height: 1.7;
  padding: var(--vk-space-panel) var(--vk-space-page) var(--vk-space-section);
  box-shadow: none;
}


@media (prefers-reduced-motion: reduce) {
  .media-transcript-splitter::before,
  .transcript-follow-button,
  .timeline-segment,
  .content-overlay-actions,
  .content-fact-button,
  .content-fact-button :deep(.el-icon),
  .content-fact-button :deep(.svg-mask-icon) {
    transition: none;
  }

  .transcript-follow-button,
  .content-fact-button:hover:not(:disabled),
  .content-fact-button:focus-visible,
  .content-fact-button:hover:not(:disabled) :deep(.el-icon),
  .content-fact-button:hover:not(:disabled) :deep(.svg-mask-icon),
  .content-fact-button:focus-visible :deep(.el-icon),
  .content-fact-button:focus-visible :deep(.svg-mask-icon) {
    transform: none;
  }

  .campus-article-loading span {
    animation: none;
    opacity: 0.72;
  }

  :global(.content-action-pop-enter-active),
  :global(.content-action-pop-leave-active) {
    transition: opacity var(--vk-motion-fast) ease;
  }

  :global(.content-action-pop-enter-from),
  :global(.content-action-pop-leave-to) {
    scale: 1;
  }

  .reader-selection-ask {
    transition: border-color 100ms ease, background-color 100ms ease, box-shadow 100ms ease;
  }

  .reader-selection-action-enter-active,
  .reader-selection-action-leave-active {
    transition: opacity 100ms ease;
    animation: none;
  }

  .reader-selection-action-leave-to,
  .reader-selection-ask:active {
    transform: none;
  }

  .reader-selection-action-enter-from {
    opacity: 0;
    transform: none;
  }

  .report-footnote-return-enter-active,
  .report-footnote-return-leave-active {
    transition: opacity 120ms ease;
  }

  .report-footnote-return-enter-from,
  .report-footnote-return-leave-to {
    transform: none;
  }
}

@media (prefers-reduced-transparency: reduce) {
  :global(.content-action-popover),
  .report-footnote-return,
  .transcript-follow-button,
  .reader-selection-ask {
    background: var(--vk-bg-panel) !important;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
  :global(.content-action-popover),
  .report-footnote-return,
  .transcript-follow-button,
  .reader-selection-ask {
    border-color: color-mix(in srgb, var(--vk-text) 48%, var(--vk-border)) !important;
    background: var(--vk-bg-panel) !important;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (max-width: 900px) {
  .main-canvas {
    width: 100%;
  }

  .content-media-frame,
  .media-frame {
    min-height: 210px;
  }
}

@media (max-width: 620px) {
  .main-canvas {
    grid-column: 1;
  }

}
</style>
