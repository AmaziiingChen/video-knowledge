import { computed, ref, watch } from 'vue'

import {
  appearanceThemes,
  DEFAULT_APPEARANCE_THEME,
  DESKTOP_ASR_POLICY,
  normalizeAppearanceTheme,
} from '../../config/desktopPresentation.js'

const ASR_SETTINGS_KEY = 'video-knowledge.asr-settings.v1'
const AI_SETTINGS_KEY = 'video-knowledge.ai-settings.v1'
const ASSISTANT_SETTINGS_KEY = 'video-knowledge.assistant-settings.v1'
const APPEARANCE_SETTINGS_KEY = 'video-knowledge.appearance-settings.v1'

function normalizeAiModelValue(model) {
  if (model === 'deepseek-chat' || model === 'deepseek-reasoner') {
    return 'deepseek-v4-flash:enabled'
  }
  if (model === 'deepseek-v4-flash' || model === 'deepseek-v4-pro') {
    return `${model}:enabled`
  }
  return model || 'deepseek-v4-flash:enabled'
}

export function useAppSettingsController() {
  // The global selection is used for ingestion and all background work.
  // The reading-side assistant starts from it but may be changed temporarily
  // without unexpectedly making later batch jobs use a more expensive model.
  const selectedAiModel = ref('deepseek-v4-flash:enabled')
  const assistantAiModel = ref(selectedAiModel.value)
  const autoQaShortcutRecognition = ref(true)
  const selectedTheme = ref(DEFAULT_APPEARANCE_THEME)
  const themeOptions = appearanceThemes
  const selectedThemeOption = computed(() => {
    return themeOptions.find((item) => item.value === selectedTheme.value) || themeOptions[0]
  })

  const asrRequestOptions = () => ({ ...DESKTOP_ASR_POLICY })
  const aiRequestOptions = () => ({ ai_model: selectedAiModel.value })
  const appearanceRequestOptions = () => ({ theme: selectedTheme.value })

  function persistAiSettings() {
    try {
      localStorage.setItem(AI_SETTINGS_KEY, JSON.stringify(aiRequestOptions()))
    } catch {
      // 本地存储失败不影响处理流程。
    }
  }

  function persistAssistantSettings() {
    try {
      localStorage.setItem(ASSISTANT_SETTINGS_KEY, JSON.stringify({
        auto_qa_shortcut_recognition: Boolean(autoQaShortcutRecognition.value),
      }))
    } catch {
      // 本地存储失败不影响追问功能。
    }
  }

  function applyTheme() {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.theme = selectedThemeOption.value.value
    delete document.documentElement.dataset.readingTheme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', selectedThemeOption.value.background)
  }

  function persistAppearanceSettings() {
    applyTheme()
    try {
      localStorage.setItem(APPEARANCE_SETTINGS_KEY, JSON.stringify(appearanceRequestOptions()))
    } catch {
      // 本地存储失败不影响界面切换。
    }
  }

  function startSettingsPersistence() {
    watch(selectedAiModel, (model) => {
      assistantAiModel.value = model
      persistAiSettings()
    })
    watch(autoQaShortcutRecognition, persistAssistantSettings)
    watch(selectedTheme, persistAppearanceSettings)
  }

  function restoreAsrSettings() {
    try {
      // v1 exposed ASR tuning. New tasks are fixed to the desktop policy, so
      // discard that local preset instead of silently carrying it forward.
      localStorage.removeItem(ASR_SETTINGS_KEY)
    } catch {
      // Storage availability does not affect the fixed ASR policy.
    }
  }

  function restoreAiSettings() {
    try {
      const raw = localStorage.getItem(AI_SETTINGS_KEY)
      if (!raw) return false
      const data = JSON.parse(raw)
      selectedAiModel.value = normalizeAiModelValue(data.ai_model)
      return true
    } catch {
      return false
    }
  }

  function restoreAssistantSettings() {
    try {
      const raw = localStorage.getItem(ASSISTANT_SETTINGS_KEY)
      if (!raw) return false
      const data = JSON.parse(raw)
      autoQaShortcutRecognition.value = Boolean(data.auto_qa_shortcut_recognition ?? true)
      return true
    } catch {
      return false
    }
  }

  function restoreAppearanceSettings() {
    try {
      const raw = localStorage.getItem(APPEARANCE_SETTINGS_KEY)
      if (!raw) {
        applyTheme()
        return false
      }
      const data = JSON.parse(raw)
      selectedTheme.value = normalizeAppearanceTheme(data.theme)
      applyTheme()
      return true
    } catch {
      applyTheme()
      return false
    }
  }

  function restoreSettings() {
    restoreAsrSettings()
    const hasLocalAiSettings = restoreAiSettings()
    restoreAssistantSettings()
    restoreAppearanceSettings()
    return { hasLocalAiSettings }
  }

  return {
    selectedAiModel,
    assistantAiModel,
    autoQaShortcutRecognition,
    selectedTheme,
    themeOptions,
    selectedThemeOption,
    asrRequestOptions,
    aiRequestOptions,
    appearanceRequestOptions,
    normalizeAiModelValue,
    startSettingsPersistence,
    restoreSettings,
  }
}
