<template>
  <section class="main-canvas">
    <div
      v-if="activeView === 'library'"
      class="workbench-editor-host"
    >
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
                'media-transcript-layout': hasMediaTranscriptWorkspace(activeContentTab.id),
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
                    <ReportCoverPreview
                      v-if="isReportTab(activeContentTab.id)"
                      :content-item-id="String(contentForTab(activeContentTab.id)?.id || '')"
                      :title="reportDisplayTitle(activeContentTab.id)"
                      :cover-url="contentForTab(activeContentTab.id)?.cover_url || ''"
                      :history="reportCoverHistoryForTab(activeContentTab.id)"
                      :generating="isWechatCoverGenerating(activeContentTab.id)"
                      :switching="isWechatCoverSwitching(activeContentTab.id)"
                      @select="$emit('select-wechat-cover', $event)"
                    />
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
                  :aria-busy="shouldShowXhsImageCapturePreview(activeContentTab.id)"
                  aria-label="小红书图文图片"
                >
                  <div v-if="shouldShowXhsImageCapturePreview(activeContentTab.id)" class="xhs-capture-image-loading" role="status">
                    <div class="xhs-capture-image-stream" aria-hidden="true">
                      <span class="xhs-capture-image-sheet is-back"></span>
                      <span class="xhs-capture-image-sheet is-middle"></span>
                      <span class="xhs-capture-image-sheet is-front"></span>
                    </div>
                    <div class="xhs-capture-loading-copy">
                      <span class="xhs-capture-loading-pulse" aria-hidden="true"></span>
                      <div>
                        <strong>正在获取笔记图片</strong>
                        <small>图片到达后会立即显示</small>
                      </div>
                    </div>
                  </div>
                  <template v-else>
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
                    class="media-preview-loader"
                    role="status"
                    aria-live="polite"
                    aria-label="正在加载视频预览"
                  >
                    <span class="media-preview-spinner" aria-hidden="true"></span>
                  </div>
                </template>
                <div
                  v-else-if="contentForTab(activeContentTab.id)?.status === 'processing' && ['video', 'audio'].includes(contentForTab(activeContentTab.id)?.content_type)"
                  class="media-preview-loader is-empty"
                  role="status"
                  aria-live="polite"
                  aria-label="正在加载媒体预览"
                >
                  <span class="media-preview-spinner" aria-hidden="true"></span>
                </div>
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
                    :search-label="isWechatArticleTab(activeContentTab.id) ? '在原文中查找' : '在预览中查找'"
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
                  <ContentActionMenu
                    :model="activeContentActionMenuModel"
                    @select="handleContentActionMenuSelect"
                  >
                    <template #reference>
                      <button class="content-fact-button" type="button" aria-label="内容操作">
                        <SvgMaskIcon :src="ellipsisIcon" :size="15" />
                      </button>
                    </template>
                  </ContentActionMenu>
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
                    <AiSkeletonStream
                      v-if="shouldShowXhsTextCapturePreview(activeContentTab.id)"
                      class="xhs-capture-text-loading"
                      label="正在读取作者文字"
                      aria-label="小红书作者文字正在读取"
                    />
                    <template v-else>
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
                    </template>
                  </div>
                </section>
              <div
                v-if="hasMediaTranscriptWorkspace(activeContentTab.id)"
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
                v-if="hasMediaTranscriptWorkspace(activeContentTab.id)"
                class="transcript-timeline"
                :class="{ 'is-generating': shouldShowTranscriptGeneration(activeContentTab.id) }"
                :aria-busy="shouldShowTranscriptGeneration(activeContentTab.id)"
                @wheel.passive="pauseTranscriptAutoFollow"
                @touchstart.passive="pauseTranscriptAutoFollow"
              >
                <div
                  v-if="shouldShowTranscriptGeneration(activeContentTab.id)"
                  class="transcript-generation"
                  role="status"
                  aria-live="polite"
                >
                  <div class="transcript-generation-heading">
                    <span class="transcript-generation-pulse" aria-hidden="true"></span>
                    <div>
                      <strong>{{ transcriptGenerationLabel(activeContentTab.id) }}</strong>
                      <small>{{ transcriptGenerationDescription(activeContentTab.id) }}</small>
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
                </template>
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

  <PromptEditorSurface
    v-else-if="activeView === 'prompts'"
    :prompt-workspace-tabs="promptWorkspaceTabs"
    :active-prompt-tab-id="activePromptTabId"
    :prompt-task-type="promptTaskType"
    :prompt-templates="promptTemplates"
    :selected-prompt-template-id="selectedPromptTemplateId"
    :loading-prompts="loadingPrompts"
    :prompt-editor-text="promptEditorText"
    :prompt-editor-name="promptEditorName"
    :saving-prompt-template="savingPromptTemplate"
    :activating-prompt-template="activatingPromptTemplate"
    :wechat-report-prompts="wechatReportPrompts"
    :selected-wechat-report-prompt-group-id="selectedWechatReportPromptGroupId"
    :selected-wechat-report-prompt-type="selectedWechatReportPromptType"
    :wechat-report-prompt-text="wechatReportPromptText"
    :loading-wechat-report-prompts="loadingWechatReportPrompts"
    :saving-wechat-report-prompt="savingWechatReportPrompt"
    @update:prompt-editor-text="$emit('update:promptEditorText', $event)"
    @update:wechat-report-prompt-text="$emit('update:wechat-report-prompt-text', $event)"
    @activate-prompt-template="$emit('activate-prompt-template', $event)"
    @save-prompt="$emit('save-prompt')"
    @save-wechat-report-prompt="$emit('save-wechat-report-prompt')"
    @reset-prompt="$emit('reset-prompt')"
  />

  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import katex from 'katex'
