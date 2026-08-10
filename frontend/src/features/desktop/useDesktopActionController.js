import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useDesktopActionController({
  request = axios,
  apiBase = API,
  notify = ElMessage,
  confirm = ElMessageBox.confirm,
  getDesktopBridge = () => window.knowledgeHubDesktop,
  writeClipboard = (value) => navigator.clipboard.writeText(value),
  openWindow = (...args) => window.open(...args),
} = {}) {
  async function copyText(value, message) {
    if (!value) return
    try {
      const desktopCopy = getDesktopBridge()?.copyText
      if (desktopCopy) await desktopCopy(value)
      else await writeClipboard(value)
      notify.success(message)
    } catch {
      notify.error('复制失败')
    }
  }

  function openExternalLink(value) {
    if (!value) return
    const desktopOpen = getDesktopBridge()?.openExternal
    if (desktopOpen) {
      desktopOpen(value).catch(() => {
        notify.error('无法使用默认浏览器打开链接')
      })
      return
    }
    openWindow(value, '_blank', 'noopener,noreferrer')
  }

  async function revealLibraryNodeLocation(node) {
    const desktopReveal = getDesktopBridge()?.revealPath
    if (!desktopReveal) {
      notify.warning('请在桌面版中使用“在 Finder 中显示”')
      return
    }
    const isFolder = node?.type === 'folder'
    const nodeId = String(node?.raw?.id || node?.id || '').trim()
    if (!nodeId) return
    try {
      const response = isFolder
        ? await request.get(`${apiBase}/content/folders/${encodeURIComponent(nodeId)}/location`, { timeout: 10000 })
        : await request.get(`${apiBase}/markdown/content/${encodeURIComponent(nodeId)}`, { timeout: 10000 })
      const localPath = isFolder
        ? String(response.data?.path || '')
        : String(response.data?.markdown_draft_path || response.data?.obsidian_path || '')
      if (!localPath) throw new Error('本地 Markdown 文件尚未生成')
      await desktopReveal(localPath)
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || '无法打开所在位置'
      notify.error(typeof detail === 'string' ? detail : '无法打开所在位置')
    }
  }

  async function revealLocalPath(localPath) {
    const desktopReveal = getDesktopBridge()?.revealPath
    if (!desktopReveal) {
      notify.warning('请在桌面版中使用“在 Finder 中显示”')
      return
    }
    if (!String(localPath || '').trim()) return
    try {
      await desktopReveal(localPath)
    } catch (error) {
      notify.error(error?.message || '无法打开所在位置')
    }
  }

  function recordTelemetry(eventName, properties = {}) {
    return request.post(
      `${apiBase}/telemetry/events`,
      { event_name: eventName, properties },
      { timeout: 2000 },
    ).catch(() => {})
  }

  async function checkManualUpdate() {
    try {
      const response = await request.get(`${apiBase}/updates/check`, { timeout: 6000 })
      const update = response.data || {}
      if (update.state !== 'available' || !update.download_page_url) return
      const notes = String(update.release_notes || '').trim()
      await confirm(
        notes
          ? `发现 KnowledgeHub ${update.latest_version}。\n\n${notes}`
          : `发现 KnowledgeHub ${update.latest_version}。`,
        '有可用更新',
        {
          confirmButtonText: '打开下载页',
          cancelButtonText: '稍后再说',
          type: 'info',
          closeOnClickModal: true,
        },
      )
      openExternalLink(update.download_page_url)
      void recordTelemetry('update_download_page_opened')
    } catch (error) {
      // The manifest is optional and update checks must not interrupt startup.
      if (error !== 'cancel' && error?.message !== 'cancel') return
    }
  }

  return {
    copyText,
    openExternalLink,
    revealLibraryNodeLocation,
    revealLocalPath,
    recordTelemetry,
    checkManualUpdate,
  }
}
