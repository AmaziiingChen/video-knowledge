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
import {
  readableCharacterCount,
  reportBodyHtmlForCharacterCount,
} from '../utils/reportReadingStats'
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
import { createContentActionMenuModel } from './contentActionMenuModel.js'
import { dispatchEditorContentAction } from './editorContentActions.js'
import { createEditorContentKind } from './editorContentKind.js'
import { formatTimelineTime } from './mediaTranscriptModel.js'

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
  running: { type: Boolean, default: false },
  result: { type: Object, required: true },
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
  isLocalHtmlArticleTab,
  isReportTab,
  isTimedMediaTab,
  isVideoTab,
  sourceUrlForTab,
} = createEditorContentKind({
  contentForTab: props.contentForTab,
  articlePreviewForTab: props.articlePreviewForTab,
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

const activeContentActionMenuModel = computed(() => {
  const tabId = activeContentTab.value?.id || ''
  const content = tabId ? props.contentForTab(tabId) : null
  const textReadiness = tabId ? textReadinessForTab(tabId) : null
  return createContentActionMenuModel({
    content,
    retryingContentId: props.retryingContentId,
    hasRemoteSource: tabId ? hasRemoteSource(tabId) : false,
    remotePageAvailable: canOpenWechatRemotePage.value,
    remotePageLoading: activeWechatRemotePage.value?.status === 'loading',
    remotePageLabel: wechatRemoteActionLabel.value,
    articleTextRetryable: Boolean(tabId && isArticleTab(tabId) && textReadiness?.retryable),
    articleTextStatus: textReadiness?.status,
    canReprocessLocalSource: tabId ? canReprocessLocalSource(tabId) : false,
    localReprocessLabel: tabId ? localReprocessLabel(tabId) : '',
    canRetranscribeMedia: tabId ? canRetranscribeMedia(tabId) : false,
    isAudio: tabId ? isAudioTab(tabId) : false,
    canFetchExternalSubtitle: tabId ? canFetchExternalSubtitle(tabId) : false,
    canRefreshSourceContext: tabId ? canRefreshSourceContext(tabId) : false,
    canDownloadVideo: tabId ? canDownloadVideo(tabId) : false,
    videoCacheExpired: tabId ? isVideoCacheExpired(tabId) : false,
    isTimedMedia: tabId ? isTimedMediaTab(tabId) : false,
    hasTimelineSegments: Boolean(tabId && timelineSegmentsForTab(tabId).length),
    isReport: tabId ? isReportTab(tabId) : false,
    coverGenerating: tabId ? isWechatCoverGenerating(tabId) : false,
    coverSwitching: tabId ? isWechatCoverSwitching(tabId) : false,
    publishingConfigured: props.wechatPublishingConfigured,
    details: tabId ? contentDetailRows(tabId) : [],
  })
})

function handleContentActionMenuSelect({ id, payload } = {}) {
  const tabId = activeContentTab.value?.id || ''
  const content = tabId ? props.contentForTab(tabId) : null
  dispatchEditorContentAction({ id, payload, tabId, content, sourceUrl: tabId ? sourceUrlForTab(tabId) : '', emit, toggleRemotePage: toggleWechatRemotePage, exportTranscript: exportVideoSubtitles, requestCover: requestWechatCoverGeneration })
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
  grid-template-rows: minmax(0, 1fr);
  margin: 0;
  padding-inline: 0;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: var(--vk-bg-center);
}

.tab-content-workspace {
  position: relative;
  z-index: 0;
  grid-row: 1;
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

.media-preview-loader {
  position: absolute;
  z-index: 3;
  inset: 0;
  display: grid;
  place-items: center;
  pointer-events: none;
}

.media-preview-spinner {
  width: 22px;
  height: 22px;
  box-sizing: border-box;
  border: 2px solid color-mix(in srgb, var(--vk-on-media) 38%, transparent);
  border-top-color: var(--vk-on-media);
  border-radius: 50%;
  filter: drop-shadow(0 1px 2px color-mix(in srgb, var(--vk-media-surface) 54%, transparent));
  animation: media-preview-spin 0.78s linear infinite;
}

.media-preview-loader.is-empty .media-preview-spinner {
  border-color: color-mix(in srgb, var(--vk-muted) 38%, transparent);
  border-top-color: var(--vk-muted);
  filter: none;
}

@keyframes media-preview-spin {
  to { transform: rotate(360deg); }
}

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

@media (prefers-reduced-motion: reduce) {
  .media-preview-spinner { animation: none; }
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

.xhs-capture-image-loading {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: var(--vk-space-panel) var(--vk-space-page);
  gap: var(--vk-space-control);
  box-sizing: border-box;
}

.xhs-capture-image-stream {
  position: relative;
  width: min(74%, 430px);
  min-width: min(74%, 260px);
  min-height: 0;
  height: min(82%, 360px);
  align-self: center;
  justify-self: center;
}

.xhs-capture-image-sheet {
  position: absolute;
  inset: 0;
  display: block;
  border: 1px solid color-mix(in srgb, var(--vk-border) 86%, transparent);
  border-radius: var(--vk-radius-surface);
  background: linear-gradient(
    105deg,
    color-mix(in srgb, var(--vk-bg-quiet) 84%, var(--vk-bg-panel)) 12%,
    color-mix(in srgb, var(--vk-bg-panel) 94%, #fff) 46%,
    color-mix(in srgb, var(--vk-bg-quiet) 84%, var(--vk-bg-panel)) 78%
  );
  background-size: 220% 100%;
  box-shadow: none;
  animation: xhs-capture-shimmer 1.55s linear infinite;
}

.xhs-capture-image-sheet.is-back {
  opacity: 0.38;
  transform: translate(-12px, -10px) rotate(-2deg);
  animation-delay: -0.52s;
}

.xhs-capture-image-sheet.is-middle {
  opacity: 0.64;
  transform: translate(10px, -5px) rotate(1.4deg);
  animation-delay: -0.26s;
}

.xhs-capture-image-sheet.is-front {
  position: relative;
  opacity: 1;
}

.xhs-capture-loading-copy {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--vk-space-sm);
  min-width: 0;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  line-height: var(--vk-leading-label);
  text-align: left;
}

.xhs-capture-loading-copy > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.xhs-capture-loading-copy strong {
  color: var(--vk-text);
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.xhs-capture-loading-copy small {
  overflow: hidden;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.xhs-capture-loading-pulse {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--vk-accent);
  animation: xhs-capture-pulse 1.5s var(--vk-ease-out) infinite;
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

.xhs-capture-text-loading {
  align-self: flex-start;
  box-sizing: border-box;
  width: min(820px, 100%);
  min-height: 0;
  margin: 0 auto;
  padding: 0 var(--vk-space-page) var(--vk-space-section);
  --ai-skeleton-stream-width: 100%;
  --ai-skeleton-stream-padding: 0;
}

@keyframes xhs-capture-shimmer {
  from { background-position: 100% 0; }
  to { background-position: -120% 0; }
}

@keyframes xhs-capture-pulse {
  0%, 100% { opacity: 0.48; transform: scale(0.84); }
  50% { opacity: 1; transform: scale(1); }
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

.transcript-timeline.is-generating {
  overflow: hidden;
}

/* This is deliberately shaped like the real timed transcript rather than a
   generic loading card. It gives the user a truthful, quiet indication that
   text is arriving while leaving the video independently usable above. */
.transcript-generation {
  width: min(100%, 720px);
  display: grid;
  align-content: start;
  gap: 22px;
  padding: 28px 24px;
}

.transcript-generation-heading {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.transcript-generation-heading strong,
.transcript-generation-heading small {
  display: block;
}

.transcript-generation-heading strong {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-medium);
  line-height: 1.45;
}

.transcript-generation-heading small {
  margin-top: 3px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  line-height: 1.5;
}

.transcript-generation-pulse {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--vk-accent);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--vk-accent) 28%, transparent);
  animation: transcript-generation-pulse 1.7s var(--vk-ease-out) infinite;
}

.transcript-generation-lines {
  display: grid;
  gap: 12px;
  width: min(100%, 580px);
}

.transcript-generation-line {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
}

.transcript-generation-line > span {
  color: color-mix(in srgb, var(--vk-muted) 72%, transparent);
  font-family: var(--vk-font-mono);
  font-size: 12px;
  line-height: 1;
}

.transcript-generation-line > i {
  position: relative;
  display: block;
  width: 78%;
  height: 10px;
  overflow: hidden;
  border-radius: 3px;
  background: color-mix(in srgb, var(--vk-border) 62%, var(--vk-bg-panel));
}

.transcript-generation-line > i::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    color-mix(in srgb, #ffffff 56%, var(--vk-border)) 48%,
    transparent 100%
  );
  transform: translateX(-110%);
  animation: transcript-generation-shimmer 1.2s linear infinite;
  will-change: transform;
}

.transcript-generation-line.is-wide > i { width: 92%; }
.transcript-generation-line.is-medium > i { width: 64%; }
.transcript-generation-line.is-long > i { width: 82%; }
.transcript-generation-line.is-short > i { width: 43%; }
.transcript-generation-line:nth-child(2) > i::after { animation-delay: 0.12s; }
.transcript-generation-line:nth-child(3) > i::after { animation-delay: 0.24s; }
.transcript-generation-line:nth-child(4) > i::after { animation-delay: 0.36s; }

@keyframes transcript-generation-shimmer {
  to { transform: translateX(110%); }
}

@keyframes transcript-generation-pulse {
  55% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--vk-accent) 0%, transparent); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--vk-accent) 0%, transparent); }
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

  .transcript-generation-pulse,
  .transcript-generation-line > i::after,
  .xhs-capture-image-sheet,
  .xhs-capture-loading-pulse {
    animation: none;
  }

  .transcript-generation-pulse,
  .xhs-capture-loading-pulse {
    opacity: 0.72;
    box-shadow: none;
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
  .report-footnote-return,
  .transcript-follow-button,
  .reader-selection-ask {
    background: var(--vk-bg-panel) !important;
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-contrast: more) {
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