import {
  Aim,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
} from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import AiSkeletonStream from '../components/AiSkeletonStream.vue'
import { useMarkdownFootnoteNavigation } from '../composables/useMarkdownFootnoteNavigation'
const movieClapperIcon = 'movieclapper'
const questionPageIcon = 'questionmark.text.page'
const playFillIcon = 'play.fill'
const pauseFillIcon = 'pause.fill'
const ellipsisIcon = 'ellipsis'
import { remainingReadingMinutes } from './readingProgress.js'
import { shouldShowArticlePreviewLoader } from '../features/library/articlePreviewLoadState.js'
import PreviewFindBar from './PreviewFindBar.vue'
import PromptEditorSurface from './PromptEditorSurface.vue'
import ReadingProgressControl from './ReadingProgressControl.vue'
import ReportCoverPreview from './ReportCoverPreview.vue'
import ReportOutlineRail from './ReportOutlineRail.vue'
import { usePreviewFindController } from './usePreviewFindController.js'
import { useMediaTranscriptWorkspaceController } from './useMediaTranscriptWorkspaceController.js'
import { useXhsGalleryController } from './useXhsGalleryController.js'
import { useReadingProgressController } from './useReadingProgressController.js'
import { useReaderSelectionController } from './useReaderSelectionController.js'
import { useRemoteArticlePreviewController } from './useRemoteArticlePreviewController.js'
import { useEditorContentActionMenuController } from './useEditorContentActionMenuController.js'
import { articleOutlineHeadingSelector, createArticleOutlineModel } from './articleOutlineModel.js'
import { createEditorContentKind } from './editorContentKind.js'
import { formatTimelineTime } from './mediaTranscriptModel.js'
import {
  readerMetadataText,
} from './editorReaderMetadata.js'
import { createEditorReportPresentation } from './editorReportPresentation.js'

