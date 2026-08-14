import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useMarkdownOutputSettingsController({
  notify,
  request = axios,
  apiBase = API,
  refreshLibrary = async () => {},
}) {
  const obsidianVaultPath = ref('')
  const markdownExportPath = ref('')
  const obsidianAutoWrite = ref(false)
  let savedVaultPath = ''

  async function loadObsidianSettings() {
    try {
      const response = await request.get(`${apiBase}/obsidian/settings`, { timeout: 10000 })
      obsidianVaultPath.value = response.data.vault_path || ''
      savedVaultPath = obsidianVaultPath.value
      markdownExportPath.value = response.data.export_path || response.data.vault_path || ''
      obsidianAutoWrite.value = Boolean(response.data.auto_write)
    } catch {
      // Markdown output settings must not prevent the rest of the workbench
      // from starting when the local backend is still becoming available.
    }
  }

  async function saveObsidianSettings({ recoverExisting = false } = {}) {
    const vaultPath = obsidianVaultPath.value.trim()
    const exportPath = markdownExportPath.value.trim()
    if (!vaultPath || !exportPath) {
      notify.warning('请填写 Markdown 写入目录和默认导出目录')
      return false
    }
    const shouldRecover = Boolean(
      obsidianAutoWrite.value
      && (recoverExisting || vaultPath !== savedVaultPath),
    )
    try {
      const response = await request.post(`${apiBase}/obsidian/settings`, {
        vault_path: vaultPath,
        export_path: exportPath,
        auto_write: obsidianAutoWrite.value,
        recover_existing: shouldRecover,
      }, { timeout: shouldRecover ? 30000 : 10000 })
      obsidianVaultPath.value = response.data.vault_path || vaultPath
      savedVaultPath = obsidianVaultPath.value
      markdownExportPath.value = response.data.export_path || exportPath
      obsidianAutoWrite.value = Boolean(response.data.auto_write)
      const restored = Number(response.data.restored_documents || 0)
      const existing = Number(response.data.existing_documents || 0)
      const conflicts = Number(response.data.conflicted_documents || 0)
      const recognized = Number(response.data.recognized_documents || 0)
      const scanTruncated = Boolean(response.data.scan_truncated)
      if (shouldRecover) {
        if (restored > 0) {
          notify.success(`已恢复 ${restored} 条旧资料，正在刷新侧边栏`)
        } else if (recognized > 0 && conflicts === 0) {
          notify.info(`目录中的 ${existing || recognized} 条资料均已识别`)
        } else if (recognized === 0) {
          notify.warning('所选目录中未发现可恢复的 KnowledgeHub 资料')
        }
        if (conflicts > 0) {
          notify.warning(`${conflicts} 条重复或冲突资料已安全跳过`)
        }
        if (scanTruncated) {
          notify.warning('目录资料超过单次识别上限，请整理后再次识别')
        }
      }
      if (restored > 0 || Number(response.data.migrated_documents || 0) > 0) {
        await refreshLibrary()
      }
      return true
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '保存 Markdown 输出目录失败'
      notify.error(typeof message === 'string' ? message : '保存 Markdown 输出目录失败')
      return false
    }
  }

  async function saveObsidianSettingsFromForm(options) {
    return saveObsidianSettings(options)
  }

  return {
    obsidianVaultPath,
    markdownExportPath,
    obsidianAutoWrite,
    loadObsidianSettings,
    saveObsidianSettings,
    saveObsidianSettingsFromForm,
  }
}
