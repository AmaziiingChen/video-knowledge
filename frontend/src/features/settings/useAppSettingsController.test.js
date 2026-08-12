import assert from 'node:assert/strict'
import test from 'node:test'

import { nextTick } from 'vue'

import { useAppSettingsController } from './useAppSettingsController.js'

const ASR_SETTINGS_KEY = 'video-knowledge.asr-settings.v1'
const AI_SETTINGS_KEY = 'video-knowledge.ai-settings.v1'
const ASSISTANT_SETTINGS_KEY = 'video-knowledge.assistant-settings.v1'
const APPEARANCE_SETTINGS_KEY = 'video-knowledge.appearance-settings.v1'

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

function installDocument() {
  const themeColor = { content: '' }
  globalThis.document = {
    documentElement: { dataset: { readingTheme: 'temporary' } },
    querySelector: (selector) => (
      selector === 'meta[name="theme-color"]'
        ? { setAttribute: (_name, value) => { themeColor.content = value } }
        : null
    ),
  }
  return themeColor
}

test('uses 简记 for a fresh profile without persisting an implicit preference', () => {
  const priorStorage = globalThis.localStorage
  const priorDocument = globalThis.document
  const storage = createStorage()
  globalThis.localStorage = storage
  const themeColor = installDocument()

  try {
    const controller = useAppSettingsController()
    const restored = controller.restoreSettings()

    assert.deepEqual(restored, { hasLocalAiSettings: false })
    assert.equal(controller.selectedTheme.value, 'notion')
    assert.equal(globalThis.document.documentElement.dataset.theme, 'notion')
    assert.equal(themeColor.content, '#FFFFFF')
    assert.equal(storage.getItem(APPEARANCE_SETTINGS_KEY), null)
  } finally {
    globalThis.localStorage = priorStorage
    globalThis.document = priorDocument
  }
})

test('restores legacy settings in the original order while keeping ASR fixed to desktop policy', async () => {
  const priorStorage = globalThis.localStorage
  const priorDocument = globalThis.document
  const storage = createStorage({
    [ASR_SETTINGS_KEY]: JSON.stringify({ asr_backend: 'mlx' }),
    [AI_SETTINGS_KEY]: JSON.stringify({ ai_model: 'deepseek-chat' }),
    [ASSISTANT_SETTINGS_KEY]: JSON.stringify({ auto_qa_shortcut_recognition: false }),
    [APPEARANCE_SETTINGS_KEY]: JSON.stringify({ theme: 'everforest' }),
  })
  globalThis.localStorage = storage
  const themeColor = installDocument()

  try {
    const controller = useAppSettingsController()
    controller.startSettingsPersistence()
    const restored = controller.restoreSettings()

    assert.deepEqual(restored, { hasLocalAiSettings: true })
    assert.equal(storage.getItem(ASR_SETTINGS_KEY), null)
    assert.deepEqual(controller.asrRequestOptions(), {
      whisper_model: 'small',
      asr_backend: 'auto',
      asr_model_strategy: 'manual',
      asr_short_video_model: 'base',
      asr_long_video_model: 'small',
      asr_beam_size: 1,
      asr_vad_filter: true,
      asr_fallback_enabled: false,
    })
    assert.equal(controller.selectedAiModel.value, 'deepseek-v4-flash:enabled')
    assert.equal(controller.autoQaShortcutRecognition.value, false)
    assert.equal(controller.selectedTheme.value, 'paper')
    assert.equal(globalThis.document.documentElement.dataset.theme, 'paper')
    assert.equal(globalThis.document.documentElement.dataset.readingTheme, undefined)
    assert.equal(themeColor.content, '#FDF6E3')

    await nextTick()
    assert.equal(controller.assistantAiModel.value, 'deepseek-v4-flash:enabled')
  } finally {
    globalThis.localStorage = priorStorage
    globalThis.document = priorDocument
  }
})

test('persists changed AI, assistant, and appearance preferences without altering request shapes', async () => {
  const priorStorage = globalThis.localStorage
  const priorDocument = globalThis.document
  const storage = createStorage()
  globalThis.localStorage = storage
  const themeColor = installDocument()

  try {
    const controller = useAppSettingsController()
    controller.startSettingsPersistence()
    controller.selectedAiModel.value = 'deepseek-v4-pro:enabled'
    controller.autoQaShortcutRecognition.value = false
    controller.selectedTheme.value = 'night'
    await nextTick()

    assert.deepEqual(controller.aiRequestOptions(), { ai_model: 'deepseek-v4-pro:enabled' })
    assert.deepEqual(controller.appearanceRequestOptions(), { theme: 'night' })
    assert.equal(controller.assistantAiModel.value, 'deepseek-v4-pro:enabled')
    assert.equal(storage.getItem(AI_SETTINGS_KEY), JSON.stringify({ ai_model: 'deepseek-v4-pro:enabled' }))
    assert.equal(storage.getItem(ASSISTANT_SETTINGS_KEY), JSON.stringify({ auto_qa_shortcut_recognition: false }))
    assert.equal(storage.getItem(APPEARANCE_SETTINGS_KEY), JSON.stringify({ theme: 'night' }))
    assert.equal(globalThis.document.documentElement.dataset.theme, 'night')
    assert.equal(themeColor.content, '#1D211C')
  } finally {
    globalThis.localStorage = priorStorage
    globalThis.document = priorDocument
  }
})

test('preserves opaque provider selections without storing credentials', async () => {
  const priorStorage = globalThis.localStorage
  const priorDocument = globalThis.document
  const selection = 'qwen::qwen3.7-plus:enabled'
  const storage = createStorage({ [AI_SETTINGS_KEY]: JSON.stringify({ ai_model: selection }) })
  globalThis.localStorage = storage
  installDocument()
  try {
    const controller = useAppSettingsController()
    controller.startSettingsPersistence()
    assert.deepEqual(controller.restoreSettings(), { hasLocalAiSettings: true })
    assert.equal(controller.selectedAiModel.value, selection)
    await nextTick()
    assert.equal(storage.getItem(AI_SETTINGS_KEY), JSON.stringify({ ai_model: selection }))
    assert.equal(storage.getItem('text-provider-api-key'), null)
  } finally {
    globalThis.localStorage = priorStorage
    globalThis.document = priorDocument
  }
})
