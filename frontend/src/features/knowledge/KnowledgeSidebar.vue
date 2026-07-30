<template>
  <aside class="knowledge-sidebar" aria-label="知识集导航">
    <div class="knowledge-sidebar-tree">
      <SidebarTreeRow kind="folder" label="可问答知识集" :meta="String(readySourceSets.length)" :open="setsOpen" tone="strong" @activate="setsOpen = !setsOpen" />
      <template v-if="setsOpen">
        <template v-for="source in readySourceSets" :key="source.id">
          <SidebarTreeRow
            kind="folder"
            :label="source.name"
            :meta="sourceMeta(source)"
            :depth="1"
            :open="expandedSourceIds.has(source.id)"
            :selected="sourceCheckState(source) !== 'unchecked'"
            :check-state="sourceCheckState(source)"
            :check-label="sourceCheckState(source) === 'checked' ? `取消选择知识集 ${source.name}` : `选择知识集 ${source.name} 的全部文章`"
            :aria-label="`展开知识集 ${source.name}`"
            @activate="toggleSourceFolder(source)"
            @toggle-check="toggleSourceAll(source)"
          />
          <template v-if="expandedSourceIds.has(source.id)">
            <SidebarTreeRow
              v-for="document in sourceDocuments(source)"
              :key="document.id"
              kind="file"
              :label="document.title"
              :label-title="document.title"
              :meta="formatDocumentDate(document.published_at)"
              :icon="libraryContentIcon(document)"
              :depth="2"
              :selected="documentCheckState(source, document) === 'checked'"
              :check-state="documentCheckState(source, document)"
              :check-label="documentCheckState(source, document) === 'checked' ? `取消选择文章 ${document.title}` : `选择文章 ${document.title}`"
              :aria-label="`选择文章 ${document.title}`"
              @activate="toggleDocument(source, document)"
              @toggle-check="toggleDocument(source, document)"
            />
            <p v-if="isLoadingDocuments(source)" class="knowledge-sidebar-loading">正在读取已索引文章…</p>
            <button v-else-if="nextDocumentOffset(source) !== null" class="knowledge-sidebar-more" type="button" @click="loadDocuments(source)">显示更多文章</button>
            <p v-else-if="!sourceDocuments(source).length" class="knowledge-sidebar-empty">没有可展示的已索引文章。</p>
          </template>
        </template>
        <p v-if="!readySourceSets.length" class="knowledge-sidebar-empty">还没有完成索引的知识集。</p>
      </template>

      <SidebarTreeRow kind="folder" label="对话记录" :meta="String(conversations.length)" :open="conversationsOpen" tone="strong" @activate="conversationsOpen = !conversationsOpen" />
      <template v-if="conversationsOpen">
        <SidebarTreeRow
          v-for="conversation in conversations"
          :key="conversation.id"
          kind="file"
          :label="conversation.title"
          :meta="formatConversationTime(conversation.updated_at)"
          :depth="1"
          :active="activeConversationId === conversation.id"
          @activate="emit('open-conversation', conversation.id)"
        />
        <p v-if="!conversations.length" class="knowledge-sidebar-empty">还没有保存的知识库对话。</p>
      </template>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import SidebarTreeRow from '../../workbench/SidebarTreeRow.vue'
import { libraryContentIcon } from '../../utils/contentIcons'

const API = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api'
const props = defineProps({ activeConversationId: { type: String, default: '' }, selectedSources: { type: Array, default: () => [] } })
const emit = defineEmits(['open-conversation', 'select-scope'])
const sourceSets = ref([])
const conversations = ref([])
const setsOpen = ref(true)
const conversationsOpen = ref(true)
const expandedSourceIds = ref(new Set())
const documentsBySource = ref({})
const loadingSourceIds = ref(new Set())
const selectedScope = computed(() => props.selectedSources[0] || null)
const readySourceSets = computed(() => sourceSets.value.filter((source) => source.selectable))

onMounted(refresh)

async function refresh() {
  const [setsResponse, conversationsResponse] = await Promise.all([
    fetch(`${API}/knowledge/v2/source-sets`),
    fetch(`${API}/knowledge/conversations`),
  ])
  if (setsResponse.ok) sourceSets.value = (await setsResponse.json()).items || []
  if (conversationsResponse.ok) {
    conversations.value = ((await conversationsResponse.json()).items || []).filter((item) => item.scope?.version === 'v2')
  }
}

function sourceMeta(source) {
  return String(sourceCheckState(source) === 'indeterminate'
    ? selectedDocumentCount(source)
    : (source.document_count || 0))
}

function sourceDocuments(source) {
  return documentsBySource.value[source.id]?.items || []
}

function nextDocumentOffset(source) {
  return documentsBySource.value[source.id]?.nextOffset ?? null
}

