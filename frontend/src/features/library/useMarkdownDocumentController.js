import { reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useMarkdownDocumentController({
  request = axios,
  apiBase = API,
  notify = ElMessage,
  setSelectedContentItem = () => {},
  isSelectedContentItem = () => true,
} = {}) {
  const showMarkdownDialog = ref(false)
  const currentMarkdownItem = ref(null)
  const loadingMarkdown = ref(false)
  const savingMarkdown = ref(false)
  const syncingMarkdown = ref(false)
  const markdownState = reactive({
    content_item_id: null,
    markdown_draft_path: null,
    obsidian_path: null,
    markdown: '',
    markdown_size_bytes: 0,
    sync_status: 'unknown',
    conflict: false,
    last_synced_at: null,
  })

  function applyMarkdownState(data = {}) {
    markdownState.content_item_id = data.content_item_id || null
    markdownState.markdown_draft_path = data.markdown_draft_path || null
    markdownState.obsidian_path = data.obsidian_path || null
    markdownState.markdown = data.markdown || ''
    markdownState.markdown_size_bytes = Number(data.markdown_size_bytes || 0)
    markdownState.sync_status = data.sync_status || 'unknown'
    markdownState.conflict = Boolean(data.conflict)
    markdownState.last_synced_at = data.last_synced_at || null
  }

  function resetMarkdownState() {
    applyMarkdownState()
  }

  async function loadMarkdownForItem(item) {
    loadingMarkdown.value = true
    try {
      const response = await request.get(`${apiBase}/markdown/content/${item.id}`, { timeout: 10000 })
      if (isSelectedContentItem(item.id)) applyMarkdownState(response.data)
    } catch {
      if (isSelectedContentItem(item.id)) resetMarkdownState()
    } finally {
      if (isSelectedContentItem(item.id)) loadingMarkdown.value = false
    }
  }

  async function openMarkdownDialog(item) {
    currentMarkdownItem.value = item
    setSelectedContentItem(item)
    showMarkdownDialog.value = true
    loadingMarkdown.value = true
    try {
      const response = await request.get(`${apiBase}/markdown/content/${item.id}`, { timeout: 10000 })
      applyMarkdownState(response.data)
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '读取 Markdown 草稿失败'
      notify.error(typeof message === 'string' ? message : '读取 Markdown 草稿失败')
      showMarkdownDialog.value = false
    } finally {
      loadingMarkdown.value = false
    }
  }

  async function saveMarkdownDraft() {
    if (!currentMarkdownItem.value?.id) return
    savingMarkdown.value = true
    try {
      const response = await request.put(`${apiBase}/markdown/content/${currentMarkdownItem.value.id}`, {
        markdown: markdownState.markdown,
      }, { timeout: 10000 })
      applyMarkdownState(response.data)
      setSelectedContentItem(currentMarkdownItem.value)
      notify.success('草稿已保存')
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '保存 Markdown 失败'
      notify.error(typeof message === 'string' ? message : '保存 Markdown 失败')
    } finally {
      savingMarkdown.value = false
    }
  }

  async function syncMarkdownDraft() {
    if (!currentMarkdownItem.value?.id) return
    syncingMarkdown.value = true
    try {
      const response = await request.post(
        `${apiBase}/markdown/content/${currentMarkdownItem.value.id}/sync`,
        {},
        { timeout: 10000 },
      )
      applyMarkdownState(response.data)
      setSelectedContentItem(currentMarkdownItem.value)
      notify.success('已写入指定 Markdown 目录')
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '写入 Markdown 失败'
      notify.error(typeof message === 'string' ? message : '写入 Markdown 失败')
    } finally {
      syncingMarkdown.value = false
    }
  }

  return {
    showMarkdownDialog,
    currentMarkdownItem,
    loadingMarkdown,
    savingMarkdown,
    syncingMarkdown,
    markdownState,
    applyMarkdownState,
    resetMarkdownState,
    loadMarkdownForItem,
    openMarkdownDialog,
    saveMarkdownDraft,
    syncMarkdownDraft,
  }
}
