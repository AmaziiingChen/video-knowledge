import assert from 'node:assert/strict'
import test from 'node:test'
import { activeTimelineSegmentKey, formatTimelineTime, mediaTranscriptState, normalizeTranscriptSegments } from './mediaTranscriptModel.js'

test('normalizes usable segments and falls back to an approximate transcript', () => {
  assert.deepEqual(normalizeTranscriptSegments([{ text: '', start_seconds: 0 }, { position: 3, text: '片段', approximate: 1 }]), [{ position: 3, start_seconds: undefined, text: '片段', approximate: true }])
  assert.deepEqual(normalizeTranscriptSegments([], '  缓存字幕  '), [{ position: 0, start_seconds: 0, text: '缓存字幕', approximate: true }])
})

test('only timed media exposes transcript workspace and processing state', () => {
  assert.equal(mediaTranscriptState({ isTimedMedia: false, fallbackTranscript: '文档正文', taskStatus: 'running' }).hasWorkspace, false)
  assert.equal(mediaTranscriptState({ isTimedMedia: true, taskStatus: 'running', taskStep: 'transcribe' }).showGeneration, true)
  assert.equal(mediaTranscriptState({ isTimedMedia: true, taskStep: 'transcribe' }).label, '正在转写音频')
})

test('maps generation stages to stable user-facing descriptions', () => {
  assert.equal(mediaTranscriptState({ taskStep: 'download' }).description, '下载与字幕获取会并行进行，首段文本就绪后会立即显示。')
  assert.equal(mediaTranscriptState({ taskStep: 'extract_audio' }).label, '正在提取音频')
  assert.equal(mediaTranscriptState({ taskStep: 'save' }).label, '正在整理字幕文本')
})

test('selects the active timeline segment only for the active tab', () => {
  const segments = [{ position: 0, start_seconds: 0 }, { position: 1, start_seconds: 10 }]
  assert.equal(activeTimelineSegmentKey({ tabId: 'a', activeTabId: 'a', segments, playbackTime: 0 }), 'a:0')
  assert.equal(activeTimelineSegmentKey({ tabId: 'a', activeTabId: 'a', segments, playbackTime: 10 }), 'a:1')
  assert.equal(activeTimelineSegmentKey({ tabId: 'a', activeTabId: 'b', segments, playbackTime: 12 }), '')
})

test('formats invalid, negative and long timeline times deterministically', () => {
  assert.equal(formatTimelineTime(Number.NaN), '--:--')
  assert.equal(formatTimelineTime(-1), '00:00')
  assert.equal(formatTimelineTime(3661), '61:01')
})
