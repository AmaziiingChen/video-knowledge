import axios from 'axios'
import { ElMessage } from 'element-plus'

export function useWechatFeedExportController({
  feedApi,
  request = axios,
  notify = ElMessage,
  clipboard = globalThis.navigator?.clipboard,
  documentObject = globalThis.document,
  urlObject = globalThis.URL,
  BlobClass = globalThis.Blob,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  async function copyWeChatRss(subscriptionId = '') {
    const suffix = subscriptionId ? `/rss/${subscriptionId}.xml` : '/rss.xml'
    const url = `${feedApi}${suffix}`
    try {
      if (!clipboard?.writeText) throw new Error('Clipboard unavailable')
      await clipboard.writeText(url)
      notify.success(subscriptionId ? '单公众号 RSS 地址已复制' : '聚合 RSS 地址已复制')
    } catch {
      notify.error('无法复制 RSS 地址，请检查系统剪贴板权限')
    }
  }

  async function exportWeChatSubscriptions() {
    try {
      const response = await request.get(`${feedApi}/subscriptions.json`, { timeout: 10000 })
      const blob = new BlobClass([JSON.stringify(response.data, null, 2)], { type: 'application/json;charset=utf-8' })
      const url = urlObject.createObjectURL(blob)
      const anchor = documentObject.createElement('a')
      anchor.href = url
      anchor.download = 'knowledgehub-wechat-subscriptions.json'
      anchor.click()
      urlObject.revokeObjectURL(url)
      notify.success('订阅配置已导出，不包含登录凭据')
    } catch (error) {
      notify.error(errorMessage(error, '导出订阅配置失败'))
    }
  }

  return { copyWeChatRss, exportWeChatSubscriptions }
}
