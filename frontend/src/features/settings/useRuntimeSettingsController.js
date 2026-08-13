import { onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const RUNTIME_COMPONENTS_API = `${API}/runtime-components`
const LLM_SETTINGS_API = `${API}/llm-settings`
const DEEPSEEK_SETTINGS_API = `${LLM_SETTINGS_API}/deepseek`
const CAMPUS_EMBEDDING_SETTINGS_API = `${LLM_SETTINGS_API}/campus-embedding`
const PADDLE_OCR_SETTINGS_API = `${API}/paddle-ocr-settings`
const MANUAL_COLLECTION_SETTINGS_API = `${API}/manual-collection/settings`
const MEDIA_TOOLS_API = `${API}/media-tools`

function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.message || fallback
}

export function useRuntimeSettingsController({
  formatBytes,
  loadAiTokenUsageSummary,
  requestDestructiveConfirmation,
  notify = ElMessage,
}) {
  const mediaTools = ref({})
  const ffmpegPath = ref('')
  const ytDlpPath = ref('')
  const savingMediaTools = ref(false)
  const runtimeComponents = ref({ browser: {}, models: [] })
  const loadingRuntimeComponents = ref(false)
  let runtimeComponentsPollTimer = null

  const deepseekApiKey = ref('')
  const deepseekBaseUrl = ref('https://api.deepseek.com')
  const deepseekPricing = ref({
    'deepseek-v4-flash': { input_cache_hit: 0.02, input_cache_miss: 1, output: 2 },
    'deepseek-v4-pro': { input_cache_hit: 0.025, input_cache_miss: 3, output: 6 }
  })
  const deepseekPeakPricingMultiplier = ref(1)
  const deepseekConfigured = ref(false)
  const savingDeepSeekSettings = ref(false)
  const testingDeepSeekConnection = ref(false)

  const embeddingApiKey = ref('')
  const embeddingBaseUrl = ref('https://dashscope.aliyuncs.com/compatible-mode/v1')
  const embeddingModel = ref('qwen3.7-text-embedding')
  const embeddingConfigured = ref(false)
  const savingEmbeddingSettings = ref(false)
  const testingEmbeddingConnection = ref(false)

  const paddleOcrAccessToken = ref('')
  const paddleOcrConfigured = ref(false)
  const paddleOcrBaseUrl = ref('https://paddleocr.aistudio-app.com/api/v2/ocr/jobs')
  const paddleOcrModel = ref('PaddleOCR-VL-1.6')
  const savingPaddleOcrSettings = ref(false)
  const manualAutoSummarize = ref(true)

  async function loadManualCollectionSettings() {
    const response = await axios.get(MANUAL_COLLECTION_SETTINGS_API, { timeout: 10000 })
    manualAutoSummarize.value = response.data?.auto_summarize !== false
  }

  async function saveManualCollectionSettings() {
    try {
      await axios.put(
        MANUAL_COLLECTION_SETTINGS_API,
        { auto_summarize: manualAutoSummarize.value },
        { timeout: 10000 }
      )
      notify.success(
        manualAutoSummarize.value
          ? '主动收藏将自动生成 AI 总结'
          : '主动收藏将仅抓取正文，不自动总结'
      )
    } catch (error) {
      notify.error(apiErrorMessage(error, '主动收藏设置保存失败'))
      await loadManualCollectionSettings().catch(() => null)
    }
  }

  async function loadDeepSeekSettings() {
    const response = await axios.get(LLM_SETTINGS_API, { timeout: 10000 })
    deepseekConfigured.value = Boolean(response.data?.deepseek_configured)
    deepseekBaseUrl.value = response.data?.deepseek_base_url || 'https://api.deepseek.com'
    if (response.data?.deepseek_pricing && typeof response.data.deepseek_pricing === 'object') {
      deepseekPricing.value = response.data.deepseek_pricing
    }
    deepseekPeakPricingMultiplier.value = Number(response.data?.deepseek_peak_pricing_multiplier ?? 1)
    deepseekApiKey.value = ''
    embeddingConfigured.value = Boolean(response.data?.campus_embedding_configured)
    embeddingBaseUrl.value = response.data?.campus_embedding_api_base_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    embeddingModel.value = response.data?.campus_embedding_api_model || 'qwen3.7-text-embedding'
    embeddingApiKey.value = ''
  }

  async function saveDeepSeekSettings() {
    savingDeepSeekSettings.value = true
    try {
      // The generic provider editor may have changed this URL after the legacy
      // pricing form was opened. Re-read the canonical profile so saving local
      // cost estimates cannot overwrite a newer provider endpoint.
      const canonical = await axios.get(LLM_SETTINGS_API, { timeout: 10000 })
      const canonicalBaseUrl = String(canonical.data?.deepseek_base_url || deepseekBaseUrl.value).trim()
      deepseekBaseUrl.value = canonicalBaseUrl
      const response = await axios.put(DEEPSEEK_SETTINGS_API, {
        deepseek_api_key: deepseekApiKey.value.trim() || undefined,
        deepseek_base_url: canonicalBaseUrl,
        deepseek_pricing: deepseekPricing.value,
        deepseek_peak_pricing_multiplier: deepseekPeakPricingMultiplier.value
      }, { timeout: 10000 })
      deepseekConfigured.value = Boolean(response.data?.deepseek_configured)
      if (response.data?.deepseek_pricing && typeof response.data.deepseek_pricing === 'object') {
        deepseekPricing.value = response.data.deepseek_pricing
      }
      deepseekPeakPricingMultiplier.value = Number(response.data?.deepseek_peak_pricing_multiplier ?? 1)
      deepseekApiKey.value = ''
      void loadAiTokenUsageSummary()
      notify.success('DeepSeek 配置已保存')
    } catch (error) {
      notify.error(apiErrorMessage(error, 'DeepSeek 配置保存失败'))
    } finally {
      savingDeepSeekSettings.value = false
    }
  }

  async function testDeepSeekConnection() {
    testingDeepSeekConnection.value = true
    try {
      const response = await axios.post(`${DEEPSEEK_SETTINGS_API}/test`, {
        deepseek_api_key: deepseekApiKey.value.trim() || undefined,
        deepseek_base_url: deepseekBaseUrl.value.trim() || undefined
      }, { timeout: 30000 })
      const elapsed = Number(response.data?.elapsed_ms || 0)
      notify.success(`DeepSeek 连接成功${elapsed ? ` · ${elapsed} ms` : ''}`)
    } catch (error) {
      notify.error(apiErrorMessage(error, 'DeepSeek 连接失败'))
    } finally {
      testingDeepSeekConnection.value = false
    }
  }

  async function saveEmbeddingSettings() {
    savingEmbeddingSettings.value = true
    try {
      const response = await axios.put(CAMPUS_EMBEDDING_SETTINGS_API, {
        campus_embedding_api_key: embeddingApiKey.value.trim() || undefined,
        campus_embedding_api_base_url: embeddingBaseUrl.value.trim(),
        campus_embedding_api_model: embeddingModel.value.trim()
      }, { timeout: 10000 })
      embeddingConfigured.value = Boolean(response.data?.campus_embedding_configured)
      embeddingBaseUrl.value = response.data?.campus_embedding_api_base_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'
      embeddingModel.value = response.data?.campus_embedding_api_model || 'qwen3.7-text-embedding'
      embeddingApiKey.value = ''
      notify.success('Embedding 配置已保存')
    } catch (error) {
      notify.error(apiErrorMessage(error, 'Embedding 配置保存失败'))
    } finally {
      savingEmbeddingSettings.value = false
    }
  }

  async function testEmbeddingConnection() {
    testingEmbeddingConnection.value = true
    try {
      const response = await axios.post(`${CAMPUS_EMBEDDING_SETTINGS_API}/test`, {
        campus_embedding_api_key: embeddingApiKey.value.trim() || undefined,
        campus_embedding_api_base_url: embeddingBaseUrl.value.trim() || undefined,
        campus_embedding_api_model: embeddingModel.value.trim() || undefined
      }, { timeout: 30000 })
      const elapsed = Number(response.data?.elapsed_ms || 0)
      const dimensions = Number(response.data?.dimensions || 0)
      notify.success(
        `Embedding 连接成功${dimensions ? ` · ${dimensions} 维` : ''}${elapsed ? ` · ${elapsed} ms` : ''}`
      )
    } catch (error) {
      notify.error(apiErrorMessage(error, 'Embedding 连接失败'))
    } finally {
      testingEmbeddingConnection.value = false
    }
  }

  async function loadPaddleOcrSettings() {
    const response = await axios.get(PADDLE_OCR_SETTINGS_API, { timeout: 10000 })
    paddleOcrConfigured.value = Boolean(response.data?.configured)
    paddleOcrBaseUrl.value = response.data?.base_url || 'https://paddleocr.aistudio-app.com/api/v2/ocr/jobs'
    paddleOcrModel.value = response.data?.model || 'PaddleOCR-VL-1.6'
    paddleOcrAccessToken.value = ''
  }

  async function savePaddleOcrSettings() {
    savingPaddleOcrSettings.value = true
    try {
      const response = await axios.put(PADDLE_OCR_SETTINGS_API, {
        access_token: paddleOcrAccessToken.value.trim() || undefined,
        base_url: paddleOcrBaseUrl.value.trim() || undefined,
        model: paddleOcrModel.value.trim() || undefined
      }, { timeout: 10000 })
      paddleOcrConfigured.value = Boolean(response.data?.configured)
      paddleOcrBaseUrl.value = response.data?.base_url || 'https://paddleocr.aistudio-app.com/api/v2/ocr/jobs'
      paddleOcrModel.value = response.data?.model || 'PaddleOCR-VL-1.6'
      paddleOcrAccessToken.value = ''
      notify.success('PaddleOCR 配置已保存')
    } catch (error) {
      notify.error(apiErrorMessage(error, 'PaddleOCR 配置保存失败'))
    } finally {
      savingPaddleOcrSettings.value = false
    }
  }

  async function loadMediaTools() {
    const response = await axios.get(MEDIA_TOOLS_API, { timeout: 10000 })
    mediaTools.value = response.data || {}
    ffmpegPath.value = mediaTools.value.ffmpeg_path?.configured_path || ''
    ytDlpPath.value = mediaTools.value.yt_dlp_path?.configured_path || ''
  }

  async function saveMediaTools() {
    savingMediaTools.value = true
    try {
      const response = await axios.put(MEDIA_TOOLS_API, {
        ffmpeg_path: ffmpegPath.value.trim(),
        yt_dlp_path: ytDlpPath.value.trim()
      }, { timeout: 10000 })
      mediaTools.value = response.data || {}
      notify.success('媒体工具路径已保存并检测')
    } catch (error) {
      notify.error(apiErrorMessage(error, '媒体工具路径不可用'))
    } finally {
      savingMediaTools.value = false
    }
  }

  async function chooseMediaTool(toolName) {
    const executable = await window.knowledgeHubDesktop?.chooseExecutable?.(toolName)
    if (!executable) return
    if (toolName === 'ffmpeg') ffmpegPath.value = executable
    if (toolName === 'yt-dlp') ytDlpPath.value = executable
  }

  function scheduleRuntimeComponentsPoll() {
    if (runtimeComponentsPollTimer) clearTimeout(runtimeComponentsPollTimer)
    const browserDownloading = runtimeComponents.value.browser?.state === 'downloading'
    const modelDownloading = (runtimeComponents.value.models || []).some((item) => item.state === 'downloading')
    if (!browserDownloading && !modelDownloading) return
    runtimeComponentsPollTimer = setTimeout(() => loadRuntimeComponents({ silent: true }), 1200)
  }

  async function loadRuntimeComponents({ silent = false } = {}) {
    if (!silent) loadingRuntimeComponents.value = true
    try {
      const response = await axios.get(RUNTIME_COMPONENTS_API, { timeout: 15000 })
      runtimeComponents.value = response.data || { browser: {}, models: [] }
      scheduleRuntimeComponentsPoll()
    } catch (error) {
      if (!silent) notify.error(apiErrorMessage(error, '无法检查设备准备情况'))
    } finally {
      if (!silent) loadingRuntimeComponents.value = false
    }
  }

  async function installRuntimeBrowser() {
    try {
      const response = await axios.post(`${RUNTIME_COMPONENTS_API}/browser/install`, {}, { timeout: 15000 })
      runtimeComponents.value = { ...runtimeComponents.value, browser: response.data || {} }
      scheduleRuntimeComponentsPoll()
    } catch (error) {
      notify.error(apiErrorMessage(error, '浏览器组件下载未能启动'))
    }
  }

  async function downloadAsrModel(model) {
    try {
      await axios.post(
        `${RUNTIME_COMPONENTS_API}/models/download`,
        { model: model.model, backend: model.backend },
        { timeout: 15000 }
      )
      await loadRuntimeComponents({ silent: true })
    } catch (error) {
      notify.error(apiErrorMessage(error, '语音识别模型下载未能启动'))
    }
  }

  async function deleteAsrModel(model) {
    const label = `${model.model} · ${model.backend === 'mlx' ? 'MLX' : 'Faster-Whisper'}`
    const confirmed = await requestDestructiveConfirmation({
      title: '移除本机模型',
      message: `将移除本机模型“${label}”（约 ${formatBytes(model.installed_bytes || model.estimated_bytes)}）。已保存的转写和总结不会受影响；以后可重新下载。`,
      confirmLabel: '移除'
    })
    if (!confirmed) return
    try {
      await axios.delete(`${RUNTIME_COMPONENTS_API}/models`, {
        data: { model: model.model, backend: model.backend },
        timeout: 15000
      })
      await loadRuntimeComponents({ silent: true })
      notify.success('本机模型已移除')
    } catch (error) {
      notify.error(apiErrorMessage(error, '移除本机模型失败'))
    }
  }

  onBeforeUnmount(() => {
    if (runtimeComponentsPollTimer) clearTimeout(runtimeComponentsPollTimer)
  })

  return {
    mediaTools,
    ffmpegPath,
    ytDlpPath,
    savingMediaTools,
    runtimeComponents,
    loadingRuntimeComponents,
    deepseekApiKey,
    deepseekBaseUrl,
    deepseekPricing,
    deepseekPeakPricingMultiplier,
    deepseekConfigured,
    savingDeepSeekSettings,
    testingDeepSeekConnection,
    embeddingApiKey,
    embeddingBaseUrl,
    embeddingModel,
    embeddingConfigured,
    savingEmbeddingSettings,
    testingEmbeddingConnection,
    paddleOcrAccessToken,
    paddleOcrConfigured,
    paddleOcrBaseUrl,
    paddleOcrModel,
    savingPaddleOcrSettings,
    manualAutoSummarize,
    loadManualCollectionSettings,
    saveManualCollectionSettings,
    loadDeepSeekSettings,
    saveDeepSeekSettings,
    testDeepSeekConnection,
    saveEmbeddingSettings,
    testEmbeddingConnection,
    loadPaddleOcrSettings,
    savePaddleOcrSettings,
    loadMediaTools,
    saveMediaTools,
    chooseMediaTool,
    loadRuntimeComponents,
    installRuntimeBrowser,
    downloadAsrModel,
    deleteAsrModel
  }
}
