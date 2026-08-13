import { computed } from 'vue'
import { createContentActionMenuModel } from './contentActionMenuModel.js'
import { dispatchEditorContentAction } from './editorContentActions.js'
import { editorContentDetailRows } from './editorContentDetails.js'
import {
  formatReadableCharacterCount,
  formatReaderDocumentSize,
} from './editorReaderMetadata.js'
import { formatTimelineTime } from './mediaTranscriptModel.js'

export function useEditorContentActionMenuController({
  props,
  activeContentTab,
  canOpenRemotePage,
  activeRemotePage,
  remoteActionLabel,
  sourceUrlForTab,
  readerTextForMetadata,
  hasRemoteSource,
  isTimedMediaTab,
  isArticleTab,
  isAudioTab,
  isReportTab,
  timelineSegmentsForTab,
  isCoverGenerating,
  isCoverSwitching,
  toggleRemotePage,
  requestCover,
  emit,
  createObjectUrl = (blob) => URL.createObjectURL(blob),
  revokeObjectUrl = (url) => URL.revokeObjectURL(url),
  createTextBlob = (content) => new Blob([content], { type: 'text/plain;charset=utf-8' }),
  createDownloadAnchor = () => document.createElement('a'),
  scheduleTimer = (callback) => window.setTimeout(callback, 0),
}) {
  function contentForTab(tabId) {
    return props.contentForTab(tabId)
  }

  function canRetranscribeMedia(tabId) {
    const content = contentForTab(tabId)
    if (!isTimedMediaTab(tabId)) return false
    if (content?.source_provider === 'local_file') return Boolean(content?.original_file_path)
    return Boolean(props.resultForTab(tabId)?.video_path || content?.video_path)
  }

  function canFetchExternalSubtitle(tabId) {
    const content = contentForTab(tabId)
    return content?.content_type === 'video'
      && content?.source_provider === 'bilibili'
      && Boolean(content?.source_url)
  }

  function canRefreshSourceContext(tabId) {
    const content = contentForTab(tabId)
    return ['bilibili', 'douyin'].includes(content?.source_provider)
      && Boolean(content?.source_url)
  }

  function isVideoCacheExpired(tabId) {
    const content = contentForTab(tabId)
    return content?.content_type === 'video' && content?.video_cache_status === 'expired'
  }

  function canDownloadVideo(tabId) {
    const content = contentForTab(tabId)
    return content?.content_type === 'video'
      && content?.source_provider !== 'local_file'
      && !content?.video_path
      && hasRemoteSource(tabId)
  }

  function canReprocessLocalSource(tabId) {
    return contentForTab(tabId)?.source_provider === 'local_file' && !isTimedMediaTab(tabId)
  }

  function localReprocessLabel(tabId) {
    const content = contentForTab(tabId)
    if (content?.content_type === 'image') return '重新识别图片文字'
    const source = String(content?.source_name || '')
    if (source.includes('PDF')) return '重新识别 PDF'
    if (source.includes('HTML')) return '重新提取 HTML 正文'
    if (source.includes('Word')) return '重新提取 Word 正文'
    return '重新提取原文件'
  }

  function contentDetailRows(tabId) {
    const content = contentForTab(tabId)
    const tab = props.workspaceTabById(tabId)
    const sourceUrl = sourceUrlForTab(tabId)
    const isTimedMedia = isTimedMediaTab(tabId)
    const isCurrentDocument = String(content?.id || '') === String(props.selectedContentItem?.id || '')
    const markdownPath = isCurrentDocument
      ? String(props.selectedMarkdownPath || content?.markdown_draft_path || '')
      : String(content?.markdown_draft_path || '')
    return editorContentDetailRows({
      content,
      tab,
      sourceUrl: hasRemoteSource(tabId) ? sourceUrl : '',
      readableText: readerTextForMetadata(tabId),
      markdownPath,
      isTimedMedia,
      format: {
        sourceProvider: props.sourceProviderLabel,
        characters: formatReadableCharacterCount,
        documentSize: (item) => formatReaderDocumentSize(item, {
          selectedContentId: props.selectedContentItem?.id,
          selectedMarkdownSizeBytes: props.selectedMarkdownSizeBytes,
          formatBytes: props.formatBytes,
        }),
        duration: props.formatDuration,
        bytes: props.formatBytes,
        dateTime: props.formatDateTime,
      },
    })
  }

  function exportTranscript(tabId) {
    const segments = timelineSegmentsForTab(tabId)
    if (!segments.length) return
    const lines = segments.map((segment) => `[${formatTimelineTime(segment.start_seconds)}] ${segment.text.trim()}`)
    const title = String(contentForTab(tabId)?.title || '字幕').trim()
    const filename = `${(title || '字幕').replace(/[\\/:*?"<>|]+/gu, '-').slice(0, 80)}-字幕.txt`
    const url = createObjectUrl(createTextBlob(`\uFEFF${lines.join('\n').trimEnd()}\n`))
    const anchor = createDownloadAnchor()
    anchor.href = url
    anchor.download = filename
    anchor.click()
    scheduleTimer(() => revokeObjectUrl(url))
  }

  const activeContentActionMenuModel = computed(() => {
    const tabId = activeContentTab.value?.id || ''
    const content = tabId ? contentForTab(tabId) : null
    const textReadiness = content?.text_readiness || null
    return createContentActionMenuModel({
      content,
      retryingContentId: props.retryingContentId,
      hasRemoteSource: tabId ? hasRemoteSource(tabId) : false,
      remotePageAvailable: canOpenRemotePage.value,
      remotePageLoading: activeRemotePage.value?.status === 'loading',
      remotePageLabel: remoteActionLabel.value,
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
      coverGenerating: tabId ? isCoverGenerating(tabId) : false,
      coverSwitching: tabId ? isCoverSwitching(tabId) : false,
      publishingConfigured: props.wechatPublishingConfigured,
      details: tabId ? contentDetailRows(tabId) : [],
    })
  })

  function handleContentActionMenuSelect({ id, payload } = {}) {
    const tabId = activeContentTab.value?.id || ''
    const content = tabId ? contentForTab(tabId) : null
    dispatchEditorContentAction({
      id,
      payload,
      tabId,
      content,
      sourceUrl: tabId ? sourceUrlForTab(tabId) : '',
      emit,
      toggleRemotePage,
      exportTranscript,
      requestCover,
    })
  }

  return {
    activeContentActionMenuModel,
    handleContentActionMenuSelect,
    isVideoCacheExpired,
  }
}
