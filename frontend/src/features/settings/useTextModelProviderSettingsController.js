import { computed, reactive, ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export const TEXT_PROVIDER_PRESETS = Object.freeze({
  deepseek: {
    id: 'deepseek', type: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com',
    models: ['deepseek-v4-flash', 'deepseek-v4-pro'], thinking_parameter: 'thinking',
  },
  qwen: {
    id: 'qwen', type: 'qwen', label: '阿里云百炼 · 千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3.7-plus', 'qwen3.7-max', 'qwen3.6-flash'], thinking_parameter: 'enable_thinking',
  },
  mimo: {
    id: 'mimo', type: 'mimo', label: 'Xiaomi MiMo', base_url: 'https://api.xiaomimimo.com/v1',
    models: ['mimo-v2.5', 'mimo-v2.5-pro'], thinking_parameter: 'thinking',
  },
  custom: {
    id: '', type: 'custom', label: '', base_url: 'http://127.0.0.1:11434/v1',
    models: [], thinking_parameter: 'none', send_temperature: false, stream_options: false, response_format: false,
  },
})

function errorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function cloneDraft(source) {
  return {
    id: String(source?.id || ''),
    type: String(source?.type || 'custom'),
    label: String(source?.label || ''),
    base_url: String(source?.base_url || ''),
    models: Array.isArray(source?.models) ? [...source.models] : [],
    thinking_parameter: String(source?.thinking_parameter || 'none'),
    send_temperature: source?.send_temperature === true,
    stream_options: source?.stream_options === true,
    response_format: source?.response_format === true,
    enabled: source?.enabled !== false,
    api_key: '',
  }
}