const ArtVideoPlayer = defineAsyncComponent(() => import('./ArtVideoPlayer.vue'))
const ArtAudioPlayer = defineAsyncComponent(() => import('./ArtAudioPlayer.vue'))
const ContentActionMenu = defineAsyncComponent(() => import('./ContentActionMenu.vue'))
const props = defineProps({
  activeView: { type: String, required: true },
  workspaceTabs: { type: Array, default: () => [] },
  activeWorkspaceTab: { type: Object, default: null },
  promptWorkspaceTabs: { type: Array, default: () => [] },
  activePromptTabId: { type: String, default: '' },
  selectedContentItem: { type: Object, default: null },
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
  formatBytes: { type: Function, required: true },
  retryingContentId: { type: String, default: null },
  wechatPublishingConfigured: { type: Boolean, default: false },
  wechatCoverGeneratingContentIds: { type: Array, default: () => [] },
  wechatCoverSwitchingContentIds: { type: Array, default: () => [] },
  wechatCoverHistoryForContent: { type: Function, required: true },
})

const emit = defineEmits([
  'update:promptEditorText',
  'activate-prompt-template',
  'save-prompt',
  'reset-prompt',
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
  'ask-about-selection',
  'generate-wechat-cover',
  'regenerate-wechat-cover',
  'replan-wechat-cover',
  'select-wechat-cover',
  'create-wechat-draft',
  'delete-content',
])

const activePlayer = ref(null)
const contentHero = ref(null)
const reportReader = ref(null)
const reportMarkdown = ref(null)
const activeArticlePreviewFrame = ref(null)
const articleOutlineRoot = ref(null)
let removeDesktopPreviewFindListener = null

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
const {
  articlePreviewHtml,
  hasRemoteSource,
  isArticleTab,
  isAudioTab,
  isExternalImageTab,
  isExternalMarkdownTab,
  isExternalPdfTab,
  isLocalHtmlArticleTab,
  isMiniProgramCaptureTab,
  isReportTab,
  isTimedMediaTab,
  isVideoTab,
  readerKindForTab,
  sourceUrlForTab,
} = createEditorContentKind({
  contentForTab: props.contentForTab,
  articlePreviewForTab: props.articlePreviewForTab,
})
const {
  reportDateLabel,
  reportDisplayTitle,
  reportGeneratedLabel,
} = createEditorReportPresentation({
  contentForTab: props.contentForTab,
  workspaceTabById: props.workspaceTabById,
})
const {
  articleOutlineHeadingLevel,
  isArticleOutlineHeading,
} = createArticleOutlineModel({
  activeArticleTitle: () => props.contentForTab(activeContentTab.value?.id)?.title,
})

const {
  xhsGalleryTrack,
  xhsGalleryIndex,
  xhsGalleryImageCount,
  canNavigateXhsGallery,
  scrollXhsGallery,
  syncXhsGalleryPosition,
  handleXhsGalleryKeydown,
  resetXhsGallery,
} = useXhsGalleryController({
  activeContentTab,
  articlePreviewForTab: props.articlePreviewForTab,
})

const {
  dispose: disposeMediaTranscriptWorkspace,
  handleAudioPlaybackChange,
  handleMediaTranscriptKeydown,
  handlePlayerTimeUpdate,
  handleTimelineSegmentClick,
  handleXhsImageTextKeydown,
  hasMediaTranscriptWorkspace,
  hasTranscriptTimeline,
  isAudioPlaying,
  isTimelineSegmentActive,
  mediaTranscriptHeight,
  mediaTranscriptResizing,
  mount: mountMediaTranscriptWorkspace,
  pauseTranscriptAutoFollow,
  resetActiveMediaState,
  resumeTranscriptAutoFollow,
  seekToTimestamp,
  setTimelineSegmentRef,
  shouldShowTranscriptGeneration,
  startMediaTranscriptResize,
  startXhsImageTextResize,
  timelineSegmentsForTab,
  transcriptAutoFollow,
  transcriptGenerationDescription,
  transcriptGenerationLabel,
  verticalContentBounds,
  xhsImageTextHeight,
  xhsImageTextResizing,
  toggleActiveAudioPlayback,
} = useMediaTranscriptWorkspaceController({
  contentHero,
  activeContentTab,
  activePlayer,
  contentForTab: props.contentForTab,
  isAudioTab,
  isArticleTab,
  isTimedMediaTab,
  resultForTab: props.resultForTab,
  transcriptForTab: props.transcriptForTab,
})

