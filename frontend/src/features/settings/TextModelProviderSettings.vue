<template>
  <div class="text-provider-settings">
    <div class="text-provider-default">
      <label class="settings-ai-input-label" for="default-ai-model">默认文本模型</label>
      <el-select
        id="default-ai-model"
        :model-value="selectedModel"
        class="settings-ai-select"
        name="default-ai-model"
        filterable
        aria-label="默认文本模型"
        placeholder="选择已配置的模型"
        :loading="loading"
        :disabled="isBusy || !modelOptions.length"
        @change="setDefaultModel"
      >
        <el-option-group v-for="group in groupedModelOptions" :key="group.provider" :label="group.label">
          <el-option v-for="option in group.options" :key="option.value" :label="option.disabled ? `${option.label}（未配置）` : option.label" :value="option.value" :disabled="option.disabled" />
        </el-option-group>
      </el-select>
    </div>

    <div class="text-provider-toolbar">
      <p>API Key 保存到本机钥匙串；不会写入项目文件或浏览器存储。</p>
      <el-button size="small" :disabled="isBusy" @click="openCreate">新增服务</el-button>
    </div>

    <div v-if="loading && !providers.length" class="settings-empty-state" role="status">正在读取文本模型服务…</div>
    <div v-else-if="loadError && !providers.length" class="text-provider-error" role="alert">
      <span>{{ loadError }}</span>
      <el-button size="small" @click="loadProviders()">重试</el-button>
    </div>
    <div v-else-if="!providers.length" class="settings-empty-state">尚未配置文本模型服务。</div>
    <div v-else class="text-provider-list" aria-label="文本模型服务列表">
      <article v-for="provider in providers" :key="provider.id" class="text-provider-row">
        <div class="text-provider-copy">
          <div class="text-provider-title">
            <strong>{{ provider.label }}</strong>
            <span class="settings-status" :class="provider.enabled === false ? 'is-idle' : provider.configured ? 'is-valid' : 'is-warning'">{{ provider.enabled === false ? '已停用' : provider.configured ? '已配置' : '待填写密钥' }}</span>
          </div>
          <p>{{ provider.base_url }}</p>
          <span>{{ provider.models.length }} 个模型 · {{ provider.type === 'custom' ? 'OpenAI 兼容服务' : '内置服务' }}</span>
        </div>
        <div class="text-provider-actions">
          <el-button size="small" :disabled="isBusy" @click="openEdit(provider)">{{ provider.enabled === false ? '重新配置' : '编辑' }}</el-button>
          <el-button v-if="provider.type === 'custom' && provider.enabled !== false" size="small" text type="danger" :loading="busyAction === `delete:${provider.id}`" :disabled="isBusy && busyAction !== `delete:${provider.id}`" @click="deleteProvider(provider)">删除</el-button>
        </div>
      </article>
    </div>
    <div v-if="loadError && providers.length" class="text-provider-inline-error" role="alert">{{ loadError }} <button type="button" @click="loadProviders()">重试</button></div>

    <el-dialog v-model="editorOpen" append-to-body width="min(580px, calc(100vw - 32px))" class="text-provider-editor" :title="editingExisting ? `编辑 ${draft.label}` : '新增文本模型服务'" :close-on-click-modal="!isBusy" :close-on-press-escape="!isBusy">
      <div class="text-provider-form">
        <label for="text-provider-id">Provider ID</label>
        <el-input id="text-provider-id" v-model="draft.id" name="text-provider-id" autocomplete="off" spellcheck="false" :disabled="editingExisting" placeholder="例如 local-gateway" />
        <label for="text-provider-label">显示名称</label>
        <el-input id="text-provider-label" v-model="draft.label" name="text-provider-label" autocomplete="off" placeholder="例如 本机 Ollama" />
        <label for="text-provider-base-url">Base URL</label>
        <el-input id="text-provider-base-url" v-model="draft.base_url" name="text-provider-base-url" type="url" autocomplete="off" inputmode="url" spellcheck="false" placeholder="http://127.0.0.1:11434/v1" />
        <label for="text-provider-api-key">API Key</label>
        <el-input id="text-provider-api-key" v-model="draft.api_key" name="text-provider-api-key" type="password" autocomplete="new-password" spellcheck="false" :placeholder="editingExisting && currentProviderConfigured ? '已保存；留空保持不变' : '输入服务 API Key'" />
        <label for="text-provider-models">模型名称</label>
        <el-input id="text-provider-models" v-model="draftModelsText" name="text-provider-models" type="textarea" :rows="3" autocomplete="off" spellcheck="false" placeholder="每行一个模型名称" />
        <div v-if="draft.type === 'custom'" class="text-provider-capabilities">
          <label for="text-provider-thinking">思考内容参数</label>
          <el-select id="text-provider-thinking" v-model="draft.thinking_parameter" aria-label="思考内容参数">
            <el-option label="不发送额外思考参数" value="none" />
            <el-option label="thinking.type" value="thinking" />
            <el-option label="enable_thinking" value="enable_thinking" />
          </el-select>
          <label><el-checkbox v-model="draft.send_temperature">发送 temperature</el-checkbox></label>
          <label><el-checkbox v-model="draft.stream_options">发送 stream_options</el-checkbox></label>
          <label><el-checkbox v-model="draft.response_format">支持 JSON response_format</el-checkbox></label>
        </div>
        <p class="text-provider-form-note">Knowledge 类结构化任务只会使用支持 response_format 的服务；系统不会自动猜测 Base URL，也不会自动故障转移。</p>
      </div>
      <template #footer>
        <div class="text-provider-editor-footer">
          <div>
            <el-button size="small" :loading="busyAction === `models:${draft.id}`" :disabled="isBusy && busyAction !== `models:${draft.id}`" @click="refreshModels">刷新模型</el-button>
            <el-button size="small" :loading="busyAction === `test:${draft.id}`" :disabled="isBusy && busyAction !== `test:${draft.id}`" @click="testProvider">测试连接</el-button>
          </div>
          <div>
            <el-button size="small" :disabled="isBusy" @click="closeEditor">取消</el-button>
            <el-button size="small" type="primary" :loading="busyAction === `save:${draft.id.trim().toLowerCase()}`" :disabled="isBusy && busyAction !== `save:${draft.id.trim().toLowerCase()}`" @click="saveProvider">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm.js'