export function useTextModelProviderSettingsController({
  request = axios,
  apiBase = API,
  notify,
  confirmDelete,
  onOptionsChanged = () => {},
  onDefaultChanged = () => {},
  getSelectedModel = () => '',
} = {}) {
  const providers = ref([])
  const modelOptions = ref([])
  const loading = ref(false)
  const loadError = ref('')
  const busyAction = ref('')
  const editorOpen = ref(false)
  const editingExisting = ref(false)
  const draft = reactive(cloneDraft(TEXT_PROVIDER_PRESETS.custom))
  let loadRequestId = 0

  const draftModelsText = computed({
    get: () => draft.models.join('\n'),
    set: (value) => {
      draft.models = [...new Set(String(value || '').split(/[\n,，]/u).map((item) => item.trim()).filter(Boolean))].slice(0, 40)
    },
  })
  const isBusy = computed(() => Boolean(busyAction.value))

  function replaceDraft(source) {
    Object.assign(draft, cloneDraft(source))
  }

  function openCreate() {
    replaceDraft(TEXT_PROVIDER_PRESETS.custom)
    editingExisting.value = false
    editorOpen.value = true
  }

  function openEdit(provider) {
    replaceDraft(provider)
    editingExisting.value = true
    editorOpen.value = true
  }

  function closeEditor() {
    draft.api_key = ''
    editorOpen.value = false
  }

  async function loadProviders({ silent = false } = {}) {
    const requestId = ++loadRequestId
    if (!silent) loading.value = true
    loadError.value = ''
    try {
      const response = await request.get(`${apiBase}/llm-settings/text-providers`, { timeout: 10000 })
      if (requestId !== loadRequestId) return false
      const nextProviders = Array.isArray(response.data?.providers) ? response.data.providers : []
      const providerLabels = Object.fromEntries(nextProviders.map((item) => [item.id, item.label]))
      const providerAvailability = Object.fromEntries(nextProviders.map((item) => [item.id, item.enabled !== false && item.configured === true]))
      const nextModelOptions = Array.isArray(response.data?.model_options)
        ? response.data.model_options.map((option) => ({
          ...option,
          provider_label: providerLabels[option?.provider] || option?.provider || '文本模型',
          disabled: providerAvailability[option?.provider] !== true,
        }))
        : []
      providers.value = nextProviders
      modelOptions.value = nextModelOptions
      onOptionsChanged(nextModelOptions)
      const optionValues = nextModelOptions.filter((option) => !option.disabled).map((option) => option.value)
      if (!optionValues.includes(getSelectedModel())) {
        const config = await request.get(`${apiBase}/config`, { timeout: 10000 }).catch(() => ({ data: {} }))
        if (requestId !== loadRequestId) return false
        const serverDefault = String(config.data?.default_ai_model || '')
        if (serverDefault) onDefaultChanged(serverDefault)
      }
      return true
    } catch (error) {
      if (requestId !== loadRequestId) return false
      loadError.value = errorMessage(error, '无法读取文本模型服务')
      return false
    } finally {
      if (!silent && requestId === loadRequestId) loading.value = false
    }
  }

  function providerPayload() {
    const payload = {
      type: draft.type,
      label: draft.label.trim(),
      base_url: draft.base_url.trim(),
      models: [...draft.models],
      thinking_parameter: draft.thinking_parameter,
    }
    if (draft.type === 'custom') {
      payload.send_temperature = draft.send_temperature
      payload.stream_options = draft.stream_options
      payload.response_format = draft.response_format
    }
    if (draft.api_key.trim()) payload.api_key = draft.api_key.trim()
    return payload
  }

  async function saveProvider() {
    const providerId = draft.id.trim().toLowerCase()
    if (!providerId || !draft.label.trim() || !draft.base_url.trim() || !draft.models.length) {
      notify?.warning?.('请填写 Provider ID、名称、Base URL 和至少一个模型')
      return false
    }
    if (draft.enabled === false && !draft.api_key.trim()) {
      notify?.warning?.('重新启用服务时必须重新输入 API Key')
      return false
    }
    busyAction.value = `save:${providerId}`
    try {
      await request.put(
        `${apiBase}/llm-settings/text-providers/${encodeURIComponent(providerId)}`,
        providerPayload(),
        { timeout: 15000 },
      )
      draft.api_key = ''
      await loadProviders({ silent: true })
      editorOpen.value = false
      notify?.success?.(`${draft.label.trim()} 已保存`)
      return true
    } catch (error) {
      notify?.error?.(errorMessage(error, '文本模型服务保存失败'))
      return false
    } finally {
      busyAction.value = ''
    }
  }

  async function testProvider() {
    if (!editingExisting.value) {
      notify?.warning?.('请先保存服务，再测试连接')
      return false
    }
    busyAction.value = `test:${draft.id}`
    try {
      const body = { model: draft.models[0] || undefined }
      if (draft.api_key.trim()) body.api_key = draft.api_key.trim()
      const response = await request.post(
        `${apiBase}/llm-settings/text-providers/${encodeURIComponent(draft.id)}/test`,
        body,
        { timeout: 30000 },
      )
      const elapsed = Number(response.data?.elapsed_ms || 0)
      notify?.success?.(`连接成功${elapsed ? ` · ${elapsed} ms` : ''}`)
      return true
    } catch (error) {
      notify?.error?.(errorMessage(error, '文本模型连接失败'))
      return false
    } finally {
      busyAction.value = ''
    }
  }

  async function refreshModels() {
    if (!editingExisting.value) {
      notify?.warning?.('请先保存服务，再刷新模型')
      return false
    }
    busyAction.value = `models:${draft.id}`
    try {
      const body = {}
      if (draft.api_key.trim()) body.api_key = draft.api_key.trim()
      const response = await request.post(
        `${apiBase}/llm-settings/text-providers/${encodeURIComponent(draft.id)}/models`,
        body,
        { timeout: 30000 },
      )
      if (Array.isArray(response.data?.models)) draft.models = [...new Set(response.data.models.map(String))].slice(0, 40)
      const warning = String(response.data?.warning || '')
      if (warning) notify?.warning?.(warning)
      else notify?.success?.(response.data?.source === 'remote' ? '已读取服务端模型列表，保存后生效' : '已载入内置模型目录')
      return true
    } catch (error) {
      notify?.error?.(errorMessage(error, '模型列表刷新失败'))
      return false
    } finally {
      busyAction.value = ''
    }
  }

  async function deleteProvider(provider) {
    if (!provider || provider.type !== 'custom' || provider.enabled === false) return false
    const confirmed = await confirmDelete?.({
      title: '删除文本模型服务',
      message: `将停用“${provider.label}”并删除其本机钥匙串凭据。已有对话不会被删除。`,
      confirmLabel: '删除',
    })
    if (!confirmed) return false
    busyAction.value = `delete:${provider.id}`
    try {
      await request.delete(`${apiBase}/llm-settings/text-providers/${encodeURIComponent(provider.id)}`, { timeout: 15000 })
      await loadProviders({ silent: true })
      notify?.success?.('文本模型服务已停用，本机凭据已删除')
      return true
    } catch (error) {
      notify?.error?.(errorMessage(error, '文本模型服务删除失败'))
      return false
    } finally {
      busyAction.value = ''
    }
  }

  async function setDefaultModel(selection) {
    const next = String(selection || '').trim()
    if (!next) return false
    busyAction.value = 'default'
    try {
      await request.put(`${apiBase}/llm-settings/default-text-model`, { selection: next }, { timeout: 10000 })
      onDefaultChanged(next)
      notify?.success?.('默认文本模型已更新')
      return true
    } catch (error) {
      notify?.error?.(errorMessage(error, '默认文本模型保存失败'))
      return false
    } finally {
      busyAction.value = ''
    }
  }

  return {
    providers, modelOptions, loading, loadError, busyAction, isBusy,
    editorOpen, editingExisting, draft, draftModelsText,
    openCreate, openEdit, closeEditor, loadProviders, saveProvider,
    testProvider, refreshModels, deleteProvider, setDefaultModel,
  }
}
