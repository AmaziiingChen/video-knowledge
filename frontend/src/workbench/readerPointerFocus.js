export const READER_TEXT_FOCUS_SELECTOR = [
  '.report-markdown',
  '.article-preview-body',
  '.transcript-timeline',
].join(', ')

export const READER_INTERACTIVE_SELECTOR = [
  'a[href]',
  'button',
  'input',
  'textarea',
  'select',
  '[contenteditable="true"]',
  '[role="button"]',
].join(', ')

export function shouldClaimReaderFocus(target) {
  if (!target || typeof target.closest !== 'function') return false
  return Boolean(target.closest(READER_TEXT_FOCUS_SELECTOR))
    && !target.closest(READER_INTERACTIVE_SELECTOR)
}
