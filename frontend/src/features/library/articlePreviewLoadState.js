export function pendingArticlePreview(currentPreview, readiness) {
  const status = readiness?.status || 'pending'
  const loadingLabel = status === 'needs_fetch'
    ? '本地正文快照未就绪，正在获取原文…'
    : status === 'pending'
      ? '正在检查本地正文快照…'
      : '正在读取本地正文快照…'
  return {
    ...currentPreview,
    loading: true,
    showLoader: false,
    loading_label: loadingLabel,
    // A ready item already has a server-side local snapshot.  Its very short
    // local read should not flash a loading message before the iframe mounts.
    silent: status === 'ready',
  }
}

export function revealArticlePreviewLoader(preview) {
  return { ...preview, showLoader: true }
}

export function shouldShowArticlePreviewLoader(preview) {
  return Boolean(preview?.loading && preview?.showLoader && !preview?.silent)
}
