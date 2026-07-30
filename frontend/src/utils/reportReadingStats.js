const INLINE_REFERENCE_PATTERN =
  /<sup\b[^>]*class=["'][^"']*\bmarkdown-footnote-ref\b[^"']*["'][^>]*>[\s\S]*?<\/sup>/giu
const SOURCE_INDEX_PATTERN =
  /<section\b[^>]*class=["'][^"']*\bmarkdown-footnotes\b[^"']*["'][^>]*>[\s\S]*?<\/section>/giu

export function reportBodyHtmlForCharacterCount(html) {
  return String(html || '')
    .replace(INLINE_REFERENCE_PATTERN, '')
    .replace(SOURCE_INDEX_PATTERN, '')
}

export function readableCharacterCount(value) {
  return Array.from(String(value || '').replace(/\s+/gu, '')).length
}
