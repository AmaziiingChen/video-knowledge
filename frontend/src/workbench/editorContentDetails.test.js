import assert from 'node:assert/strict'
import test from 'node:test'
import { editorContentDetailRows } from './editorContentDetails.js'

test('keeps media metadata, local path, and remote source details', () => {
  const rows = editorContentDetailRows({
    content: { source_provider: 'local_file', duration_seconds: 12, created_at: 'created', updated_at: 'updated', source_metadata: { file_format: 'MP4', video_codec: 'h264', audio_codec: 'aac', sample_rate: 44100, channels: 2 } },
    tab: {}, sourceUrl: 'https://example.com', readableText: 'hello', markdownPath: '/vault/a.md', isTimedMedia: true,
    format: { sourceProvider: (v) => v, characters: (v) => String(v).length, documentSize: () => 'size', duration: (v) => `${v}s`, bytes: String, dateTime: String },
  })
  assert.deepEqual(rows.map((row) => row.label), ['来源', '字符数', '时长', '格式', '视频编码', '音频编码', '采样率', '声道', '导入时间', '修改时间', '文件位置', '原文链接'])
  assert.equal(rows.find((row) => row.label === '文件位置').kind, 'path')
  assert.equal(rows.find((row) => row.label === '原文链接').kind, 'url')
})
