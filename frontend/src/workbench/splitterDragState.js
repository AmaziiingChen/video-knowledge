export const PANE_SNAP_COLLAPSE_WIDTH = 120
export const PANE_SNAP_REOPEN_WIDTH = 148
export const COLLAPSED_PANE_REVEAL_DISTANCE = 50
export const COLLAPSED_PANE_SIZE = 0
export const MAX_PROCESS_LOG_HEIGHT = 360
export const PROCESS_LOG_SNAP_COLLAPSE_HEIGHT = 96
export const PROCESS_LOG_SNAP_REOPEN_HEIGHT = 124
export const MIN_PROCESS_LOG_TASK_WIDTH = 180
export const MAX_PROCESS_LOG_TASK_WIDTH = 560
export const MIN_PROCESS_LOG_OUTPUT_WIDTH = 400
export const PROCESS_LOG_TASK_SPLITTER_WIDTH = 8
export const VERTICAL_CONTENT_SPLITTER_HEIGHT = 8
export const VERTICAL_CONTENT_PRIMARY_MIN_HEIGHT = 150
export const VERTICAL_CONTENT_SECONDARY_MIN_HEIGHT = 160

export function revealProgressForDistance(distance, threshold = COLLAPSED_PANE_REVEAL_DISTANCE) {
  const safeThreshold = Math.max(1, Number(threshold) || COLLAPSED_PANE_REVEAL_DISTANCE)
  return Math.min(1, Math.max(0, Number(distance) || 0) / safeThreshold)
}

export function processLogRevealHeight(
  distance,
  collapsedSize = COLLAPSED_PANE_SIZE,
  maxHeight = MAX_PROCESS_LOG_HEIGHT,
) {
  const safeCollapsedSize = Math.max(0, Number(collapsedSize) || 0)
  const safeMaxHeight = Math.max(safeCollapsedSize, Number(maxHeight) || MAX_PROCESS_LOG_HEIGHT)
  return Math.min(safeMaxHeight, safeCollapsedSize + Math.max(0, Number(distance) || 0))
}

export function resolveProcessLogDragTransition(state, targetHeight) {
  const collapsed = Boolean(state?.collapsed)

  if (collapsed) {
    if (targetHeight < PROCESS_LOG_SNAP_REOPEN_HEIGHT) {
      return { collapsed: true, action: 'none' }
    }
    return { collapsed: false, action: 'open' }
  }

  if (targetHeight < PROCESS_LOG_SNAP_COLLAPSE_HEIGHT) {
    return { collapsed: true, action: 'collapse' }
  }

  return { collapsed: false, action: 'resize' }
}

export function clampProcessLogTaskWidth(
  width,
  containerWidth,
  minTaskWidth = MIN_PROCESS_LOG_TASK_WIDTH,
  maxTaskWidth = MAX_PROCESS_LOG_TASK_WIDTH,
  minOutputWidth = MIN_PROCESS_LOG_OUTPUT_WIDTH,
  splitterWidth = PROCESS_LOG_TASK_SPLITTER_WIDTH,
) {
  const min = Math.max(0, Number(minTaskWidth) || MIN_PROCESS_LOG_TASK_WIDTH)
  const preferredMax = Math.max(min, Number(maxTaskWidth) || MAX_PROCESS_LOG_TASK_WIDTH)
  const available = Number(containerWidth)
  const widthLimitedMax = Number.isFinite(available)
    ? Math.max(min, available - Math.max(0, Number(minOutputWidth) || 0) - Math.max(0, Number(splitterWidth) || 0))
    : preferredMax
  const max = Math.min(preferredMax, widthLimitedMax)
  const candidate = Number(width)
  return Math.round(Math.max(min, Math.min(max, Number.isFinite(candidate) ? candidate : min)))
}

export function resolvePaneDragTransition(state, targetWidth) {
  const collapsed = Boolean(state?.collapsed)

  if (collapsed) {
    if (targetWidth < PANE_SNAP_REOPEN_WIDTH) {
      return { collapsed: true, action: 'none' }
    }
    return { collapsed: false, action: 'open' }
  }

  if (targetWidth < PANE_SNAP_COLLAPSE_WIDTH) {
    return { collapsed: true, action: 'collapse' }
  }

  return { collapsed: false, action: 'resize' }
}

/**
 * Keeps a vertical media/text layout usable when the workbench becomes short.
 * The preferred 25–75% range remains in effect on normal windows. On a short
 * viewport the physical minimum heights take precedence, scaled together when
 * both minima cannot fit at once.
 */
export function verticalContentSplitBounds(
  containerHeight,
  primaryMinHeight = VERTICAL_CONTENT_PRIMARY_MIN_HEIGHT,
  secondaryMinHeight = VERTICAL_CONTENT_SECONDARY_MIN_HEIGHT,
  splitterHeight = VERTICAL_CONTENT_SPLITTER_HEIGHT,
  preferredMin = 25,
  preferredMax = 75,
) {
  const total = Math.max(1, Number(containerHeight) || 0)
  const available = Math.max(1, total - Math.max(0, Number(splitterHeight) || 0))
  const requestedPrimary = Math.max(0, Number(primaryMinHeight) || 0)
  const requestedSecondary = Math.max(0, Number(secondaryMinHeight) || 0)
  // CSS uses one half of the available height as the emergency minimum for
  // each row. Mirror that rule here so ARIA values and pointer clamping always
  // describe the visible layout, including very short windows.
  const halfAvailable = available / 2
  const safePrimary = Math.min(requestedPrimary, halfAvailable)
  const safeSecondary = Math.min(requestedSecondary, halfAvailable)
  const lower = Math.max(Number(preferredMin) || 0, (safePrimary / total) * 100)
  const upper = Math.min(Number(preferredMax) || 100, ((total - safeSecondary) / total) * 100)

  if (lower <= upper) return { min: lower, max: upper }

  const midpoint = Math.max(0, Math.min(100, (lower + upper) / 2))
  return { min: midpoint, max: midpoint }
}

export function clampVerticalContentSplit(value, containerHeight, ...options) {
  const bounds = verticalContentSplitBounds(containerHeight, ...options)
  const candidate = Number(value)
  const safeValue = Number.isFinite(candidate) ? candidate : (bounds.min + bounds.max) / 2
  return Math.round(Math.max(bounds.min, Math.min(bounds.max, safeValue)))
}
