export function sourceProviderFromUrl(value) {
  const url = String(value || '').toLowerCase()
  if (/https?:\/\/(?:v\.)?douyin\.com\//.test(url)) return 'douyin'
  if (/https?:\/\/(?:www\.)?bilibili\.com\/video\//.test(url) || /https?:\/\/b23\.tv\//.test(url)) return 'bilibili'
  if (/https?:\/\/mp\.weixin\.qq\.com\//.test(url)) return 'wechat'
  return ''
}
