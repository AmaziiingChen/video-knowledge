const documentIcon = 'text.document'
const filmIcon = 'film'
const waveformIcon = 'waveform'

export const VIDEO_ICON_PROVIDERS = new Set(['bilibili', 'douyin'])

export function libraryContentIcon(item) {
  const provider = String(item?.source_provider || '').trim().toLowerCase()
  if (item?.content_type === 'audio') return waveformIcon
  return VIDEO_ICON_PROVIDERS.has(provider) || item?.content_type === 'video' ? filmIcon : documentIcon
}

export function cacheContentIcon(item) {
  return item?.content_kind === 'article' ? documentIcon : filmIcon
}
