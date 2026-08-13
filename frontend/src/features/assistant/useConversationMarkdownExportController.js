import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useConversationMarkdownExportController({
  getConversation = () => ({}),
  getDesktopExport = () => globalThis.window?.knowledgeHubDesktop?.exportMarkdown,
  recordTelemetry = () => {},
  request = axios,
  apiBase = API,
  notify = ElMessage,
} = {}) {
  const exportingConversationMarkdown = ref(false)

  async function exportConversationMarkdown() {
    if (exportingConversationMarkdown.value) return
    const {
      content = null,
      fallbackTitle = '',
      fallbackSourceUrl = '',
      summary: rawSummary = '',
      history = [],
    } = getConversation() || {}
    const title = String(content?.title || fallbackTitle || 'AI 对话').replace(/\r?\n/g, ' ').trim()
    const sourceUrl = content?.source_url || fallbackSourceUrl || ''
    const sections = [`# ${title}`]
    if (sourceUrl) sections.push(`来源：${sourceUrl}`)
    const summary = String(rawSummary || '').trim()
    if (summary) sections.push(`## AI 总结\n\n${summary}`)
    const exchanges = (Array.isArray(history) ? history : [])
      .filter((item) => String(item?.question || '').trim() || String(item?.answer || '').trim())
      .map((item) => {
        const question = String(item?.question || '').trim()
        const answer = String(item?.answer || '').trim() || '（尚未生成回答）'
        return `### 我\n\n${question}\n\n### AI\n\n${answer}`
      })
    if (exchanges.length) sections.push(`## 对话\n\n${exchanges.join('\n\n---\n\n')}`)
    if (!summary && !exchanges.length) {
      notify.warning('当前没有可导出的 AI 总结或对话')
      return
    }

    exportingConversationMarkdown.value = true
    try {
      const exportTitle = `${title}-AI对话`
      const markdown = `${sections.join('\n\n')}\n`
      const desktopExport = getDesktopExport()
      const exported = desktopExport
        ? await desktopExport(exportTitle, markdown)
        : (await request.post(`${apiBase}/markdown/export`, {
            title: exportTitle,
            markdown,
          }, { timeout: 15000 })).data
      notify.success(`Markdown 已导出到 ${exported.path}`)
      void recordTelemetry('export_completed', { export_kind: 'markdown', result: 'succeeded' })
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || '导出 Markdown 失败'
      notify.error(typeof message === 'string' ? message : '导出 Markdown 失败')
      void recordTelemetry('export_completed', { export_kind: 'markdown', result: 'failed' })
    } finally {
      exportingConversationMarkdown.value = false
    }
  }

  return { exportingConversationMarkdown, exportConversationMarkdown }
}
