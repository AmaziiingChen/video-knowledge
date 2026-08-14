import axios from 'axios'
import { ref } from 'vue'

import { API_BASE as API } from '../../utils/localApiAuth.js'

function selectionProvider(selection) {
  const withoutThinking = String(selection || '').replace(/:(?:enabled|disabled)$/u, '')
  return withoutThinking.includes('::') ? withoutThinking.split('::', 1)[0] : 'deepseek'
}

export function useDesktopBootstrapSettingsController({
  selectedAiModel,
  assistantAiModel,
  normalizeAiModelValue,
  checkManualUpdate,
  request = axios,
  apiBase = API,
}) {
  const availableModels = ref(['tiny', 'base', 'small'])
  const miniprogramForumCaptureEnabled = ref(false)
  const availableAiModels = ref([
    { value: 'deepseek-v4-flash:enabled', label: 'deepseek-v4-flash' },
    { value: 'deepseek-v4-pro:enabled', label: 'deepseek-v4-pro' },
  ])
  const autoDownloadBilibiliVideo = ref(false)
  const douyinVideoQuality = ref('standard')

  async function loadDesktopBootstrapSettings({ hasLocalAiSettings = false } = {}) {
    // Update discovery is independent of optional local settings.  A damaged
    // provider/profile configuration must not suppress an available release.
    void Promise.resolve(checkManualUpdate()).catch(() => {})
    try {
      const configResponse = await request.get(`${apiBase}/config`)
      const config = configResponse.data || {}
      miniprogramForumCaptureEnabled.value = Boolean(config.miniprogram_forum_capture_enabled)
      if (Array.isArray(config.available_whisper_models)) {
        availableModels.value = config.available_whisper_models
      }
      if (Array.isArray(config.available_ai_models)) {
        availableAiModels.value = config.available_ai_models
      } else if (config.deepseek_model) {
        availableAiModels.value = [normalizeAiModelValue(config.deepseek_model)]
      }
      const serverDefault = String(
        config.default_ai_model
        || config.deepseek_model_option
        || (config.deepseek_model ? normalizeAiModelValue(config.deepseek_model) : ''),
      )
      const providerResponse = await request.get(`${apiBase}/llm-settings/text-providers`).catch(() => ({ data: {} }))
      const providers = Array.isArray(providerResponse.data?.providers) ? providerResponse.data.providers : []
      const providerStates = Object.fromEntries(providers.map((provider) => [
        provider.id,
        { configured: provider.enabled !== false && provider.configured === true, label: provider.label },
      ]))
      const defaultProvider = selectionProvider(serverDefault)
      availableAiModels.value = availableAiModels.value.map((option) => {
        const source = typeof option === 'object' ? option : { value: option, label: option }
        const provider = String(source.provider || selectionProvider(source.value))
        const knownState = providerStates[provider]
        const configured = knownState
          ? knownState.configured
          : provider === defaultProvider && config.text_model_configured !== false
        return {
          ...source,
          provider,
          provider_label: source.provider_label || knownState?.label || provider,
          disabled: !configured,
        }
      })
      const optionValues = availableAiModels.value
        .filter((option) => option?.disabled !== true)
        .map((option) => String(option?.value || option || ''))
        .filter(Boolean)
      if (!hasLocalAiSettings || !optionValues.includes(selectedAiModel.value)) {
        selectedAiModel.value = serverDefault || optionValues[0] || selectedAiModel.value
      }
      if (assistantAiModel && !optionValues.includes(assistantAiModel.value)) {
        assistantAiModel.value = optionValues.includes(selectedAiModel.value)
          ? selectedAiModel.value
          : optionValues[0] || assistantAiModel.value
      }

      const videoResponse = await request.get(`${apiBase}/video-download-settings`)
      autoDownloadBilibiliVideo.value = Boolean(videoResponse.data?.auto_download_bilibili_video)
      douyinVideoQuality.value = ['low', 'standard', 'high'].includes(videoResponse.data?.douyin_video_quality)
        ? videoResponse.data.douyin_video_quality
        : 'standard'
    } catch {
      // Startup remains usable with defaults when optional configuration reads fail.
    }
  }

  return {
    availableModels,
    miniprogramForumCaptureEnabled,
    availableAiModels,
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    loadDesktopBootstrapSettings,
  }
}
