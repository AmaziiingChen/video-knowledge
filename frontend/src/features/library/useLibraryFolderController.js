import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useLibraryFolderController({
  libraryFolders,
  snapshotLibraryState,
  restoreLibraryState,
  nextSortOrder,
  recordLibraryHistory,
  request = axios,
  apiBase = API,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  async function loadLibraryFolders({ throwOnError = false } = {}) {
    try {
      const response = await request.get(`${apiBase}/content/folders`, { timeout: 10000 })
      libraryFolders.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
      notifyError(error, '读取文件夹失败')
      if (throwOnError) throw error
    }
  }

  async function createLibraryFolder(payload) {
    const snapshot = snapshotLibraryState()
    const tempId = `tmp-${Date.now()}`
    const tempFolder = {
      id: tempId,
      name: payload.name,
      parent_folder_id: payload.parent_folder_id || null,
      sort_order: nextSortOrder(payload.parent_folder_id || null),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    libraryFolders.value = [...libraryFolders.value, tempFolder]
    try {
      const response = await request.post(`${apiBase}/content/folders`, {
        name: payload.name,
        parent_folder_id: payload.parent_folder_id || null,
        sort_order: tempFolder.sort_order,
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((folder) => folder.id === tempId ? response.data : folder)
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '新建失败')
    }
  }

  async function renameLibraryFolder(payload) {
    const snapshot = snapshotLibraryState()
    const currentFolder = snapshot.folders.find((folder) => folder.id === payload.id)
    if (!currentFolder || currentFolder.name === payload.name) return
    libraryFolders.value = libraryFolders.value.map((folder) => (
      folder.id === payload.id ? { ...folder, name: payload.name } : folder
    ))
    try {
      const response = await request.patch(`${apiBase}/content/folders/${payload.id}`, {
        name: payload.name,
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((folder) => (
        folder.id === payload.id ? { ...folder, ...response.data } : folder
      ))
      recordLibraryHistory('重命名文件夹', snapshot, snapshotLibraryState(), [{ type: 'folder', id: payload.id }])
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '重命名失败')
    }
  }

  async function setLibraryFolderPinned({ folder, pinned }) {
    if (!folder?.id || Boolean(folder.is_pinned) === Boolean(pinned)) return
    const snapshot = snapshotLibraryState()
    libraryFolders.value = libraryFolders.value.map((current) => (
      current.id === folder.id ? { ...current, is_pinned: Boolean(pinned) } : current
    ))
    try {
      const response = await request.patch(`${apiBase}/content/folders/${folder.id}`, {
        is_pinned: Boolean(pinned),
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((current) => (
        current.id === folder.id ? { ...current, ...response.data } : current
      ))
      recordLibraryHistory(
        pinned ? '置顶文件夹' : '取消置顶文件夹',
        snapshot,
        snapshotLibraryState(),
        [{ type: 'folder', id: folder.id }],
      )
      notify.success(pinned ? '文件夹已置顶' : '文件夹已取消置顶')
    } catch (error) {
      restoreLibraryState(snapshot)
      notifyError(error, '更新文件夹置顶状态失败')
    }
  }

  return {
    loadLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    setLibraryFolderPinned,
  }
}