const remotePreviewCallbacks = {
  clearSelectedTextAction: () => {},
  handleSelection: () => {},
  isFindOpen: () => false,
  getFindQuery: () => '',
  setFindResult: () => {},
  resetFindResult: () => {},
  scheduleFindRefresh: () => {},
}
const {
  activeLocalHtmlRemotePage,
  activeLocalHtmlRemoteWebview,
  activeRemoteOutline,
  activeRemoteOutlineKey,
  activeRemoteOutlineVersion,
  activeRemoteOutlineWebview,
  activeRemoteReadingProgress,
  activeWechatContent,
  activeWechatRemotePage,
  canOpenWechatRemotePage,
  clearRemotePreviewFind,
  disposeRemoteArticlePreviewController,
  handleLocalHtmlRemoteConsoleMessage,
  handleLocalHtmlRemoteFoundInPage,
  handleLocalHtmlRemotePageFailed,
  handleLocalHtmlRemotePageLoaded,
  handleWechatRemoteConsoleMessage,
  handleWechatRemotePageFailed,
  handleWechatRemotePageLoaded,
  isLocalHtmlRemoteVisible,
  isWechatRemotePageVisible,
  isWechatRemoteVisible,
  navigateRemotePreviewFind,
  openedWechatRemotePages,
  previewFindMode,
  refreshRemotePreviewFind,
  scrollToRemoteOutlineEntry,
  setWechatRemoteWebview,
  toggleWechatRemotePage,
  wechatRemoteActionLabel,
  wechatRemoteWebviews,
} = useRemoteArticlePreviewController({
  activeContentTab,
  workspaceTabs: () => props.workspaceTabs,
  contentForTab: props.contentForTab,
  isWechatArticleTab,
  localHtmlOriginalPageUrl,
  readerTextForMetadata,
  clearSelectedTextAction: () => remotePreviewCallbacks.clearSelectedTextAction(),
  handleWechatRemoteSelection: (payload) => remotePreviewCallbacks.handleSelection(payload),
  onPreviewFindResult: (result) => remotePreviewCallbacks.setFindResult(result),
  resetPreviewFindResult: () => remotePreviewCallbacks.resetFindResult(),
  onPreviewFindRefresh: () => remotePreviewCallbacks.scheduleFindRefresh(),
  isPreviewFindOpen: () => remotePreviewCallbacks.isFindOpen(),
  getPreviewFindQuery: () => remotePreviewCallbacks.getFindQuery(),
})
const {
  selectedTextAction,
  selectedTextActionStyle,
  askAboutSelectedText,
  attachArticlePreviewSelectionFrame,
  clearSelectedTextAction,
  disposeReaderSelectionController,
  handleWechatRemoteSelection: handleWechatRemoteSelectionFromReader,
  mountReaderSelectionController,
} = useReaderSelectionController({
  activeContentTab,
  activeArticlePreviewFrame,
  contentHero,
  contentForTab: props.contentForTab,
  isWechatRemoteVisible: () => isWechatRemoteVisible.value,
  wechatRemoteWebviews,
  onAsk: (selection) => emit('ask-about-selection', selection),
})
remotePreviewCallbacks.clearSelectedTextAction = clearSelectedTextAction
remotePreviewCallbacks.handleSelection = handleWechatRemoteSelectionFromReader
const {
  clearPreviewFindHighlights,
  closePreviewFind,
  disposePreviewFindController,
  navigatePreviewFind,
  openPreviewFind,
  previewFindActiveIndex,
  previewFindFocusRequest,
  previewFindMatchCount,
  previewFindOpen,
  previewFindQuery,
  previewFindTruncated,
  schedulePreviewFindRefresh,
  setRemoteFindResult,
  updatePreviewFindQuery,
} = usePreviewFindController({
  hasActiveContent: () => Boolean(activeContentTab.value),
  getMode: previewFindMode,
  getLocalRoot: previewFindRoot,
  getFocusFallback: () => contentHero.value,
  onLocalMatchActivated: seekMediaToPreviewFindMatch,
  refreshRemote: refreshRemotePreviewFind,
  navigateRemote: navigateRemotePreviewFind,
  clearRemote: clearRemotePreviewFind,
})
remotePreviewCallbacks.isFindOpen = () => previewFindOpen.value
remotePreviewCallbacks.getFindQuery = () => previewFindQuery.value
remotePreviewCallbacks.setFindResult = setRemoteFindResult
remotePreviewCallbacks.resetFindResult = () => {
  previewFindMatchCount.value = 0
  previewFindActiveIndex.value = -1
  previewFindTruncated.value = false
}
remotePreviewCallbacks.scheduleFindRefresh = schedulePreviewFindRefresh
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
const {
  readingProgress,
  readingCharacterCount,
  handleReadingScroll,
  attachReadingProgressFrame,
  scheduleReadingProgressRefresh,
  resetReadingProgress,
  disposeReadingProgressController,
} = useReadingProgressController({
  activeContentTab,
  activeArticlePreviewFrame,
  reportReader,
  isArticleTab,
  supportsReadingProgress,
  isRemoteReadingVisible: () => isWechatRemoteVisible.value || isLocalHtmlRemoteVisible.value,
  readerTextForMetadata,
})
watch(
  () => activeContentTab.value?.id || '',
  () => {
    resetActiveMediaState()
    clearSelectedTextAction()
    resetReadingProgress()
    scheduleReadingProgressRefresh()
  }
)

