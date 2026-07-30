export const READING_CHARACTERS_PER_MINUTE = 350

export function clampReadingProgress(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.min(100, Math.max(0, Math.round(numeric)))
}

export function readingProgressFromScroll({ scrollTop = 0, scrollHeight = 0, clientHeight = 0 } = {}) {
  const scrollableHeight = Number(scrollHeight) - Number(clientHeight)
  if (!Number.isFinite(scrollableHeight) || scrollableHeight <= 1) return 100
  return clampReadingProgress((Number(scrollTop) / scrollableHeight) * 100)
}

export function estimatedReadingMinutes(characterCount, charactersPerMinute = READING_CHARACTERS_PER_MINUTE) {
  const count = Number(characterCount)
  const pace = Number(charactersPerMinute)
  if (!Number.isFinite(count) || count <= 0 || !Number.isFinite(pace) || pace <= 0) return 0
  return Math.max(1, Math.ceil(count / pace))
}

export function remainingReadingMinutes(characterCount, progress, charactersPerMinute = READING_CHARACTERS_PER_MINUTE) {
  const normalizedProgress = clampReadingProgress(progress)
  if (normalizedProgress >= 100) return 0
  const remainingCharacters = Number(characterCount) * (1 - normalizedProgress / 100)
  return estimatedReadingMinutes(remainingCharacters, charactersPerMinute)
}