import { useTextModelProviderSettingsController } from './useTextModelProviderSettingsController.js'

const props = defineProps({
  selectedModel: { type: String, default: '' },
})
const emit = defineEmits(['update:selectedModel', 'options-updated'])

const {
  providers, modelOptions, loading, loadError, busyAction, isBusy,
  editorOpen, editingExisting, draft, draftModelsText,
  openCreate, openEdit, closeEditor, loadProviders, saveProvider,
  testProvider, refreshModels, deleteProvider, setDefaultModel,
} = useTextModelProviderSettingsController({
  notify: ElMessage,
  confirmDelete: requestDestructiveConfirmation,
  onOptionsChanged: (options) => emit('options-updated', options),
  onDefaultChanged: (selection) => emit('update:selectedModel', selection),
  getSelectedModel: () => props.selectedModel,
})

const providerLabels = computed(() => Object.fromEntries(providers.value.map((item) => [item.id, item.label])))
const groupedModelOptions = computed(() => {
  const groups = new Map()
  for (const option of modelOptions.value) {
    const provider = String(option.provider || 'other')
    if (!groups.has(provider)) groups.set(provider, { provider, label: providerLabels.value[provider] || provider, options: [] })
    groups.get(provider).options.push(option)
  }
  return [...groups.values()]
})
const currentProviderConfigured = computed(() => providers.value.find((item) => item.id === draft.id)?.configured === true)

onMounted(() => loadProviders())
</script>

<style scoped>
.text-provider-settings { display: grid; gap: var(--vk-space-cluster); }
.text-provider-default { display: grid; gap: var(--vk-space-sm); }
.text-provider-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--vk-space-cluster); }
.text-provider-toolbar p, .text-provider-form-note { margin: 0; color: var(--vk-muted); font-size: var(--vk-type-label-size); line-height: var(--vk-leading-body); }
.text-provider-list { overflow: hidden; border: 1px solid var(--vk-border); border-radius: var(--vk-radius-surface); background: var(--vk-bg-panel); }
.text-provider-row { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: var(--vk-space-cluster); padding: var(--vk-space-cluster) var(--vk-space-panel); }
.text-provider-row + .text-provider-row { border-top: 1px solid color-mix(in srgb, var(--vk-border) 70%, transparent); }
.text-provider-copy { min-width: 0; display: grid; gap: var(--vk-space-xs); }
.text-provider-title { display: flex; align-items: center; gap: var(--vk-space-control); }
.text-provider-title strong { min-width: 0; overflow: hidden; color: var(--vk-text); font-size: var(--vk-type-body-size); text-overflow: ellipsis; white-space: nowrap; }
.text-provider-copy p { margin: 0; overflow: hidden; color: var(--vk-muted); font-family: var(--vk-font-mono); font-size: var(--vk-type-meta-size); text-overflow: ellipsis; white-space: nowrap; }
.text-provider-copy > span { color: var(--vk-muted); font-size: var(--vk-type-label-size); }
.text-provider-actions { display: flex; align-items: center; gap: var(--vk-space-xs); }
.text-provider-error { display: flex; align-items: center; justify-content: space-between; gap: var(--vk-space-cluster); padding: var(--vk-space-cluster); border: 1px solid var(--vk-danger); border-radius: var(--vk-radius-surface); color: var(--vk-error-text); }
.text-provider-inline-error { color: var(--vk-error-text); font-size: var(--vk-type-label-size); }
.text-provider-inline-error button { border: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; }
.text-provider-form { display: grid; gap: var(--vk-space-sm); }
.text-provider-form > label { color: var(--vk-muted); font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-strong); }
.text-provider-capabilities { display: grid; gap: var(--vk-space-xs); padding: var(--vk-space-control) 0; }
.text-provider-editor-footer { display: flex; justify-content: space-between; gap: var(--vk-space-cluster); }
.text-provider-editor-footer > div { display: flex; gap: var(--vk-space-sm); }
@media (max-width: 720px) {
  .text-provider-toolbar, .text-provider-row, .text-provider-editor-footer { align-items: stretch; grid-template-columns: 1fr; flex-direction: column; }
  .text-provider-row { display: grid; }
  .text-provider-actions, .text-provider-editor-footer > div { justify-content: flex-start; flex-wrap: wrap; }
}
</style>
