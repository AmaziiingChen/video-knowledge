const SINGLE_PANE_WORKSPACE_VIEWS = new Set([
  'wechat',
  'campus',
  'creator',
  'rss',
  'reports',
])

export function isSinglePaneWorkspaceView(view) {
  return SINGLE_PANE_WORKSPACE_VIEWS.has(String(view || ''))
}