function isLoadingDocuments(source) {
  return loadingSourceIds.value.has(source.id)
}

function scopeMatches(source) {
  const current = selectedScope.value
  return Boolean(current && current.id === source.id)
}

function sourceCheckState(source) {
  if (!scopeMatches(source)) return 'unchecked'
  const current = selectedScope.value
  if ((current.document_ids || []).length || (current.excluded_document_ids || []).length) return 'indeterminate'
  return 'checked'
}

function documentCheckState(source, document) {
  if (!scopeMatches(source)) return 'unchecked'
  const current = selectedScope.value
  const included = current.document_ids || []
  const excluded = current.excluded_document_ids || []
  if (included.length) return included.includes(document.id) ? 'checked' : 'unchecked'
  return excluded.includes(document.id) ? 'unchecked' : 'checked'
}

function selectedDocumentCount(source) {
  if (!scopeMatches(source)) return 0
  const current = selectedScope.value
  if ((current.document_ids || []).length) return current.document_ids.length
  if ((current.excluded_document_ids || []).length) return Math.max(0, Number(source.document_count || 0) - current.excluded_document_ids.length)
  return Number(source.document_count || 0)
}

async function toggleSourceFolder(source) {
  const next = new Set(expandedSourceIds.value)
  if (next.has(source.id)) {
    next.delete(source.id)
  } else {
    next.add(source.id)
    if (!documentsBySource.value[source.id]) await loadDocuments(source, { reset: true })
  }
  expandedSourceIds.value = next
}

async function loadDocuments(source, { reset = false } = {}) {
  if (isLoadingDocuments(source)) return
  const cached = documentsBySource.value[source.id]
  const offset = reset ? 0 : (cached?.nextOffset ?? 0)
  if (!reset && cached && cached.nextOffset === null) return
  const nextLoading = new Set(loadingSourceIds.value)
  nextLoading.add(source.id)
  loadingSourceIds.value = nextLoading
  try {
    const params = new URLSearchParams({ provider: source.provider, name: source.name, limit: '200', offset: String(offset) })
    const response = await fetch(`${API}/knowledge/v2/source-documents?${params}`)
    if (!response.ok) throw Error('无法读取知识集文章')
    const payload = await response.json()
    const previous = reset ? [] : (cached?.items || [])
    documentsBySource.value = {
      ...documentsBySource.value,
      [source.id]: { items: [...previous, ...(payload.items || [])], nextOffset: payload.next_offset ?? null },
    }
  } finally {
    const nextLoading = new Set(loadingSourceIds.value)
    nextLoading.delete(source.id)
    loadingSourceIds.value = nextLoading
  }
}

function toggleSourceAll(source) {
  if (sourceCheckState(source) === 'checked') {
    emit('select-scope', null)
    return
  }
  emit('select-scope', { ...source, document_ids: [], excluded_document_ids: [] })
}

function toggleDocument(source, document) {
  const current = scopeMatches(source) ? selectedScope.value : null
  if (!current) {
    emit('select-scope', { ...source, document_ids: [document.id], excluded_document_ids: [] })
    return
  }
  const included = [...(current.document_ids || [])]
  const excluded = [...(current.excluded_document_ids || [])]
  if (included.length) {
    const next = included.includes(document.id) ? included.filter((id) => id !== document.id) : [...included, document.id]
    emit('select-scope', next.length ? { ...source, document_ids: next, excluded_document_ids: [] } : null)
    return
  }
  const nextExcluded = excluded.includes(document.id) ? excluded.filter((id) => id !== document.id) : [...excluded, document.id]
  emit('select-scope', { ...source, document_ids: [], excluded_document_ids: nextExcluded })
}

function formatConversationTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

function formatDocumentDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

defineExpose({ refresh })
</script>

<style scoped>
.knowledge-sidebar { width: 100%; height: 100%; min-height: 0; overflow: hidden; background: var(--vk-bg-quiet); }
.knowledge-sidebar-tree { height: 100%; overflow-y: auto; padding: var(--vk-space-xs, 4px) 0 var(--vk-space-panel, 14px); }
.knowledge-sidebar-empty, .knowledge-sidebar-loading { margin: 4px 14px 10px 46px; color: var(--vk-muted); font-size: var(--vk-type-meta-size); line-height: 1.45; }
.knowledge-sidebar-loading { color: var(--vk-accent-strong); }
.knowledge-sidebar-more { margin: 3px 14px 9px 46px; padding: 0; border: 0; background: transparent; color: var(--vk-accent-strong); font: inherit; font-size: var(--vk-type-meta-size); cursor: pointer; }
.knowledge-sidebar-more:hover, .knowledge-sidebar-more:focus-visible { color: var(--vk-text); text-decoration: underline; outline: none; }
</style>
