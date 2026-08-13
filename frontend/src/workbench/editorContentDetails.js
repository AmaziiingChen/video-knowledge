export function editorContentDetailRows({ content, tab, sourceUrl, readableText, markdownPath, isTimedMedia, format }) {
  const meta = content?.source_metadata || {}
  const rows = [
    { label: '来源', value: format.sourceProvider(content?.source_provider) },
    { label: '字符数', value: format.characters(readableText), title: '按当前可阅读正文统计，不含空白字符' },
    ...(!isTimedMedia ? [{ label: '文档大小', value: format.documentSize(content), title: '当前本地 Markdown 文档的实际 UTF-8 字节大小' }] : []),
    ...(isTimedMedia && content?.duration_seconds ? [{ label: '时长', value: format.duration(content.duration_seconds) }] : []),
    ...(meta.file_format ? [{ label: '格式', value: String(meta.file_format) }] : []),
    ...(meta.file_size_bytes ? [{ label: '原件大小', value: format.bytes(meta.file_size_bytes) }] : []),
    ...(meta.width && meta.height ? [{ label: '尺寸', value: `${meta.width} × ${meta.height}` }] : []),
    ...(meta.page_count ? [{ label: '页数', value: `${meta.page_count} 页` }] : []),
    ...(meta.video_codec ? [{ label: '视频编码', value: String(meta.video_codec) }] : []),
    ...(meta.audio_codec ? [{ label: '音频编码', value: String(meta.audio_codec) }] : []),
    ...(meta.sample_rate ? [{ label: '采样率', value: `${(Number(meta.sample_rate) / 1000).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} kHz` }] : []),
    ...(meta.channels ? [{ label: '声道', value: Number(meta.channels) === 1 ? '单声道' : `${meta.channels} 声道` }] : []),
    { label: '导入时间', value: format.dateTime(content?.created_at || tab?.opened_at) },
    { label: '修改时间', value: format.dateTime(content?.updated_at || tab?.opened_at) },
    ...(markdownPath ? [{ label: '文件位置', value: markdownPath, title: markdownPath, kind: 'path' }] : []),
    ...(sourceUrl ? [{ label: '原文链接', value: sourceUrl, title: sourceUrl, kind: 'url' }] : []),
  ]
  return rows
}