watch(
  () => [isWechatRemoteVisible.value, isLocalHtmlRemoteVisible.value],
  () => scheduleReadingProgressRefresh(),
  { flush: 'post' }
)

watch(() => activeContentTab.value?.id, () => {
  clearFootnoteReturn()
  resetXhsGallery()
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
  disposeMediaTranscriptWorkspace()
  disposeRemoteArticlePreviewController()
  disposePreviewFindController()
  disposeReadingProgressController()
  disposeReaderSelectionController()
  window.removeEventListener('keydown', handlePreviewFindShortcut, true)
  removeDesktopPreviewFindListener?.()
  removeDesktopPreviewFindListener = null
})

onMounted(() => {
  mountMediaTranscriptWorkspace()
  window.addEventListener('keydown', handlePreviewFindShortcut, true)
  mountReaderSelectionController()
  removeDesktopPreviewFindListener = window.knowledgeHubDesktop?.onPreviewFind?.(handleDesktopPreviewFindShortcut) || null
  scheduleReadingProgressRefresh()
})

const {
  activeContentActionMenuModel,
  handleContentActionMenuSelect,
} = useEditorContentActionMenuController({
  props,
  activeContentTab,
  canOpenRemotePage: canOpenWechatRemotePage,
  activeRemotePage: activeWechatRemotePage,
  remoteActionLabel: wechatRemoteActionLabel,
  sourceUrlForTab,
  readerTextForMetadata,
  hasRemoteSource,
  isTimedMediaTab,
  isArticleTab,
  isAudioTab,
  isReportTab,
  timelineSegmentsForTab,
  isCoverGenerating: isWechatCoverGenerating,
  isCoverSwitching: isWechatCoverSwitching,
  toggleRemotePage: toggleWechatRemotePage,
  requestCover: requestWechatCoverGeneration,
  emit,
})

function localHtmlOriginalPageUrl(tabId) {
  if (!isLocalHtmlArticleTab(tabId)) return ''
  const sourceUrl = String(props.contentForTab(tabId)?.source_metadata?.original_source_url || '').trim()
  return /^https:\/\//iu.test(sourceUrl) ? sourceUrl : ''
}

function isXiaohongshuArticleTab(tabId) {
  const content = props.contentForTab(tabId)
  return content?.source_provider === 'xiaohongshu' && content?.content_type === 'article'
}

