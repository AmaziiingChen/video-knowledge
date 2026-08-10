import assert from 'node:assert/strict'
import test from 'node:test'

import { ref } from 'vue'

import { useDesktopBootstrapSettingsController } from './useDesktopBootstrapSettingsController.js'

function createController({ responses = [], selectedModel = 'local-model' } = {}) {
  const requests = []
  const updateChecks = []
  const selectedAiModel = ref(selectedModel)
  const controller = useDesktopBootstrapSettingsController({
    selectedAiModel,
    normalizeAiModelValue: (model) => `normalized:${model}`,
    checkManualUpdate: () => updateChecks.push('checked'),
    request: {
      get: async (url) => {
        requests.push(url)
        const response = responses[requests.length - 1]
        if (response instanceof Error) throw response
        return { data: response }
      },
    },
    apiBase: 'http://api.test',
  })
  return { controller, requests, selectedAiModel, updateChecks }
}

test('loads current backend choices without replacing a locally persisted AI model', async () => {
  const { controller, requests, selectedAiModel, updateChecks } = createController({
    responses: [
      {
        miniprogram_forum_capture_enabled: true,
        available_whisper_models: ['small'],
        deepseek_model_option: 'server-option',
        available_ai_models: [{ value: 'server-option', label: 'Server' }],
      },
      { auto_download_bilibili_video: true, douyin_video_quality: 'high' },
    ],
  })

  await controller.loadDesktopBootstrapSettings({ hasLocalAiSettings: true })

  assert.deepEqual(requests, [
    'http://api.test/config',
    'http://api.test/video-download-settings',
  ])
  assert.deepEqual(updateChecks, ['checked'])
  assert.equal(selectedAiModel.value, 'local-model')
  assert.equal(controller.miniprogramForumCaptureEnabled.value, true)
  assert.deepEqual(controller.availableModels.value, ['small'])
  assert.deepEqual(controller.availableAiModels.value, [{ value: 'server-option', label: 'Server' }])
  assert.equal(controller.autoDownloadBilibiliVideo.value, true)
  assert.equal(controller.douyinVideoQuality.value, 'high')
})

test('normalizes a legacy backend model and rejects an unsupported video quality', async () => {
  const { controller, selectedAiModel } = createController({
    selectedModel: 'default-model',
    responses: [
      { deepseek_model: 'legacy-model' },
      { auto_download_bilibili_video: false, douyin_video_quality: 'ultra' },
    ],
  })

  await controller.loadDesktopBootstrapSettings()

  assert.equal(selectedAiModel.value, 'normalized:legacy-model')
  assert.deepEqual(controller.availableAiModels.value, ['normalized:legacy-model'])
  assert.equal(controller.autoDownloadBilibiliVideo.value, false)
  assert.equal(controller.douyinVideoQuality.value, 'standard')
})

test('a config failure keeps defaults and skips dependent startup reads', async () => {
  const { controller, requests, selectedAiModel, updateChecks } = createController({
    responses: [new Error('offline')],
  })

  await controller.loadDesktopBootstrapSettings()

  assert.deepEqual(requests, ['http://api.test/config'])
  assert.deepEqual(updateChecks, [])
  assert.equal(selectedAiModel.value, 'local-model')
  assert.deepEqual(controller.availableModels.value, ['tiny', 'base', 'small'])
  assert.equal(controller.miniprogramForumCaptureEnabled.value, false)
  assert.equal(controller.autoDownloadBilibiliVideo.value, false)
  assert.equal(controller.douyinVideoQuality.value, 'standard')
})

test('a later video-settings failure preserves the already loaded config', async () => {
  const { controller, requests, updateChecks } = createController({
    responses: [
      { miniprogram_forum_capture_enabled: true, available_whisper_models: ['base'] },
      new Error('video settings unavailable'),
    ],
  })

  await controller.loadDesktopBootstrapSettings()

  assert.equal(controller.miniprogramForumCaptureEnabled.value, true)
  assert.deepEqual(controller.availableModels.value, ['base'])
  assert.deepEqual(requests, [
    'http://api.test/config',
    'http://api.test/video-download-settings',
  ])
  assert.deepEqual(updateChecks, ['checked'])
  assert.equal(controller.autoDownloadBilibiliVideo.value, false)
  assert.equal(controller.douyinVideoQuality.value, 'standard')
})
