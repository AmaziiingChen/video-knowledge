import { computed, h, nextTick, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'
import { promptTemplateDisplayName } from '../../config/promptInterface.js'

// Keeps the prompt tree, open tabs and editor drafts together. The application
// root owns only the shared prompt editor and report-prompt feature APIs.
export function usePromptWorkspaceController({
  standardPrompt,
  reportPrompt,
  fixedSystemPrompts,
  activeView,
  apiBase = API,
  reportGroupApi = `${API}/wechat-report-groups`,
  request = axios,
  notify = ElMessage,
  confirmDestructive,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const promptWorkspaceTemplates = ref([])
  const promptFolders = ref([])
  const promptWorkspaceTabs = ref([])
  const activePromptTabId = ref('')
  const promptTrashEntries = ref([])
  const loadingPromptTrash = ref(false)
  let activationSequence = 0
  let editorSyncDepth = 0

  const systemPromptEntries = computed(() => fixedSystemPrompts?.value || [])
  const promptContextEntries = computed(() => (reportPrompt?.prompts?.value || [])
    .filter((prompt) => prompt.report_type === 'group_context')
    .map((prompt) => ({
      id: `context:${prompt.id}`,
      category: `分组报告 · ${prompt.group_name || '未命名分组'}`,
      name: String(prompt.display_name || '组别说明'),
      description: '随每个生成阶段作为 user 任务上下文发送；不是 system prompt。',
      template: prompt.template || '',
    })))
  const activePromptNodeId = computed(() => {
    const tab = activePromptWorkspaceTab()
    if (!tab) return ''
    if (tab.kind === 'system') return `system:${tab.systemPromptId}`
    if (tab.kind === 'context') return `context:${tab.systemPromptId}`
    return tab.kind === 'report' ? `report:${tab.reportPromptId}` : tab.promptId ? `prompt:${tab.promptId}` : tab.id
  })

  function activePromptWorkspaceTab() {
    return promptWorkspaceTabs.value.find((tab) => tab.id === activePromptTabId.value) || null
  }

  function promptWorkspaceTabDirty(tab) {
    if (!tab || tab.kind === 'system' || tab.kind === 'context') return false
    if (tab.isNew) return Boolean(String(tab.draftName || '').trim() || String(tab.draftText || '').trim())
    if (tab.kind === 'report') return tab.draftText !== tab.originalText
    return tab.draftName !== tab.originalName || tab.draftText !== tab.originalText
  }

  function captureActivePromptDraft() {
    if (editorSyncDepth > 0) return
    const tab = activePromptWorkspaceTab()
    if (!tab || tab.kind === 'system' || tab.kind === 'context') return
    if (tab.kind === 'report') tab.draftText = reportPrompt.text.value
    else {
      tab.draftName = standardPrompt.editorName.value
      tab.draftText = standardPrompt.editorText.value
    }
    tab.dirty = promptWorkspaceTabDirty(tab)
  }

  // The standard prompt API still loads into shared editor refs. When an older
  // request finishes after a newer tab activation, restore the newer tab's
  // draft before edits are accepted again.
  function syncActiveTabDraft() {
    const tab = activePromptWorkspaceTab()
    if (!tab) return
    if (tab.kind === 'report') {
      reportPrompt.selectGroup(tab.groupId)
      reportPrompt.selectType(tab.reportType)
      reportPrompt.text.value = tab.draftText
      return
    }
    standardPrompt.taskType.value = tab.taskType
    if (tab.kind === 'system' || tab.kind === 'context') {
      standardPrompt.editorName.value = tab.title
      standardPrompt.editorText.value = tab.draftText
      return
    }
    standardPrompt.selectedId.value = tab.promptId || ''
    standardPrompt.editorName.value = tab.draftName
    standardPrompt.editorText.value = tab.draftText
  }

  function reconcilePromptWorkspaceTabs() {
    const templateMap = new Map(promptWorkspaceTemplates.value.map((template) => [template.id, template]))
    const reportMap = new Map((reportPrompt.prompts.value || []).map((prompt) => [prompt.id, prompt]))
    const systemMap = new Map(systemPromptEntries.value.map((prompt) => [prompt.id, prompt]))
    const contextMap = new Map(promptContextEntries.value.map((prompt) => [prompt.id, prompt]))
    promptWorkspaceTabs.value = promptWorkspaceTabs.value
      .filter((tab) => tab.isNew || (
        tab.kind === 'report' ? reportMap.has(tab.reportPromptId)
          : tab.kind === 'system' ? systemMap.has(tab.systemPromptId)
            : tab.kind === 'context' ? contextMap.has(tab.systemPromptId)
              : templateMap.has(tab.promptId)
      ))
      .map((tab) => {
        const source = tab.kind === 'report' ? reportMap.get(tab.reportPromptId)
          : tab.kind === 'system' ? systemMap.get(tab.systemPromptId)
            : tab.kind === 'context' ? contextMap.get(tab.systemPromptId)
              : templateMap.get(tab.promptId)
        if (!source) return tab
        return {
          ...tab,
          title: tab.kind === 'report' ? String(source.display_name || '区间报告')
            : tab.kind === 'system' ? String(source.name || '系统提示词')
              : tab.kind === 'context' ? String(source.name || '任务上下文')
                : promptTemplateDisplayName(source),
          originalText: ['system', 'context'].includes(tab.kind) ? String(source.template || '') : tab.originalText,
          draftText: ['system', 'context'].includes(tab.kind) ? String(source.template || '') : tab.draftText,
        }
      })
    if (!promptWorkspaceTabs.value.some((tab) => tab.id === activePromptTabId.value)) {
      activePromptTabId.value = promptWorkspaceTabs.value[0]?.id || ''
    }
  }

  async function loadPromptWorkspaceData() {
    try {
      const [templatesResponse, foldersResponse, systemResponse] = await Promise.all([
        request.get(`${apiBase}/prompts`, { timeout: 10000 }),
        request.get(`${apiBase}/prompt-folders`, { timeout: 10000 }),
        request.get(`${apiBase}/system-prompts`, { timeout: 10000 }),
      ])
      promptWorkspaceTemplates.value = Array.isArray(templatesResponse.data) ? templatesResponse.data : []
      promptFolders.value = Array.isArray(foldersResponse.data) ? foldersResponse.data : []
      fixedSystemPrompts.value = Array.isArray(systemResponse.data) ? systemResponse.data : []
      reconcilePromptWorkspaceTabs()
    } catch (error) {
      notify.error(errorMessage(error, '无法读取提示词文件树'))
    }
  }

  async function loadPromptTrash() {
    loadingPromptTrash.value = true
    try {
      const response = await request.get(`${apiBase}/prompts/trash`, { timeout: 10000 })
      promptTrashEntries.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
      notify.error(errorMessage(error, '无法读取提示词回收站'))
    } finally {
      loadingPromptTrash.value = false
    }
  }

  async function activatePromptWorkspaceTab(tabId, { capture = true } = {}) {
    const sequence = ++activationSequence
    if (capture) captureActivePromptDraft()
    const tab = promptWorkspaceTabs.value.find((item) => item.id === tabId)
    if (!tab) return
    editorSyncDepth += 1
    try {
      activePromptTabId.value = tabId
      if (tab.kind === 'report') {
        standardPrompt.taskType.value = 'wechat_reports'
        reportPrompt.selectGroup(tab.groupId)
        reportPrompt.selectType(tab.reportType)
        reportPrompt.text.value = tab.draftText
        return
      }
      if (tab.kind === 'system' || tab.kind === 'context') {
        standardPrompt.taskType.value = tab.taskType
        standardPrompt.editorName.value = tab.title
        standardPrompt.editorText.value = tab.draftText
        return
      }
      if (tab.isNew) {
        standardPrompt.create({ taskType: tab.taskType, name: tab.draftName, folderId: tab.folderId })
        standardPrompt.editorText.value = tab.draftText
        return
      }
      standardPrompt.taskType.value = tab.taskType
      await standardPrompt.load()
      if (sequence !== activationSequence || activePromptTabId.value !== tabId) return
      standardPrompt.select(tab.promptId)
      standardPrompt.editorName.value = tab.draftName
      standardPrompt.editorText.value = tab.draftText
    } finally {
      if (sequence !== activationSequence) syncActiveTabDraft()
      await nextTick()
      editorSyncDepth = Math.max(0, editorSyncDepth - 1)
    }
  }

  function openTab(tab) {
    if (!promptWorkspaceTabs.value.some((item) => item.id === tab.id)) promptWorkspaceTabs.value.push(tab)
    return activatePromptWorkspaceTab(tab.id)
  }

  async function openPromptWorkspaceFile({ kind, prompt }) {
    if (!prompt?.id) return
    const isReport = kind === 'report'
    return openTab({
      id: `${kind}:${prompt.id}`,
      title: isReport ? String(prompt.display_name || '区间报告') : promptTemplateDisplayName(prompt),
      kind,
      promptId: isReport ? null : prompt.id,
      reportPromptId: isReport ? prompt.id : null,
      taskType: isReport ? 'wechat_reports' : prompt.task_type,
      groupId: isReport ? prompt.group_id : null,
      reportType: isReport ? prompt.report_type : null,
      originalName: isReport ? String(prompt.display_name || '区间报告') : promptTemplateDisplayName(prompt),
      originalText: prompt.template || '', draftName: isReport ? String(prompt.display_name || '区间报告') : promptTemplateDisplayName(prompt),
      draftText: prompt.template || '', isNew: false, dirty: false,
    })
  }

  function openReadOnlyPrompt(kind, prompt, taskType, fallback) {
    if (!prompt?.id) return Promise.resolve()
    return openTab({ id: `${kind}:${prompt.id}`, title: String(prompt.name || fallback), kind, systemPromptId: prompt.id,
      taskType, originalName: String(prompt.name || fallback), originalText: String(prompt.template || ''),
      draftName: String(prompt.name || fallback), draftText: String(prompt.template || ''), isNew: false, dirty: false })
  }
  const openSystemPromptWorkspaceFile = (prompt) => openReadOnlyPrompt('system', prompt, 'system_prompts', '系统提示词')
  const openPromptContextWorkspaceFile = (prompt) => openReadOnlyPrompt('context', prompt, 'prompt_contexts', '任务上下文')

  async function createPromptWorkspaceFile({ taskType, folderId = null, name }) {
    activationSequence += 1
    captureActivePromptDraft()
    const tabId = `prompt:new:${Date.now()}`
    promptWorkspaceTabs.value.push({ id: tabId, title: name, kind: 'prompt', promptId: null, taskType, folderId,
      originalName: '', originalText: '', draftName: name, draftText: '', isNew: true, dirty: true })
    activePromptTabId.value = tabId
    standardPrompt.create({ taskType, name, folderId })
  }

  async function closePromptWorkspaceTabs(tabIds, { force = false } = {}) {
    captureActivePromptDraft()
    const closingIds = new Set((Array.isArray(tabIds) ? tabIds : [tabIds]).filter(Boolean))
    const closingTabs = promptWorkspaceTabs.value.filter((tab) => closingIds.has(tab.id))
    if (!closingIds.size) return false
    if (!force && closingTabs.some(promptWorkspaceTabDirty)) {
      const confirmed = await confirmDestructive?.({ title: '关闭提示词', message: '关闭后将丢失尚未保存的提示词修改。', confirmLabel: '放弃修改并关闭', cancelLabel: '继续编辑' })
      if (!confirmed) return false
    }
    const activeIndex = promptWorkspaceTabs.value.findIndex((tab) => tab.id === activePromptTabId.value)
    const activeClosed = closingIds.has(activePromptTabId.value)
    promptWorkspaceTabs.value = promptWorkspaceTabs.value.filter((tab) => !closingIds.has(tab.id))
    if (!activeClosed) return true
    const next = promptWorkspaceTabs.value[Math.min(Math.max(activeIndex, 0), promptWorkspaceTabs.value.length - 1)]
    if (next) await activatePromptWorkspaceTab(next.id, { capture: false })
    else {
      activationSequence += 1
      activePromptTabId.value = ''
      standardPrompt.selectedId.value = ''
      standardPrompt.editorName.value = ''
      standardPrompt.editorText.value = ''
      reportPrompt.text.value = ''
    }
    return true
  }
  const closePromptWorkspaceTab = (tabId) => closePromptWorkspaceTabs([tabId])

  async function savePromptWorkspaceCurrent() {
    const tab = activePromptWorkspaceTab()
    if (!tab || tab.kind === 'system' || tab.kind === 'context') return false
    captureActivePromptDraft()
    if (tab.kind === 'report') {
      if (!await reportPrompt.save()) return false
      tab.originalText = reportPrompt.text.value; tab.draftText = reportPrompt.text.value; tab.dirty = false
      await loadPromptWorkspaceData(); return true
    }
    const savedId = await standardPrompt.save()
    if (!savedId) return false
    const wasNew = tab.isNew
    Object.assign(tab, { promptId: savedId, isNew: false, originalName: standardPrompt.editorName.value,
      originalText: standardPrompt.editorText.value, draftName: standardPrompt.editorName.value,
      draftText: standardPrompt.editorText.value, title: standardPrompt.editorName.value, dirty: false })
    if (wasNew) { tab.id = `prompt:${savedId}`; activePromptTabId.value = tab.id }
    await loadPromptWorkspaceData(); return true
  }

  async function resetPromptWorkspaceCurrent() {
    const tab = activePromptWorkspaceTab()
    if (!tab || tab.kind === 'system' || tab.kind === 'context') return false
    const promptName = String(tab.title || '当前提示词')
    const confirmed = await confirmDestructive?.({ title: '恢复内置默认', message: `将“${promptName}”恢复为内置默认内容。当前修改会被替换，且无法撤销。`, confirmLabel: '恢复默认', cancelLabel: '取消' })
    if (!confirmed) return false
    try {
      if (tab.kind === 'report') {
        await request.post(`${reportGroupApi}/${tab.groupId}/prompts/${tab.reportType}/reset`, {}, { timeout: 10000 })
        await reportPrompt.load()
        const prompt = reportPrompt.prompts.value.find((item) => item.id === tab.reportPromptId)
        reportPrompt.text.value = prompt?.template || ''
      } else {
        await request.post(`${apiBase}/prompts/${tab.promptId}/reset`, {}, { timeout: 10000 })
        await loadPromptWorkspaceData()
        const prompt = standardPrompt.templates.value.find((item) => item.id === tab.promptId)
        standardPrompt.editorText.value = prompt?.template || ''
      }
      tab.originalText = tab.draftText = tab.kind === 'report' ? reportPrompt.text.value : standardPrompt.editorText.value
      tab.dirty = false; notify.success(`已恢复“${promptName}”的内置默认内容`); return true
    } catch (error) { notify.error(errorMessage(error, '恢复默认提示词失败')); return false }
  }

  async function createPromptWorkspaceFolder({ taskType, parentFolderId, name }) {
    try { await request.post(`${apiBase}/prompt-folders`, { name, task_type: taskType, parent_folder_id: parentFolderId }, { timeout: 10000 }); await loadPromptWorkspaceData() }
    catch (error) { notify.error(errorMessage(error, '新建提示词文件夹失败')) }
  }
  async function renamePromptWorkspaceFolder({ folder, name }) {
    try { await request.patch(`${apiBase}/prompt-folders/${folder.id}`, { name }, { timeout: 10000 }); await loadPromptWorkspaceData() }
    catch (error) { notify.error(errorMessage(error, '重命名提示词文件夹失败')) }
  }
  async function renamePromptWorkspaceFile({ prompt, name }) {
    captureActivePromptDraft()
    try {
      await request.patch(`${apiBase}/prompts/${prompt.id}`, { name }, { timeout: 10000 })
      const tab = promptWorkspaceTabs.value.find((item) => item.promptId === prompt.id)
      if (tab) Object.assign(tab, { title: name, originalName: name, draftName: name })
      if (standardPrompt.taskType.value === prompt.task_type) await standardPrompt.load()
      if (tab?.id === activePromptTabId.value) { standardPrompt.editorName.value = name; standardPrompt.editorText.value = tab.draftText; tab.dirty = promptWorkspaceTabDirty(tab) }
      await loadPromptWorkspaceData()
    } catch (error) { notify.error(errorMessage(error, '重命名提示词失败')) }
  }
  async function renameReportPromptWorkspaceFile({ prompt, name }) {
    try { await request.put(`${reportGroupApi}/${prompt.group_id}/prompts/${prompt.report_type}`, { display_name: name }, { timeout: 10000 }); const tab = promptWorkspaceTabs.value.find((item) => item.reportPromptId === prompt.id); if (tab) tab.title = name; await reportPrompt.load(); reconcilePromptWorkspaceTabs() }
    catch (error) { notify.error(errorMessage(error, '重命名报告提示词失败')) }
  }

  function showPromptTrashUndo(entry, message) {
    let handle = null
    handle = notify({ type: 'success', duration: 6500, showClose: true, customClass: 'vk-trash-undo-message', message: h('span', { class: 'vk-trash-undo-content' }, [h('span', { class: 'vk-trash-undo-label' }, message), h('button', { type: 'button', class: 'vk-trash-undo-action', 'aria-label': '撤销移入提示词回收站', onClick: async (event) => { event.preventDefault(); event.stopPropagation(); handle?.close?.(); await restorePromptTrashEntry(entry) } }, '撤销')]) })
  }
  async function refreshAfterTrashChange() { await Promise.all([loadPromptWorkspaceData(), loadPromptTrash(), standardPrompt.refreshQaShortcutTemplates(), standardPrompt.refreshContentAnalysisTemplates()]) }
  async function deletePromptWorkspaceFile(prompt) {
    const confirmed = await confirmDestructive?.({ title: '移入回收站', message: `将“${promptTemplateDisplayName(prompt)}”移入提示词回收站？`, confirmLabel: '移入回收站' }); if (!confirmed) return false
    try { await request.delete(`${apiBase}/prompts/${prompt.id}`, { timeout: 10000 }); await closePromptWorkspaceTabs([`prompt:${prompt.id}`], { force: true }); await refreshAfterTrashChange(); showPromptTrashUndo({ entry_type: 'prompt', id: prompt.id, name: promptTemplateDisplayName(prompt) }, `已将“${promptTemplateDisplayName(prompt)}”移入回收站`); return true }
    catch (error) { notify.error(errorMessage(error, '删除提示词失败')); return false }
  }
  async function deletePromptWorkspaceFolder(folder) {
    const confirmed = await confirmDestructive?.({ title: '移入回收站', message: `将文件夹“${folder.name}”及其内容移入提示词回收站？`, confirmLabel: '移入回收站' }); if (!confirmed) return false
    try { await request.delete(`${apiBase}/prompt-folders/${folder.id}`, { timeout: 10000 }); await refreshAfterTrashChange(); reconcilePromptWorkspaceTabs(); const next = activePromptWorkspaceTab(); if (next) await activatePromptWorkspaceTab(next.id, { capture: false }); else { standardPrompt.selectedId.value = ''; standardPrompt.editorName.value = ''; standardPrompt.editorText.value = '' }; showPromptTrashUndo({ entry_type: 'folder', id: folder.id, name: folder.name }, `已将“${folder.name}”移入回收站`); return true }
    catch (error) { notify.error(errorMessage(error, '删除提示词文件夹失败')); return false }
  }
  async function movePromptWorkspaceNode({ kind, node, folderId }) {
    try { if (kind === 'folder') await request.patch(`${apiBase}/prompt-folders/${node.id}`, { parent_folder_id: folderId }, { timeout: 10000 }); else await request.patch(`${apiBase}/prompts/${node.id}`, { folder_id: folderId }, { timeout: 10000 }); await loadPromptWorkspaceData() }
    catch (error) { notify.error(errorMessage(error, '移动提示词项目失败')) }
  }
  async function restorePromptTrashEntry(entry) {
    try { await request.post(`${apiBase}/prompts/trash/${entry.entry_type}/${entry.id}/restore`, {}, { timeout: 10000 }); await refreshAfterTrashChange(); notify.success(`已恢复“${entry.name}”`) }
    catch (error) { notify.error(errorMessage(error, '恢复提示词项目失败')) }
  }
  async function permanentlyDeletePromptTrashEntry(entry) {
    try { await request.delete(`${apiBase}/prompts/trash/${entry.entry_type}/${entry.id}`, { timeout: 10000 }); await loadPromptTrash(); notify.success('已彻底删除') }
    catch (error) { notify.error(errorMessage(error, '彻底删除提示词失败')) }
  }
  async function activatePromptWorkspaceTemplate(templateId) {
    captureActivePromptDraft(); const tab = activePromptWorkspaceTab(); await standardPrompt.activate(templateId)
    if (tab?.id === activePromptTabId.value) { standardPrompt.editorName.value = tab.draftName; standardPrompt.editorText.value = tab.draftText }
    await Promise.all([loadPromptWorkspaceData(), standardPrompt.refreshQaShortcutTemplates(), standardPrompt.refreshContentAnalysisTemplates()])
  }

  watch([standardPrompt.editorName, standardPrompt.editorText, reportPrompt.text], () => {
    if (activeView?.value !== 'prompts' || editorSyncDepth > 0) return
    captureActivePromptDraft()
  })

  return { promptWorkspaceTemplates, promptFolders, promptWorkspaceTabs, activePromptTabId, promptTrashEntries, loadingPromptTrash, systemPromptEntries, promptContextEntries, activePromptNodeId,
    loadPromptWorkspaceData, loadPromptTrash, activatePromptWorkspaceTab, openPromptWorkspaceFile, openSystemPromptWorkspaceFile, openPromptContextWorkspaceFile, createPromptWorkspaceFile, closePromptWorkspaceTabs, closePromptWorkspaceTab, savePromptWorkspaceCurrent, resetPromptWorkspaceCurrent, createPromptWorkspaceFolder, renamePromptWorkspaceFolder, renamePromptWorkspaceFile, renameReportPromptWorkspaceFile, deletePromptWorkspaceFile, deletePromptWorkspaceFolder, movePromptWorkspaceNode, restorePromptTrashEntry, permanentlyDeletePromptTrashEntry, activatePromptWorkspaceTemplate, captureActivePromptDraft, reconcilePromptWorkspaceTabs }
}
