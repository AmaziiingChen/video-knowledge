import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useMarkdownOutputSettingsController({
  notify,
  request = axios,
  apiBase = API,
}) {
  const obsidianVaultPath = ref('')
  const markdownExportPath = ref('')
  const obsidianAutoWrite = ref(false)

  async function loadObsidianSettings() {
    try {
      const response = await request.get(`${apiBase}/obsidian/settings`, { timeout: 10000 })
      obsidianVaultPath.value = response.data.vault_path || ''
      markdownExportPath.value = response.data.export_path || response.data.vault_path || ''
      obsidianAutoWrite.value = Boolean(response.data.auto_write)
    } catch {
      // Markdown output settings must not prevent the rest of the workbench
      // from starting when the local backend is still becoming available.
    }
  }

  async function saveObsidianSettings() {
    const vaultPath = obsidianVaultPath.value.trim()
    const exportPath = markdownExportPath.value.trim()
    if (!vaultPath || !exportPath) {
      notify.warning('请填写 Markdown 写入目录和默认导出目录')
      return false
    }
    try {
      const response = await request.post(`${apiBase}/obsidian/settings`, {
        vault_path: vaultPath,
        export_path: exportPath,
        auto_write: obsidianAutoWrite.value,
      }, { timeout: 10000 })
      obsidianVaultPath.value = response.data.vault_path || vaultPath
      markdownExportPath.value = response.data.export_path || exportPath
      obsidianAutoWrite.value = Boolean(response.data.auto_write)
      return true
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '保存 Markdown 输出目录失败'
      notify.error(typeof message === 'string' ? message : '保存 Markdown 输出目录失败')
      return false
    }
  }

  async function saveObsidianSettingsFromForm() {
    await saveObsidianSettings()
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
