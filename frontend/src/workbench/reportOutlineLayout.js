export function canShowReportOutline({ width, height, entryCount }) {
  // The reader normally shares the window with both sidebars.  A rail is still
  // useful in that common layout; it only needs enough room for its 52px
  // markers plus readable body text, not a full-width standalone reader.
  return Number(width) >= 520 && Number(height) >= 300 && Number(entryCount) >= 2
}