function hasXhsImageTextLayout(tabId) {
  return hasXhsGallery(tabId) || shouldShowXhsCapturePreview(tabId)
}

function hasXhsGallery(tabId) {
  return isXiaohongshuArticleTab(tabId) && Boolean(props.articlePreviewForTab(tabId)?.gallery?.length)
}

function shouldShowXhsCapturePreview(tabId) {
  if (!isXiaohongshuArticleTab(tabId) || hasXhsGallery(tabId)) return false
  const content = props.contentForTab(tabId)
  const preview = props.articlePreviewForTab(tabId)
  const task = props.resultForTab(tabId)
  // A capture can materialise either source independently. Keep the dedicated
  // image/text workspace visible while the durable task or its local preview
  // request is active; a terminal failure still returns the normal article
  // error instead of an indefinitely animated placeholder.
  return content?.status === 'processing'
    || ['queued', 'running', 'processing'].includes(task?.status)
    || ['queued', 'running'].includes(preview?.formatting_status)
    || Boolean(preview?.loading)
}

function shouldShowXhsImageCapturePreview(tabId) {
  return shouldShowXhsCapturePreview(tabId) && !hasXhsGallery(tabId)
}

function shouldShowXhsTextCapturePreview(tabId) {
  if (!isXiaohongshuArticleTab(tabId) || String(props.articlePreviewForTab(tabId)?.html || '').trim()) return false
  const content = props.contentForTab(tabId)
  const preview = props.articlePreviewForTab(tabId)
  const task = props.resultForTab(tabId)
  return content?.status === 'processing'
    || ['queued', 'running', 'processing'].includes(task?.status)
    || ['queued', 'running'].includes(preview?.formatting_status)
    || Boolean(preview?.loading)
}

function contentHeroLayoutStyle(tabId) {
  if (hasMediaTranscriptWorkspace(tabId)) return { '--media-height': `${mediaTranscriptHeight.value}%` }
  if (hasXhsImageTextLayout(tabId)) return { '--xhs-image-height': `${xhsImageTextHeight.value}%` }
  return null
}

function isCampusArticleTab(tabId) {
  return props.contentForTab(tabId)?.source_provider === 'campus'
}

function isWechatArticleTab(tabId) {
  return props.contentForTab(tabId)?.source_provider === 'wechat'
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

function requestWechatCoverGeneration(tabId) {
  const content = props.contentForTab(tabId)
  if (!content) return
  emit(content.cover_url ? 'regenerate-wechat-cover' : 'generate-wechat-cover', content)
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

function seekMediaToPreviewFindMatch(match) {
  const tab = activeContentTab.value
  if (!tab || !hasTranscriptTimeline(tab.id)) return
  const startSeconds = Number(match.closest('.timeline-segment')?.dataset.startSeconds)
  if (!Number.isFinite(startSeconds)) return
  handleTimelineSegmentClick(tab.id, startSeconds)
}

function handleArticlePreviewFrameReady(event) {
  const frameDocument = event?.target?.contentDocument
  if (!frameDocument) return
  attachReadingProgressFrame(frameDocument)
  attachArticlePreviewSelectionFrame(frameDocument)
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
  return readerMetadataText({
    content,
    kind: readerKindForTab(tabId),
    timelineSegments: timelineSegmentsForTab(tabId),
    transcript: props.transcriptForTab(tabId),
    selectedMarkdownPreview: props.selectedMarkdownPreview,
    articlePreviewText: activeArticlePreviewFrame.value?.contentDocument?.body?.innerText || '',
    captureText: reportMarkdown.value?.innerText || '',
    htmlToText: plainTextFromHtml,
  })
}

function plainTextFromHtml(html) {
  if (!html) return ''
  const template = document.createElement('template')
  template.innerHTML = html
  return template.content.textContent || ''
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

</script>

<style scoped src="./editor-host-workspace.css"></style>
<style scoped src="./editor-host-documents.css"></style>
<style scoped src="./editor-host-articles.css"></style>
<style scoped src="./editor-host-transcript.css"></style>
