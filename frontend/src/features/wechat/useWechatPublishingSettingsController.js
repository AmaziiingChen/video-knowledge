import { ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const DEFAULT_COVER_ENDPOINT = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
const DEFAULT_COVER_MODEL = 'qwen-image-2.0'

export function useWechatPublishingSettingsController({
  apiBase = `${API}/wechat-publishing`,
  request = axios,
  notify = ElMessage,
  messageBox = ElMessageBox,
  openSettings = () => {},
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const wechatPublishingSettings = ref({ configured: false, display_name: '', app_id_masked: '', status: 'unconfigured', last_error: '' })
  const wechatPublishingDisplayName = ref('订阅号')
  const wechatPublishingAppId = ref('')
  const wechatPublishingAppSecret = ref('')
  const wechatPublicSiteBaseUrl = ref('')
  const savingWechatPublishingSettings = ref(false)
  const wechatQwenCoverSettings = ref({ configured: false, endpoint: '', model: DEFAULT_COVER_MODEL })
  const wechatQwenCoverApiKey = ref('')
  const wechatQwenCoverEndpoint = ref(DEFAULT_COVER_ENDPOINT)
  const wechatQwenCoverModel = ref(DEFAULT_COVER_MODEL)
  const savingWechatQwenCoverSettings = ref(false)
  const testingWechatQwenCoverConnection = ref(false)

  async function loadWechatPublishingSettings() {
    try {
      const response = await request.get(`${apiBase}/settings`, { timeout: 10000 })
      wechatPublishingSettings.value = response.data || { configured: false }
      wechatPublishingDisplayName.value = response.data?.display_name || '订阅号'
      wechatPublishingAppId.value = ''
      wechatPublishingAppSecret.value = ''
      wechatPublicSiteBaseUrl.value = response.data?.public_site_base_url || ''
    } catch (error) {
      notify.error(errorMessage(error, '无法读取公众号发布配置'))
    }
  }

  async function loadWechatQwenCoverSettings() {
    try {
      const response = await request.get(`${apiBase}/cover-settings`, { timeout: 10000 })
      wechatQwenCoverSettings.value = response.data || { configured: false }
      wechatQwenCoverEndpoint.value = response.data?.endpoint || DEFAULT_COVER_ENDPOINT
      wechatQwenCoverModel.value = response.data?.model || DEFAULT_COVER_MODEL
      wechatQwenCoverApiKey.value = ''
    } catch (error) {
      notify.error(errorMessage(error, '无法读取千问封面配置'))
    }
  }

  async function saveWechatPublishingSettings() {
    savingWechatPublishingSettings.value = true
    try {
      const response = await request.put(`${apiBase}/settings`, {
        display_name: wechatPublishingDisplayName.value.trim() || '订阅号',
        app_id: wechatPublishingAppId.value.trim(),
        app_secret: wechatPublishingAppSecret.value.trim(),
        public_site_base_url: wechatPublicSiteBaseUrl.value.trim(),
      }, { timeout: 15000 })
      wechatPublishingSettings.value = response.data || { configured: true }
      wechatPublishingAppId.value = ''
      wechatPublishingAppSecret.value = ''
      notify.success('公众号发布账号已保存到本机 Keychain')
    } catch (error) {
      notify.error(errorMessage(error, '公众号发布账号保存失败'))
    } finally {
      savingWechatPublishingSettings.value = false
    }
  }

  async function saveWechatQwenCoverSettings() {
    savingWechatQwenCoverSettings.value = true
    try {
      const response = await request.put(`${apiBase}/cover-settings`, {
        api_key: wechatQwenCoverApiKey.value.trim() || undefined,
        endpoint: wechatQwenCoverEndpoint.value.trim(),
        model: wechatQwenCoverModel.value.trim(),
      }, { timeout: 15000 })
      wechatQwenCoverSettings.value = response.data || { configured: true }
      wechatQwenCoverApiKey.value = ''
      notify.success('千问封面配置已保存到本机 Keychain')
    } catch (error) {
      notify.error(errorMessage(error, '千问封面配置保存失败'))
    } finally {
      savingWechatQwenCoverSettings.value = false
    }
  }

  async function testWechatQwenCoverConnection() {
    try {
      await messageBox.confirm(
        '将生成 1 张测试图来验证当前 API Key、接口地址和图像模型；此操作可能消耗免费额度或余额。',
        '测试封面模型',
        { confirmButtonText: '生成测试图', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }

    testingWechatQwenCoverConnection.value = true
    try {
      const response = await request.post(`${apiBase}/cover-settings/test`, {
        api_key: wechatQwenCoverApiKey.value.trim() || undefined,
        endpoint: wechatQwenCoverEndpoint.value.trim(),
        model: wechatQwenCoverModel.value.trim(),
      }, { timeout: 90000 })
      const elapsed = Number(response.data?.elapsed_ms || 0)
      notify.success(`封面模型可用${elapsed ? ` · ${elapsed} ms` : ''}`)
    } catch (error) {
      notify.error(errorMessage(error, '封面模型测试失败'))
    } finally {
      testingWechatQwenCoverConnection.value = false
    }
  }

  async function ensureWechatPublishingConfigured() {
    if (!wechatPublishingSettings.value.configured) await loadWechatPublishingSettings()
    if (wechatPublishingSettings.value.configured) return true
    openSettings('wechat')
    notify.info('请先在“微信公众号”中配置订阅号发布账号')
    return false
  }

  async function ensureWechatCoverConfigured() {
    if (!wechatQwenCoverSettings.value.configured) await loadWechatQwenCoverSettings()
    if (wechatQwenCoverSettings.value.configured) return true
    openSettings('ai')
    notify.info('请先在“AI 服务”设置中配置图像模型 API Key')
    return false
  }

  return {
    ensureWechatCoverConfigured,
    ensureWechatPublishingConfigured,
    loadWechatPublishingSettings,
    loadWechatQwenCoverSettings,
    saveWechatPublishingSettings,
    saveWechatQwenCoverSettings,
    savingWechatPublishingSettings,
    savingWechatQwenCoverSettings,
    testWechatQwenCoverConnection,
    testingWechatQwenCoverConnection,
    wechatPublicSiteBaseUrl,
    wechatPublishingAppId,
    wechatPublishingAppSecret,
    wechatPublishingDisplayName,
    wechatPublishingSettings,
    wechatQwenCoverApiKey,
    wechatQwenCoverEndpoint,
    wechatQwenCoverModel,
    wechatQwenCoverSettings,
  }
}
