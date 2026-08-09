export const articleOutlineHeadingSelector = 'h1, h2, h3, h4, .article-section-heading'

function normalizedOutlineText(value) {
  return String(value || '').replace(/\s+/gu, ' ').trim()
}

export function createArticleOutlineModel({ activeArticleTitle }) {
  function isArticleOutlineHeading(element, text) {
    const normalized = normalizedOutlineText(text)
    if (normalized.length < 2 || normalized.length > 84) return false
    // The reader already renders the article title and metadata above the
    // iframe. Do not make a duplicated page H1 into a navigation waypoint.
    const title = normalizedOutlineText(activeArticleTitle())
    if (title && normalized === title) return false
    if (/^(?:原文内容|图片文字\s*\d*|微信公众号|微信公众平台|校园论坛)$/u.test(normalized)) return false
    if (element.closest('table, figure, figcaption, [data-wechat-image-ocr]')) return false
    return true
  }

  function articleOutlineHeadingLevel(element) {
    const tag = String(element?.tagName || '').toUpperCase()
    // The rail intentionally communicates two levels. Treat captured H1/H2 as
    // primary sections and H3/H4 or recovered numbered text as children.
    return ['H1', 'H2'].includes(tag) ? 2 : 3
  }

  return { articleOutlineHeadingLevel, isArticleOutlineHeading }
}
