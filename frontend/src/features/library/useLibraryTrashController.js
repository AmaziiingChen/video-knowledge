import { h, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLibraryTrashController({
  apiBase = API,
  request = axios,
  notify = ElMessage,
  renderVNode = h,
  loadContentItems,
  loadLibraryFolders,
  revealContentItems,
  expandLibraryFolders,
  resetLibraryHistory,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const libraryTrashEntries = ref([])
  const loadingLibraryTrash = ref(false)

  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  async function loadLibraryTrash() {
    loadingLibraryTrash.value = true
    try {
      const response = await request.get(`${apiBase}/content/trash`, { timeout: 10000 })
      libraryTrashEntries.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
      notifyError(error, '读取回收站失败')
    } finally {
      loadingLibraryTrash.value = false
    }
  }

  async function restoreLibraryTrashEntries(entries, successText) {
    const restorableEntries = Array.isArray(entries) ? entries.filter((entry) => entry?.entry_type && entry?.id) : []
    if (!restorableEntries.length) return false
    try {
      const restoredContentIds = new Set()
      const restoredFolderIds = new Set()
      for (const entry of restorableEntries) {
        const response = await request.post(`${apiBase}/content/trash/${entry.entry_type}/${entry.id}/restore`, null, { timeout: 10000 })
        for (const id of response.data?.restored_content_ids || []) restoredContentIds.add(String(id))
        for (const id of response.data?.restored_folder_ids || []) restoredFolderIds.add(String(id))
      }
      await Promise.all([loadContentItems?.(), loadLibraryTrash()])
      if (restoredContentIds.size) await revealContentItems?.([...restoredContentIds])
      if (restoredFolderIds.size) expandLibraryFolders?.([...restoredFolderIds])
      resetLibraryHistory?.()
      notify.success(successText || (restorableEntries.length === 1
        ? `已恢复“${restorableEntries[0].name}”`
        : `已恢复 ${restorableEntries.length} 个项目`))
      return true
    } catch (error) {
      await Promise.allSettled([loadContentItems?.(), loadLibraryTrash()])
      notifyError(error, '恢复失败')
      return false
    }
  }

  function restoreLibraryTrashEntry(entry) {
    return restoreLibraryTrashEntries([entry])
  }

  function showTrashUndoMessage(entries, message) {
    const undoEntries = Array.isArray(entries) ? entries.filter(Boolean) : []
    if (!undoEntries.length) {
      notify.success(message)
      return
    }
    let messageHandle = null
    let restoring = false
    const undo = async (event) => {
      event?.preventDefault?.()
      event?.stopPropagation?.()
      if (restoring) return
      restoring = true
      messageHandle?.close?.()
      const successText = undoEntries.length === 1
        ? `已撤销移除“${undoEntries[0].name}”`
        : `已撤销移除 ${undoEntries.length} 个项目`
      await restoreLibraryTrashEntries(undoEntries, successText)
    }
    messageHandle = notify({
      type: 'success',
      duration: 6500,
      showClose: true,
      customClass: 'vk-trash-undo-message',
      message: renderVNode('span', { class: 'vk-trash-undo-content' }, [
        renderVNode('span', { class: 'vk-trash-undo-label' }, message),
        renderVNode('button', {
          type: 'button',
          class: 'vk-trash-undo-action',
          'aria-label': '撤销移入回收站',
          onClick: undo,
        }, '撤销'),
      ]),
    })
  }

  async function permanentlyDeleteLibraryTrashEntry(entry) {
    try {
      await request.delete(`${apiBase}/content/trash/${entry.entry_type}/${entry.id}`, { timeout: 10000 })
      await loadLibraryTrash()
      notify.success('已彻底删除')
    } catch (error) {
      notifyError(error, '彻底删除失败')
    }
  }

  async function emptyLibraryTrash() {
    try {
      const response = await request.delete(`${apiBase}/content/trash`, { timeout: 30000 })
      await Promise.all([loadLibraryTrash(), loadContentItems?.(), loadLibraryFolders?.()])
      resetLibraryHistory?.()
      const deletedCount = Number(response.data?.deleted_content_count || 0) + Number(response.data?.deleted_folder_count || 0)
      notify.success(deletedCount ? `已清空回收站（${deletedCount} 项）` : '回收站已清空')
    } catch (error) {
      notifyError(error, '清空回收站失败')
    }
  }

  return {
    libraryTrashEntries,
    loadingLibraryTrash,
    loadLibraryTrash,
    restoreLibraryTrashEntry,
    permanentlyDeleteLibraryTrashEntry,
    emptyLibraryTrash,
    showTrashUndoMessage,
  }
}
