import assert from 'node:assert/strict'
import test from 'node:test'

import { useTextModelProviderSettingsController } from './useTextModelProviderSettingsController.js'

function createHarness({ selected = 'missing::model:enabled', getResponses = [] } = {}) {
  const calls = []
  const options = []
  const defaults = []
  const messages = []
  const request = {
    get: async (url) => {
      calls.push(['get', url])
      const value = getResponses.shift()
      if (value instanceof Error) throw value
      return { data: value || {} }
    },
    put: async (url, body) => { calls.push(['put', url, body]); return { data: {} } },
    post: async (url, body) => { calls.push(['post', url, body]); return { data: { elapsed_ms: 12 } } },
    delete: async (url) => { calls.push(['delete', url]); return { data: {} } },
  }
  const controller = useTextModelProviderSettingsController({
    request,
    apiBase: 'http://api.test',
    notify: {
      success: (message) => messages.push(['success', message]),
      warning: (message) => messages.push(['warning', message]),
      error: (message) => messages.push(['error', message]),
    },
    confirmDelete: async () => true,
    onOptionsChanged: (value) => options.push(value),
    onDefaultChanged: (value) => defaults.push(value),
    getSelectedModel: () => selected,
  })
  return { controller, request, calls, options, defaults, messages }
}

const providerPayload = {
  providers: [
    { id: 'deepseek', type: 'deepseek', label: 'DeepSeek', enabled: true, configured: true, models: ['deepseek-v4-flash'] },
    { id: 'qwen', type: 'qwen', label: '千问', enabled: true, configured: false, models: ['qwen3.7-plus'] },
  ],
  model_options: [
    { provider: 'deepseek', value: 'deepseek-v4-flash:enabled', label: 'Flash' },
    { provider: 'qwen', value: 'qwen::qwen3.7-plus:enabled', label: 'Qwen Plus' },
  ],
}

test('loads provider availability and reconciles a stale selection to the server default', async () => {
  const { controller, options, defaults } = createHarness({
    getResponses: [providerPayload, { default_ai_model: 'deepseek-v4-flash:enabled' }],
  })
  assert.equal(await controller.loadProviders(), true)
  assert.equal(controller.modelOptions.value[0].disabled, false)
  assert.equal(controller.modelOptions.value[1].disabled, true)
  assert.equal(controller.modelOptions.value[1].provider_label, '千问')
  assert.equal(options.length, 1)
  assert.deepEqual(defaults, ['deepseek-v4-flash:enabled'])
})

test('keeps an unavailable backend default instead of silently selecting the first enabled model', async () => {
  const payload = {
    ...providerPayload,
    providers: providerPayload.providers.map((provider) => ({
      ...provider,
      configured: provider.id === 'qwen',
    })),
  }
  const { controller, defaults } = createHarness({
    getResponses: [payload, { default_ai_model: 'deepseek-v4-flash:enabled' }],
  })

  assert.equal(await controller.loadProviders(), true)
  assert.equal(controller.modelOptions.value[0].disabled, true)
  assert.equal(controller.modelOptions.value[1].disabled, false)
  assert.deepEqual(defaults, ['deepseek-v4-flash:enabled'])
})

test('saves a custom provider without persisting or replaying its transient key', async () => {
  const { controller, calls } = createHarness({
    selected: 'deepseek-v4-flash:enabled',
    getResponses: [providerPayload],
  })
  controller.openCreate()
  Object.assign(controller.draft, {
    id: 'local-gateway', label: '本机服务', base_url: 'http://127.0.0.1:11434/v1',
    models: ['model-a'], thinking_parameter: 'thinking', response_format: true, api_key: 'secret-value',
  })
  assert.equal(await controller.saveProvider(), true)
  const put = calls.find((call) => call[0] === 'put')
  assert.equal(put[2].api_key, 'secret-value')
  assert.equal(put[2].thinking_parameter, 'thinking')
  assert.equal(put[2].response_format, true)
  assert.equal(controller.draft.api_key, '')
  assert.equal(controller.editorOpen.value, false)

  controller.openEdit({ ...providerPayload.providers[0], base_url: 'https://api.deepseek.com' })
  assert.equal(controller.draft.api_key, '')
})

test('applies a common protocol preset but keeps the provider identity and models user-controlled', async () => {
  const { controller, calls } = createHarness({
    selected: 'deepseek-v4-flash:enabled',
    getResponses: [providerPayload],
  })
  controller.openCreate()
  Object.assign(controller.draft, { id: 'minimax', models: ['MiniMax-M2.5'] })
  controller.applyDialectPreset('minimax')

  assert.equal(controller.draft.id, 'minimax')
  assert.equal(controller.draft.label, 'MiniMax')
  assert.equal(controller.draft.base_url, 'https://api.minimaxi.com/v1')
  assert.equal(controller.draft.auth_scheme, 'bearer')
  assert.equal(controller.draft.thinking_parameter, 'reasoning_split')
  assert.deepEqual(controller.draft.models, ['MiniMax-M2.5'])

  assert.equal(await controller.saveProvider(), true)
  const put = calls.find((call) => call[0] === 'put')
  assert.equal(put[2].auth_scheme, 'bearer')
  assert.equal(put[2].thinking_parameter, 'reasoning_split')
})

test('serializes api-key authentication without retaining the transient key', async () => {
  const { controller, calls } = createHarness({ getResponses: [providerPayload] })
  controller.openCreate()
  Object.assign(controller.draft, {
    id: 'header-gateway', label: 'Header Gateway', base_url: 'https://gateway.example/v1',
    models: ['chat-model'], auth_scheme: 'api_key', api_key: 'transient-secret',
  })

  assert.equal(await controller.saveProvider(), true)
  const put = calls.find((call) => call[0] === 'put')
  assert.equal(put[2].auth_scheme, 'api_key')
  assert.equal(put[2].api_key, 'transient-secret')
  assert.equal(controller.draft.api_key, '')
})

test('updates the default only after the backend accepts it and keeps disabled custom providers undeletable', async () => {
  const { controller, request, defaults, calls } = createHarness()
  request.put = async () => { throw new Error('offline') }
  assert.equal(await controller.setDefaultModel('qwen::qwen3.7-plus:enabled'), false)
  assert.deepEqual(defaults, [])
  assert.equal(await controller.deleteProvider({ id: 'old', type: 'custom', enabled: false }), false)
  assert.equal(calls.some((call) => call[0] === 'delete'), false)
})
