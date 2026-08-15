const MIN_READER_WIDTH = 760
const MIN_READER_HEIGHT = 300
const MIN_LEFT_GUTTER = 70
const MARKER_PITCH = 16
const MIN_RAIL_HEIGHT = 64

export function canShowReportOutline({
  width,
  height,
  entryCount,
  leftGutter = 0,
}) {
  if (Number(height) < MIN_READER_HEIGHT || Number(entryCount) < 2) return false
  // Embedded originals and local readers both need enough horizontal room;
  // otherwise the fixed rail sits on top of the article text.
  return Number(width) >= MIN_READER_WIDTH && Number(leftGutter) >= MIN_LEFT_GUTTER
}

export function reportOutlineHeight({ availableHeight, readerHeight, entryCount }) {
  const maximumHeight = Math.min(Number(availableHeight), Number(readerHeight) * 0.75)
  if (!Number.isFinite(maximumHeight) || maximumHeight < MIN_RAIL_HEIGHT) return 0
  const naturalHeight = Math.max(0, Number(entryCount)) * MARKER_PITCH
  return Math.min(Math.max(naturalHeight, MIN_RAIL_HEIGHT), maximumHeight)
}
