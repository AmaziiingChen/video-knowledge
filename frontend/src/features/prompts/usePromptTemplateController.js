import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { promptTemplateDisplayName, promptTemplatePersistedName } from '../../config/promptInterface.js'
import { API_BASE as API } from '../../utils/localApiAuth.js'

export function usePromptTemplateController({
  request = axios,
  notify = ElMessage,
  confirmDelete = async () => false,
  refreshContentAnalysisTemplates = async () => {},
  apiBase = API,
  createVersion = () => `v${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}-${Date.now().toString().slice(-4)}`,
} = {}) {
  const promptTaskType = ref('summary')
  const promptTemplates = ref([])
  const selectedPromptTemplateId = ref('')
  const qaShortcutTemplates = ref([])
  const loadingPrompts = ref(false)
  const savingPromptTemplate = ref(false)
  const activatingPromptTemplate = ref(false)
  const creatingPromptTemplate = ref(false)
  const creatingPromptFolderId = ref(null)
  const promptEditorName = ref('')
  const promptEditorText = ref('')
  let promptLoadVersion = 0

  const activePromptTemplate = computed(() => {
    return promptTemplates.value.find((template) => template.id === selectedPromptTemplateId.value)
      || promptTemplates.value.find((template) => template.is_active)
      || promptTemplates.value[0]
      || null
  })

  function promptTemplateOrder(template) {
    try {
      const schema = typeof template.variables_schema === 'string'
        ? JSON.parse(template.variables_schema)
        : template.variables_schema
      const order = Number(schema?.order)
      return Number.isFinite(order) ? order : 999
    } catch {
      return 999
    }
  }

  function sortPromptTemplates(templates) {
    return [...templates].sort((left, right) => promptTemplateOrder(left) - promptTemplateOrder(right))
  }

  function applyActiveTemplateToEditor() {
    promptEditorName.value = promptTemplateDisplayName(activePromptTemplate.value)
    promptEditorText.value = activePromptTemplate.value?.template || ''
  }

  async function loadPromptTemplates() {
    const taskType = promptTaskType.value
    const requestVersion = ++promptLoadVersion
    loadingPrompts.value = true
    try {
      const response = await request.get(`${apiBase}/prompts`, {
        params: { task_type: taskType },
        timeout: 10000,
      })
      if (requestVersion !== promptLoadVersion || taskType !== promptTaskType.value) return
      promptTemplates.value = sortPromptTemplates(response.data || [])
      if (
        !creatingPromptTemplate.value
        && !promptTemplates.value.some((template) => template.id === selectedPromptTemplateId.value)
      ) {
        selectedPromptTemplateId.value = activePromptTemplate.value?.id || ''
      }
      if (!creatingPromptTemplate.value) applyActiveTemplateToEditor()
    } catch (error) {
      if (requestVersion !== promptLoadVersion) return
      notify.error(errorMessage(error, '读取 Prompt 失败'))
    } finally {
      if (requestVersion === promptLoadVersion) loadingPrompts.value = false
    }
  }

  async function loadQaShortcutTemplates() {
    try {
      const response = await request.get(`${apiBase}/prompts`, {
        params: { task_type: 'qa_shortcut' },
        timeout: 10000,
      })
      qaShortcutTemplates.value = sortPromptTemplates(response.data || [])
        .filter((template) => template.template?.trim())
    } catch {
      qaShortcutTemplates.value = []
    }
  }

  function selectPromptTemplate(templateId) {
    creatingPromptTemplate.value = false
    creatingPromptFolderId.value = null
    selectedPromptTemplateId.value = templateId
    applyActiveTemplateToEditor()
  }

  function createPromptTemplate({ taskType = promptTaskType.value, name = '', folderId = null } = {}) {
    promptTaskType.value = taskType
    creatingPromptTemplate.value = true
    creatingPromptFolderId.value = folderId
    selectedPromptTemplateId.value = ''
    promptEditorName.value = name
    promptEditorText.value = ''
  }

  async function savePromptTemplate() {
    const editorName = promptEditorName.value.trim()
    const template = promptEditorText.value.trim()
    if (!editorName || !template) {
      notify.warning('请填写提示词名称和内容')
      return undefined
    }

    savingPromptTemplate.value = true
    const taskType = promptTaskType.value
    const baseTemplate = creatingPromptTemplate.value ? null : activePromptTemplate.value
    const name = promptTemplatePersistedName(baseTemplate, editorName)
    try {
      if (baseTemplate?.id) {
        await request.patch(`${apiBase}/prompts/${baseTemplate.id}`, {
          name,
          template,
          variables_schema: baseTemplate.variables_schema,
        }, { timeout: 10000 })
      } else {
        const created = await request.post(`${apiBase}/prompts`, {
          name,
          task_type: taskType,
          version: createVersion(),
          template,
          folder_id: creatingPromptFolderId.value,
          is_active: taskType === 'qa_shortcut',
        }, { timeout: 10000 })
        selectedPromptTemplateId.value = created.data?.id || ''
      }
      creatingPromptTemplate.value = false
      creatingPromptFolderId.value = null
      await loadPromptTemplates()
      if (taskType === 'qa_shortcut') await loadQaShortcutTemplates()
      if (taskType === 'content_analysis') await refreshContentAnalysisTemplates()
      notify.success(
        baseTemplate
          ? '提示词已保存'
          : taskType === 'qa_shortcut'
            ? '快捷追问已保存并启用'
            : '提示词已保存，请设为当前使用',
      )
      return selectedPromptTemplateId.value
    } catch (error) {
      notify.error(errorMessage(error, '保存 Prompt 失败'))
      return ''
    } finally {
      savingPromptTemplate.value = false
    }
  }

  async function activatePromptTemplate(templateId) {
    const template = promptTemplates.value.find((item) => item.id === templateId)
    if (!template || template.is_active) return
    activatingPromptTemplate.value = true
    try {
      await request.post(`${apiBase}/prompts/${templateId}/activate`, {}, { timeout: 10000 })
      await loadPromptTemplates()
      selectedPromptTemplateId.value = templateId
      applyActiveTemplateToEditor()
      notify.success(template.task_type === 'qa_shortcut' ? '快捷追问已启用' : '已设为当前使用')
    } catch (error) {
      notify.error(errorMessage(error, '启用 Prompt 失败'))
    } finally {
      activatingPromptTemplate.value = false
    }
  }

  async function deletePromptTemplate(templateId) {
    const template = promptTemplates.value.find((item) => item.id === templateId)
    if (!template) return
    const confirmed = await confirmDelete({
      title: '移入回收站',
      message: `将“${template.name}”移入提示词回收站？`,
      confirmLabel: '移入回收站',
    })
    if (!confirmed) return

    try {
      await request.delete(`${apiBase}/prompts/${templateId}`, { timeout: 10000 })
      creatingPromptTemplate.value = false
      selectedPromptTemplateId.value = ''
      promptEditorName.value = ''
      promptEditorText.value = ''
      await loadPromptTemplates()
      if (template.task_type === 'qa_shortcut') await loadQaShortcutTemplates()
      if (template.task_type === 'content_analysis') await refreshContentAnalysisTemplates()
      notify.success('提示词已移入回收站')
    } catch (error) {
      notify.error(errorMessage(error, '删除提示词失败'))
    }
  }

  return {
    promptTaskType,
    promptTemplates,
    selectedPromptTemplateId,
    qaShortcutTemplates,
    loadingPrompts,
    savingPromptTemplate,
    activatingPromptTemplate,
    promptEditorName,
    promptEditorText,
    sortPromptTemplates,
    loadPromptTemplates,
    loadQaShortcutTemplates,
    selectPromptTemplate,
    createPromptTemplate,
    savePromptTemplate,
    activatePromptTemplate,
    deletePromptTemplate,
  }
}

function errorMessage(error, fallback) {
  const message = error?.response?.data?.detail || error?.message || fallback
  return typeof message === 'string' ? message : fallback
}
