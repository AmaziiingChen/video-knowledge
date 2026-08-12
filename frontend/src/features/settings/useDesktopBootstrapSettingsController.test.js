import assert from 'node:assert/strict'
import test from 'node:test'

import { ref } from 'vue'

import { useDesktopBootstrapSettingsController } from './useDesktopBootstrapSettingsController.js'

function createController({ responses = [], selectedModel = 'local-model', assistantModel = selectedModel } = {}) {
  const requests = []
  const updateChecks = []
  const selectedAiModel = ref(selectedModel)
  const assistantAiModel = ref(assistantModel)
  const controller = useDesktopBootstrapSettingsController({
    selectedAiModel,
    assistantAiModel,
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
  return { controller, requests, selectedAiModel, assistantAiModel, updateChecks }
}

test('loads current backend choices without replacing a locally persisted AI model', async () => {
  const { controller, requests, selectedAiModel, updateChecks } = createController({
    responses: [
      {
        miniprogram_forum_capture_enabled: true,
        available_whisper_models: ['small'],
        deepseek_model_option: 'server-option',
        available_ai_models: [{ value: 'local-model', label: 'Local' }, { value: 'server-option', label: 'Server' }],
      },
      { providers: [{ id: 'deepseek', label: 'DeepSeek', configured: true, enabled: true }] },
      { auto_download_bilibili_video: true, douyin_video_quality: 'high' },
    ],
  })

  await controller.loadDesktopBootstrapSettings({ hasLocalAiSettings: true })

  assert.deepEqual(requests, [
    'http://api.test/config',
    'http://api.test/llm-settings/text-providers',
    'http://api.test/video-download-settings',
  ])
  assert.deepEqual(updateChecks, ['checked'])
  assert.equal(selectedAiModel.value, 'local-model')
  assert.equal(controller.miniprogramForumCaptureEnabled.value, true)
  assert.deepEqual(controller.availableModels.value, ['small'])
  assert.deepEqual(controller.availableAiModels.value.map(({ value, disabled }) => ({ value, disabled })), [
    { value: 'local-model', disabled: false },
    { value: 'server-option', disabled: false },
  ])
  assert.equal(controller.autoDownloadBilibiliVideo.value, true)
  assert.equal(controller.douyinVideoQuality.value, 'high')
})

test('normalizes a legacy backend model and rejects an unsupported video quality', async () => {
  const { controller, selectedAiModel } = createController({
    selectedModel: 'default-model',
    responses: [
      { deepseek_model: 'legacy-model' },
      { providers: [{ id: 'deepseek', label: 'DeepSeek', configured: true, enabled: true }] },
      { auto_download_bilibili_video: false, douyin_video_quality: 'ultra' },
    ],
  })

  await controller.loadDesktopBootstrapSettings()

  assert.equal(selectedAiModel.value, 'normalized:legacy-model')
  assert.deepEqual(controller.availableAiModels.value.map((option) => option.value), ['normalized:legacy-model'])
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
      { providers: [] },
      new Error('video settings unavailable'),
    ],
  })

  await controller.loadDesktopBootstrapSettings()

  assert.equal(controller.miniprogramForumCaptureEnabled.value, true)
  assert.deepEqual(controller.availableModels.value, ['base'])
  assert.deepEqual(requests, [
    'http://api.test/config',
    'http://api.test/llm-settings/text-providers',
    'http://api.test/video-download-settings',
  ])
  assert.deepEqual(updateChecks, ['checked'])
  assert.equal(controller.autoDownloadBilibiliVideo.value, false)
  assert.equal(controller.douyinVideoQuality.value, 'standard')
})

test('falls back from a stale local model and disables providers without credentials', async () => {
  const { controller, selectedAiModel } = createController({
    selectedModel: 'qwen::removed:enabled',
    responses: [
      {
        default_ai_model: 'deepseek-v4-flash:enabled',
        text_model_configured: true,
        available_ai_models: [
          { value: 'deepseek-v4-flash:enabled', provider: 'deepseek' },
          { value: 'qwen::qwen3.7-plus:enabled', provider: 'qwen' },
        ],
      },
      { providers: [
        { id: 'deepseek', label: 'DeepSeek', configured: true, enabled: true },
        { id: 'qwen', label: '千问', configured: false, enabled: true },
      ] },
      {},
    ],
  })

  await controller.loadDesktopBootstrapSettings({ hasLocalAiSettings: true })

  assert.equal(selectedAiModel.value, 'deepseek-v4-flash:enabled')
  assert.equal(controller.availableAiModels.value[0].disabled, false)
  assert.equal(controller.availableAiModels.value[1].disabled, true)
})

test('keeps an unconfigured server default instead of inventing a frontend-only default', async () => {
  const { controller, selectedAiModel } = createController({
    selectedModel: 'stale::removed:enabled',
    responses: [
      {
        default_ai_model: 'qwen::qwen3.7-plus:enabled',
        text_model_configured: false,
        available_ai_models: [
          { value: 'deepseek-v4-flash:enabled', provider: 'deepseek' },
          { value: 'qwen::qwen3.7-plus:enabled', provider: 'qwen' },
        ],
      },
      { providers: [
        { id: 'deepseek', label: 'DeepSeek', configured: true, enabled: true },
        { id: 'qwen', label: '千问', configured: false, enabled: true },
      ] },
      {},
    ],
  })

  await controller.loadDesktopBootstrapSettings({ hasLocalAiSettings: true })

  assert.equal(selectedAiModel.value, 'qwen::qwen3.7-plus:enabled')
  assert.equal(controller.availableAiModels.value[0].disabled, false)
  assert.equal(controller.availableAiModels.value[1].disabled, true)
})

test('reconciles only an unavailable assistant model to the enabled global default', async () => {
  const { controller, selectedAiModel, assistantAiModel } = createController({
    selectedModel: 'deepseek-v4-flash:enabled',
    assistantModel: 'qwen::removed:enabled',
    responses: [
      {
        default_ai_model: 'deepseek-v4-flash:enabled',
        text_model_configured: true,
        available_ai_models: [
          { value: 'deepseek-v4-flash:enabled', provider: 'deepseek' },
          { value: 'qwen::qwen3.7-plus:enabled', provider: 'qwen' },
        ],
      },
      { providers: [
        { id: 'deepseek', label: 'DeepSeek', configured: true, enabled: true },
        { id: 'qwen', label: '千问', configured: false, enabled: true },
      ] },
      {},
    ],
  })

  await controller.loadDesktopBootstrapSettings({ hasLocalAiSettings: true })

  assert.equal(selectedAiModel.value, 'deepseek-v4-flash:enabled')
  assert.equal(assistantAiModel.value, 'deepseek-v4-flash:enabled')
})
