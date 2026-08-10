import axios from 'axios'
import { ref } from 'vue'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useDesktopBootstrapSettingsController({
  selectedAiModel,
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
    try {
      const configResponse = await request.get(`${apiBase}/config`)
      const config = configResponse.data || {}
      miniprogramForumCaptureEnabled.value = Boolean(config.miniprogram_forum_capture_enabled)
      if (Array.isArray(config.available_whisper_models)) {
        availableModels.value = config.available_whisper_models
      }
      if (!hasLocalAiSettings && config.deepseek_model_option) {
        selectedAiModel.value = config.deepseek_model_option
      } else if (!hasLocalAiSettings && config.deepseek_model) {
        selectedAiModel.value = normalizeAiModelValue(config.deepseek_model)
      }
      if (Array.isArray(config.available_ai_models)) {
        availableAiModels.value = config.available_ai_models
      } else if (config.deepseek_model) {
        availableAiModels.value = [normalizeAiModelValue(config.deepseek_model)]
      }

      void checkManualUpdate()
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
