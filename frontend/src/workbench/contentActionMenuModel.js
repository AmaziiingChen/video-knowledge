export function createContentActionMenuModel(context = {}) {
  const content = context.content || null
  const retrying = Boolean(content?.id && context.retryingContentId === content.id)
  const coverBusy = Boolean(context.coverGenerating || context.coverSwitching)
  const actions = []

  if (context.hasRemoteSource) {
    actions.push(
      { id: 'copy-source', label: '复制原链接' },
      { id: 'open-source', label: '在外部浏览器打开' },
    )
  }
  if (context.remotePageAvailable) {
    actions.push({
      id: 'toggle-remote-page',
      label: context.remotePageLabel || '打开原始网页',
      disabled: Boolean(context.remotePageLoading),
    })
  }
  if (context.articleTextRetryable) {
    actions.push({
      id: 'retry-source-text',
      label: context.articleTextStatus === 'needs_fetch' ? '获取正文' : '重试正文',
      disabled: retrying,
    })
  }
  if (content?.status === 'failed') {
    actions.push({ id: 'retry-processing', label: '重新处理', disabled: retrying })
  }
  if (context.canReprocessLocalSource) {
    actions.push({
      id: 'reprocess-local-source',
      label: context.localReprocessLabel || '重新处理本地文件',
      disabled: retrying,
    })
  }
  if (content?.original_file_path) actions.push({ id: 'open-original-file', label: '打开原始文件' })
  if (context.canRetranscribeMedia) {
    actions.push({
      id: 'retranscribe-media',
      label: context.isAudio ? '重新转写音频' : '重新转写视频',
      disabled: retrying,
    })
  }
  if (context.canFetchExternalSubtitle) {
    actions.push({ id: 'fetch-external-subtitle', label: '尝试获取外挂字幕', disabled: retrying })
  }
  if (context.canRefreshSourceContext) {
    actions.push({ id: 'refresh-source-context', label: '补采互动与评论', disabled: retrying })
  }
  if (context.canDownloadVideo) {
    actions.push({
      id: 'download-video',
      label: context.videoCacheExpired ? '重新下载视频' : '下载视频',
      disabled: retrying,
    })
  }
  if (context.isTimedMedia) {
    actions.push({
      id: 'export-transcript',
      label: '导出字幕 / 转写 (.txt)',
      disabled: !context.hasTimelineSegments,
    })
  }
  if (context.isReport) {
    actions.push({
      id: 'generate-cover',
      label: content?.cover_url ? '重新生成 AI 封面' : '生成 AI 封面',
      disabled: coverBusy,
    })
    if (content?.cover_url) {
      actions.push({ id: 'replan-cover', label: '重新策划封面主题', disabled: coverBusy })
    }
    actions.push({
      id: 'create-wechat-draft',
      label: context.publishingConfigured ? '存入公众号草稿' : '配置公众号草稿发布',
      disabled: Boolean(context.coverSwitching),
    })
  }
  if (content) actions.push({ id: 'delete-content', label: '移入回收站', danger: true })

  return {
    actions,
    details: Array.isArray(context.details) ? context.details : [],
  }
}
