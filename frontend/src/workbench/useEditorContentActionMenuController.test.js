import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'
import { useEditorContentActionMenuController } from './useEditorContentActionMenuController.js'

function createHarness(content) {
  const activeContentTab = ref({ id: 'tab:one' })
  const events = []
  const anchors = []
  const blobs = []
  const revoked = []
  const props = reactive({
    contentForTab: () => content,
    resultForTab: () => ({}),
    workspaceTabById: () => ({ id: 'tab:one', opened_at: '2026-01-01' }),
    selectedContentItem: content,
    selectedMarkdownPath: '/vault/current.md',
    selectedMarkdownSizeBytes: 128,
    sourceProviderLabel: (value) => value,
    formatBytes: (value) => `${value} B`,
    formatDuration: (value) => `${value}s`,
    formatDateTime: (value) => String(value || ''),
    retryingContentId: null,
    wechatPublishingConfigured: false,
  })
  const controller = useEditorContentActionMenuController({
    props,
    activeContentTab,
    canOpenRemotePage: ref(false),
    activeRemotePage: ref(null),
    remoteActionLabel: ref('打开原始网页'),
    sourceUrlForTab: () => content.source_url || '',
    readerTextForMetadata: () => '可阅读正文',
    hasRemoteSource: () => Boolean(content.source_url),
    isTimedMediaTab: () => ['video', 'audio'].includes(content.content_type),
    isArticleTab: () => content.content_type === 'article',
    isAudioTab: () => content.content_type === 'audio',
    isReportTab: () => content.content_type === 'report',
    timelineSegmentsForTab: () => content.timeline || [],
    isCoverGenerating: () => false,
    isCoverSwitching: () => false,
    toggleRemotePage: () => events.push(['toggle']),
    requestCover: (tabId) => events.push(['cover', tabId]),
    emit: (...args) => events.push(args),
    createObjectUrl: (blob) => { blobs.push(blob); return 'blob:transcript' },
    revokeObjectUrl: (url) => revoked.push(url),
    createTextBlob: (value) => value,
    createDownloadAnchor: () => {
      const anchor = { clickCount: 0, click() { this.clickCount += 1 } }
      anchors.push(anchor)
      return anchor
    },
    scheduleTimer: (callback) => callback(),
  })
  return { controller, events, anchors, blobs, revoked, props }
}

test('builds local document actions and current Markdown details', () => {
  const { controller } = createHarness({
    id: 'content:pdf', content_type: 'article', source_provider: 'local_file',
    source_name: '外部 PDF', original_file_path: '/imports/source.pdf', title: '资料',
  })
  const model = controller.activeContentActionMenuModel.value
  assert.equal(model.actions.find((action) => action.id === 'reprocess-local-source')?.label, '重新识别 PDF')
  assert.equal(model.actions.some((action) => action.id === 'open-original-file'), true)
  assert.equal(model.details.find((row) => row.label === '文件位置')?.value, '/vault/current.md')
})

test('keeps remote video eligibility and action payloads on the existing contract', () => {
  const content = {
    id: 'content:video', content_type: 'video', source_provider: 'bilibili',
    source_url: 'https://www.bilibili.com/video/BV1', title: '视频', timeline: [],
  }
  const { controller, events } = createHarness(content)
  const actions = controller.activeContentActionMenuModel.value.actions
  assert.equal(actions.some((action) => action.id === 'fetch-external-subtitle'), true)
  assert.equal(actions.some((action) => action.id === 'download-video'), true)
  assert.equal(actions.find((action) => action.id === 'export-transcript')?.disabled, true)
  controller.handleContentActionMenuSelect({ id: 'fetch-external-subtitle' })
  controller.handleContentActionMenuSelect({ id: 'copy-source' })
  assert.deepEqual(events, [
    ['fetch-external-subtitle', content],
    ['copy-text', content.source_url, '链接已复制'],
  ])
})

test('keeps the expired video cache predicate available to the preview surface', () => {
  const content = {
    id: 'content:video', content_type: 'video', video_cache_status: 'expired',
  }
  const { controller } = createHarness(content)

  assert.equal(controller.isVideoCacheExpired('content:1'), true)
  content.video_cache_status = 'ready'
  assert.equal(controller.isVideoCacheExpired('content:1'), false)
})

test('exports a BOM transcript with a portable bounded filename and revokes its URL', () => {
  const content = {
    id: 'content:audio', content_type: 'audio', source_provider: 'local_file',
    original_file_path: '/imports/audio.m4a', title: 'A/B:*? 音频',
    timeline: [{ start_seconds: 65.2, text: ' 第一段 ' }],
  }
  const { controller, anchors, blobs, revoked } = createHarness(content)
  controller.handleContentActionMenuSelect({ id: 'export-transcript' })
  assert.equal(blobs[0], '\uFEFF[01:05] 第一段\n')
  assert.equal(anchors[0].download, 'A-B- 音频-字幕.txt')
  assert.equal(anchors[0].href, 'blob:transcript')
  assert.equal(anchors[0].clickCount, 1)
  assert.deepEqual(revoked, ['blob:transcript'])
})
