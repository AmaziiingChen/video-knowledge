import assert from 'node:assert/strict'
import test from 'node:test'

import { createContentActionMenuModel } from './contentActionMenuModel.js'

test('builds a compact action model for a retryable remote video', () => {
  const model = createContentActionMenuModel({
    content: { id: 'content-1', status: 'failed', original_file_path: '/tmp/source.mp4' },
    retryingContentId: 'content-1',
    hasRemoteSource: true,
    canRetranscribeMedia: true,
    canFetchExternalSubtitle: true,
    canRefreshSourceContext: true,
    canDownloadVideo: true,
    videoCacheExpired: true,
    isTimedMedia: true,
    hasTimelineSegments: false,
  })

  assert.deepEqual(model.actions.map((action) => action.id), [
    'copy-source',
    'open-source',
    'retry-processing',
    'open-original-file',
    'retranscribe-media',
    'fetch-external-subtitle',
    'refresh-source-context',
    'download-video',
    'export-transcript',
    'delete-content',
  ])
  assert.equal(model.actions.find((action) => action.id === 'download-video').label, '重新下载视频')
  assert.equal(model.actions.find((action) => action.id === 'retry-processing').disabled, true)
  assert.equal(model.actions.find((action) => action.id === 'export-transcript').disabled, true)
})

test('keeps report cover and publishing states inside the report action model', () => {
  const model = createContentActionMenuModel({
    content: { id: 'report-1', status: 'distilled', cover_url: '/cover.png' },
    isReport: true,
    coverGenerating: true,
    publishingConfigured: false,
    details: [{ label: '来源', value: '公众号' }],
  })

  assert.deepEqual(model.actions.map((action) => action.id), [
    'generate-cover',
    'replan-cover',
    'create-wechat-draft',
    'delete-content',
  ])
  assert.equal(model.actions[0].label, '重新生成 AI 封面')
  assert.equal(model.actions[0].disabled, true)
  assert.equal(model.actions[2].label, '配置公众号草稿发布')
  assert.deepEqual(model.details, [{ label: '来源', value: '公众号' }])
})
