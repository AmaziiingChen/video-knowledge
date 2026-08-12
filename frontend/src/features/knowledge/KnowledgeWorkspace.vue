<template>
  <section class="knowledge-workspace">
    <section
      ref="conversationRoot"
      class="knowledge-conversation"
      aria-live="polite"
      @scroll.passive="handleConversationScroll"
      @wheel.passive="handleConversationWheel"
      @pointerover="positionFootnotePreview"
      @focusin="positionFootnotePreview"
    >
      <div class="knowledge-conversation-content">
        <div v-if="!history.length" class="knowledge-empty">
          <template v-if="selectedSources.length">
            <strong>{{ selectedSources[0].name }}</strong>
            <span>已就绪，可以基于其中的文章提问</span>
          </template>
          <span v-else>从左侧选择一个已完成索引的知识集</span>
        </div>

        <template v-for="(item, index) in history" :key="`${item.question}:${index}`">
          <article class="knowledge-message knowledge-message-user">
            <p>{{ item.question }}</p>
          </article>

          <article class="knowledge-message knowledge-message-answer" :class="{ 'knowledge-message-new': item.pending && index === history.length - 1 }">
            <div
              v-if="item.answer"
              class="knowledge-answer report-markdown vk-prose"
              :class="{ error: item.error }"
              v-html="renderAnswer(item)"
              @click="handleAnswerFootnoteClick($event, item)"
            />
            <AiSkeletonStream
              v-else-if="item.pending"
              class="knowledge-answer knowledge-answer-skeleton"
              aria-label="AI 正在生成回答"
            />
            <p v-else class="knowledge-answer error">{{ item.error || '回答暂不可用' }}</p>
          </article>
        </template>
      </div>
      <Transition name="knowledge-footnote-return">
        <button v-if="hasFootnoteReturn" class="knowledge-footnote-return" type="button" @click="returnToFootnoteReference">
          <el-icon><ArrowUp /></el-icon><span>返回引用处</span>
        </button>
      </Transition>
    </section>

    <section class="knowledge-composer-shell">
      <Transition name="knowledge-notice">
        <p v-if="notice" class="knowledge-notice" :class="notice.kind" role="status">{{ notice.text }}</p>
      </Transition>

      <form class="knowledge-composer" @submit.prevent="ask">
        <div class="knowledge-scope" aria-label="检索范围">
          <span class="knowledge-scope-label">{{ scopeLabel }}</span>
          <span v-if="!selectedSources.length" class="knowledge-index-status">请在左栏选择一个知识集</span>
          <div class="knowledge-answer-model">
            <el-select v-model="answerModel" class="knowledge-answer-model-select" :disabled="asking" aria-label="知识问答回答模型">
              <el-option v-for="option in answerModelOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </div>
        </div>

        <div class="knowledge-composer-panel">
          <textarea
            ref="questionInput"
            v-model="question"
            name="knowledge-question"
            rows="3"
            autocomplete="off"
            :placeholder="selectedSources.length ? '基于当前知识集提问…' : '请先在左栏选择知识集'"
            :disabled="asking || !selectedSources.length"
            @keydown.enter.exact.prevent="triggerQuestionSend"
          />
          <div class="knowledge-composer-actions">
            <div class="knowledge-composer-context-actions">
              <el-tooltip content="开启新对话" placement="top">
                <button class="knowledge-new-chat" type="button" aria-label="开启新对话" :disabled="asking || !history.length" @click="startNewChat">
                  <SvgMaskIcon :src="newChatIcon" :size="18" />
                </button>
              </el-tooltip>
              <el-tooltip content="导出当前知识库对话为 Markdown" placement="top">
                <button class="knowledge-export-chat" :class="{ loading: exportingMarkdown }" type="button" aria-label="导出当前知识库对话为 Markdown" :disabled="exportingMarkdown || !hasExportableConversation" @click="exportConversationMarkdown">
                  <SvgMaskIcon :src="exportIcon" :size="18" />
                </button>
              </el-tooltip>
            </div>
            <button class="knowledge-send-button vk-ai-send-button" :class="{ active: question.trim() && selectedSources.length, 'is-launching': sendLaunchActive }" type="submit" aria-label="发送" :disabled="asking || !question.trim() || !selectedSources.length">
              <SvgMaskIcon class="vk-ai-send-icon" :src="sendIcon" :size="16" />
            </button>
          </div>
        </div>
      </form>
    </section>

  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowUp } from '../../components/macosSymbolComponents.js'
import AiSkeletonStream from '../../components/AiSkeletonStream.vue'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'
const newChatIcon = 'ellipsis.bubble'
const exportIcon = 'arrow.down.document'
const sendIcon = 'custom.paperplane.fill'
import { useMarkdownFootnoteNavigation } from '../../composables/useMarkdownFootnoteNavigation'
import { renderMarkdown } from '../../utils/viewFormatters'
import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../../utils/localApiAuth.js'
import { createQaStreamRenderer } from '../assistant/qaStreamRenderer'
import { knowledgeAnswerMarkdown } from './knowledgeAnswerMarkdown'

const emit = defineEmits(['conversation-activated', 'conversation-saved', 'conversation-usage-changed', 'navigation-changed', 'open-evidence', 'export-markdown'])
const selectedSources = ref([])
const scopeLabel = computed(() => selectedSources.value.length
  ? selectionLabel(selectedSources.value[0])
  : '未选择知识集')
const question = ref('')
const history = ref([])
const activeConversationId = ref('')
const asking = ref(false)
const ANSWER_MODEL_STORAGE_KEY = 'knowledgehub:knowledge-answer-model:v1'
const answerModelOptions = [
  { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { value: 'deepseek-v4-pro', label: 'deepseek-v4-pro' },
]
const answerModel = ref(readKnowledgeAnswerModel())
const exportingMarkdown = ref(false)
const notice = ref(null)
const conversationRoot = ref(null)
const questionInput = ref(null)
const conversationAutoFollow = ref(true)
const conversationUsage = ref(emptyUsage())
const sendLaunchActive = ref(false)
const CONVERSATION_BOTTOM_THRESHOLD = 56
let conversationScrollFrame = null
let sendLaunchTimer = null
const hasExportableConversation = computed(() => history.value.some((item) => item?.question || item?.answer))
const {
  clearFootnoteReturn,
  handleFootnoteClick,
  hasFootnoteReturn,
  positionFootnotePreview,
  returnToFootnoteReference,
} = useMarkdownFootnoteNavigation({
  scrollRoot: conversationRoot,
  scopeKey: () => activeConversationId.value,
})

async function openConversation(conversationId) {
  if (asking.value || conversationId === activeConversationId.value) return
  try {
    const response = await fetch(localApiRequestUrl(`${API}/knowledge/conversations/${encodeURIComponent(conversationId)}`), {
      headers: await localApiAuthHeaders(),
    })
    const data = await response.json()
    if (!response.ok) throw Error(data.detail || '无法读取知识库对话')
    activeConversationId.value = data.id
    emit('conversation-activated', data.id)
    const scope = data.scope || {}
    if (scope.version === 'v2' && Array.isArray(scope.sources)) {
      selectedSources.value = scope.sources.slice(0, 1).map((item) => ({
        id: `${item.provider}:${item.name}`,
        provider: item.provider,
        name: item.name,
        document_ids: scope.document_ids || [],
        excluded_document_ids: scope.excluded_document_ids || [],
        selectable: true,
      }))
    }
    history.value = messagesToHistory(data.messages || [])
    setConversationUsage(data.usage)
    resumeConversationAutoFollow()
  } catch (error) {
    notice.value = { kind: 'error', text: error.message || '无法读取知识库对话' }
  }
}

function messagesToHistory(messages) {
  const exchanges = []
  for (const message of messages) {
    if (message.role === 'user') exchanges.push({ question: message.content, answer: '', citations: [], error: '', pending: false })
    else if (exchanges.length) Object.assign(exchanges.at(-1), { answer: message.content, citations: message.citations || [], error: message.error || '', pending: false })
  }
  return exchanges
}

async function ask() {
  if (asking.value || !question.value.trim() || !selectedSources.value.length) return
  const item = { question: question.value.trim(), answer: '', citations: [], error: '', pending: true }
  history.value.push(item)
  question.value = ''
  asking.value = true
  resumeConversationAutoFollow()
  try {
    const response = await fetch(localApiRequestUrl(`${API}/knowledge/v2/query/stream`), {
      method: 'POST',
      headers: await localApiAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        question: item.question,
        sources: selectedSources.value.slice(0, 1).map(({ provider, name }) => ({ provider, name })),
        document_ids: selectedSources.value[0]?.document_ids || null,
        excluded_document_ids: selectedSources.value[0]?.excluded_document_ids || null,
        conversation_id: activeConversationId.value || null,
        answer_model: answerModel.value,
      })
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw Error(data.detail || '提问失败')
    }
    await readKnowledgeStream(response, item)
  } catch (error) {
    item.error = error.message || '提问失败'
  } finally {
    item.pending = false
    asking.value = false
    history.value = [...history.value]
    emit('conversation-saved')
  }
}

async function readKnowledgeStream(response, item) {
  const reader = response.body?.getReader()
  if (!reader) throw Error('浏览器不支持流式响应')
  const decoder = new TextDecoder()
  let buffer = ''
  let doneData = null
  const streamRenderer = createQaStreamRenderer({
    getRenderedLength: () => item.answer.length,
    onCommit: (text) => {
      item.answer += text
      history.value = [...history.value]
    },
  })
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) doneData = handleKnowledgeStreamBlock(block, item, streamRenderer, doneData)
    }
    buffer += decoder.decode()
    if (buffer.trim()) doneData = handleKnowledgeStreamBlock(buffer, item, streamRenderer, doneData)
    await streamRenderer.drain()
    if (!doneData) throw Error('AI 流式响应提前结束，请重试')
    item.answer = String(doneData.answer || item.answer)
    item.citations = Array.isArray(doneData.citations) ? doneData.citations : []
    if (doneData.conversation_id) {
      activeConversationId.value = String(doneData.conversation_id)
      emit('conversation-activated', activeConversationId.value)
    }
    setConversationUsage(doneData.usage)
  } catch (error) {
    streamRenderer.flush()
    throw error
  }
}

function handleKnowledgeStreamBlock(block, item, streamRenderer, doneData) {
  const lines = block.split('\n')
  const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
  const dataLine = lines.find((line) => line.startsWith('data:'))
  if (!dataLine) return doneData
  const data = JSON.parse(dataLine.slice(5).trim())
  if (event === 'delta') {
    streamRenderer.enqueue(data.text || '')
    return doneData
  }
  if (event === 'replace') {
    streamRenderer.flush()
    item.answer = String(data.text || '')
    history.value = [...history.value]
    return doneData
  }
  if (event === 'done') return data
  if (event === 'error') throw Error(data.error || '提问失败')
  return doneData
}

function startNewChat() {
  if (asking.value) return
  history.value = []
  activeConversationId.value = ''
  emit('conversation-activated', '')
  setConversationUsage()
  clearFootnoteReturn()
  conversationAutoFollow.value = true
  nextTick(() => questionInput.value?.focus())
}

function readKnowledgeAnswerModel() {
  try {
    const stored = window.localStorage.getItem(ANSWER_MODEL_STORAGE_KEY)
    if (answerModelOptions.some((option) => option.value === stored)) return stored
  } catch {
    // Storage can be unavailable in a restricted desktop webview.
  }
  return 'deepseek-v4-pro'
}

function triggerQuestionSend() {
  if (asking.value || !question.value.trim() || !selectedSources.value.length) return
  sendLaunchActive.value = false
  requestAnimationFrame(() => {
    sendLaunchActive.value = true
  })
  if (sendLaunchTimer !== null) clearTimeout(sendLaunchTimer)
  sendLaunchTimer = window.setTimeout(() => {
    sendLaunchActive.value = false
    sendLaunchTimer = null
  }, 600)
  ask()
}

function exportConversationMarkdown() {
  if (exportingMarkdown.value || !hasExportableConversation.value) return
  const scope = selectedSources.value[0]
  const title = String(history.value[0]?.question || scope?.name || '知识库对话').replace(/\r?\n/gu, ' ').trim()
  const sections = [`# ${title}`]
  if (scope) sections.push(`知识集：${selectionLabel(scope)}`)
  const exchanges = history.value
    .filter((item) => String(item?.question || '').trim() || String(item?.answer || '').trim())
    .map((item) => {
      const question = String(item.question || '').trim()
      const answer = String(item.answer || '').trim() || '（尚未生成回答）'
      const sources = (item.citations || []).map((citation) => {
        const sourceTitle = String(citation.title || '未命名文章').trim()
        const sourceUrl = String(citation.source_url || '').trim()
        const sourceMeta = [citation.source_label, citation.published_at].filter(Boolean).join(' · ')
        return `- ${sourceUrl ? `[${sourceTitle}](<${sourceUrl}>)` : sourceTitle}${sourceMeta ? ` · ${sourceMeta}` : ''}`
      })
      return [
        '## 问题', question,
        '## 回答', answer,
        ...(sources.length ? ['### 引用来源', sources.join('\n')] : []),
      ].join('\n\n')
    })
  sections.push(exchanges.join('\n\n---\n\n'))
  exportingMarkdown.value = true
  emit('export-markdown', {
    title: `${title}-知识库对话`,
    markdown: `${sections.join('\n\n')}\n`,
    complete: () => { exportingMarkdown.value = false },
  })
}

function emptyUsage() {
  return {
    call_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 0,
    estimated_cost: 0,
    unreported_count: 0,
  }
}

function setConversationUsage(value) {
  const base = emptyUsage()
  for (const key of Object.keys(base)) {
    const parsed = Number(value?.[key])
    base[key] = Number.isFinite(parsed) && parsed >= 0 ? parsed : base[key]
  }
  conversationUsage.value = base
  emit('conversation-usage-changed', base)
}

function setKnowledgeScope(scope) {
  selectedSources.value = scope ? [{ ...scope }] : []
  if (history.value.length) startNewChat()
}

function selectionLabel(scope) {
  const included = scope.document_ids || []
  const excluded = scope.excluded_document_ids || []
  if (included.length) return `当前知识集：${scope.name} · ${included.length} 篇文章`
  if (excluded.length) return `当前知识集：${scope.name} · 已排除 ${excluded.length} 篇`
  return `当前知识集：${scope.name} · 全部文章`
}

function renderAnswer(item) {
  return renderMarkdown(knowledgeAnswerMarkdown(item.answer, item.citations))
}

function handleAnswerFootnoteClick(event, item) {
  const targetId = handleFootnoteClick(event)
  if (!targetId) return
  const citation = (item.citations || []).find((candidate) => {
    const identifier = String(candidate.evidence_id || candidate.citation_id || '')
    return identifier && targetId.endsWith(`-${identifier}`)
  })
  if (citation?.chunk_id) emit('open-evidence', citation.chunk_id)
}

function conversationDistanceFromBottom(container) {
  return Math.max(0, container.scrollHeight - container.clientHeight - container.scrollTop)
}

function handleConversationWheel(event) {
  if (event.deltaY < 0) conversationAutoFollow.value = false
}

function handleConversationScroll() {
  const container = conversationRoot.value
  if (!container) return
  conversationAutoFollow.value = conversationDistanceFromBottom(container) <= CONVERSATION_BOTTOM_THRESHOLD
}

function scrollConversationToBottom({ force = false } = {}) {
  if (!force && !conversationAutoFollow.value) return
  if (conversationScrollFrame !== null) cancelAnimationFrame(conversationScrollFrame)
  conversationScrollFrame = requestAnimationFrame(() => {
    conversationScrollFrame = null
    const container = conversationRoot.value
    if (!container || (!force && !conversationAutoFollow.value)) return
    container.scrollTo({ top: container.scrollHeight, behavior: 'auto' })
  })
}

function resumeConversationAutoFollow() {
  conversationAutoFollow.value = true
  nextTick(() => scrollConversationToBottom({ force: true }))
}

watch(
  () => [history.value.length, history.value.at(-1)?.answer?.length || 0, history.value.at(-1)?.pending || false],
  () => {
    if (!conversationAutoFollow.value) return
    nextTick(() => scrollConversationToBottom())
  }
)

watch(answerModel, (model) => {
  try {
    window.localStorage.setItem(ANSWER_MODEL_STORAGE_KEY, model)
  } catch {
    // The current session still keeps the selected model when storage is unavailable.
  }
})

onBeforeUnmount(() => {
  if (conversationScrollFrame !== null) cancelAnimationFrame(conversationScrollFrame)
  if (sendLaunchTimer !== null) clearTimeout(sendLaunchTimer)
})

defineExpose({ openConversation, setKnowledgeScope, selectedSources })
</script>

<style scoped>
.knowledge-workspace {
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  min-width: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  overflow: hidden;
  box-sizing: border-box;
  background: var(--vk-bg);
  color: var(--vk-text);
}

.knowledge-conversation {
  position: relative;
  width: 100%;
  min-height: 0;
  min-width: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.knowledge-footnote-return {
  position: absolute;
  right: var(--vk-space-panel);
  bottom: var(--vk-space-panel);
  z-index: 7;
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-xs);
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 76%, transparent);
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-bg-panel) 86%, transparent);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
  backdrop-filter: blur(18px) saturate(1.15);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  font-weight: 600;
  cursor: pointer;
}
.knowledge-footnote-return:hover, .knowledge-footnote-return:focus-visible { outline: none; border-color: color-mix(in srgb, var(--vk-accent) 44%, var(--vk-border)); background: var(--vk-bg-panel); color: var(--vk-accent-strong); }
.knowledge-footnote-return:focus-visible { box-shadow: var(--vk-focus-ring), 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent); }
.knowledge-footnote-return-enter-active, .knowledge-footnote-return-leave-active { transition: opacity 180ms var(--vk-ease-out), transform 280ms cubic-bezier(0.22, 1, 0.36, 1); }
.knowledge-footnote-return-enter-from, .knowledge-footnote-return-leave-to { opacity: 0; transform: translateY(6px) scale(0.96); }

.knowledge-conversation-content {
  width: min(calc(100% - clamp(36px, 8vw, 140px)), 920px);
  max-width: 100%;
  min-height: 100%;
  margin: 0 auto;
  padding: clamp(28px, 5vh, 68px) 0 42px;
  box-sizing: border-box;
}

.knowledge-empty {
  min-height: min(42vh, 360px);
  display: grid;
  place-items: center;
  color: color-mix(in srgb, var(--vk-muted) 68%, transparent);
  font-size: 13px;
  letter-spacing: .01em;
}

.knowledge-message {
  max-width: min(100%, 800px);
  margin: 0 0 28px;
}

.knowledge-message-user {
  width: fit-content;
  max-width: min(78%, 660px);
  margin-left: auto;
  padding: 10px 13px;
  border: 0;
  border-radius: 12px;
  background: color-mix(in srgb, var(--vk-text) 5%, var(--vk-bg-panel));
  color: var(--vk-text);
  box-shadow: none;
}

.knowledge-message-user p { margin: 0; font-size: 15px; line-height: 1.58; white-space: pre-wrap; }


.knowledge-message-answer { padding: 1px 4px 0; }

.knowledge-message-new {
  animation: knowledge-answer-arrive var(--vk-motion-standard) var(--vk-ease-out) both;
}

.knowledge-answer {
  min-width: 0;
  color: var(--vk-text);
  font-size: var(--vk-type-reading-size);
  line-height: 1.74;
}

.knowledge-answer.error { color: var(--vk-error-text); }

.knowledge-answer :deep(p:first-child) { margin-top: 0; }
.knowledge-answer :deep(p:last-child) { margin-bottom: 0; }
.knowledge-answer :deep(h1), .knowledge-answer :deep(h2), .knowledge-answer :deep(h3) { letter-spacing: var(--vk-tracking-heading); }
.knowledge-answer :deep(h2) { margin: 1.25em 0 .55em; font-size: var(--vk-type-prose-h2-size); }
.knowledge-answer :deep(h3) { margin: 1.15em 0 .5em; font-size: var(--vk-type-prose-h3-size); }
.knowledge-answer :deep(ul), .knowledge-answer :deep(ol) { padding-left: 1.4em; }
.knowledge-answer :deep(table) { width: 100%; margin: 12px 0; border-spacing: 0; border-top: 1px solid var(--vk-border); border-bottom: 1px solid var(--vk-border); font-size: var(--vk-type-body-size); }
.knowledge-answer :deep(th), .knowledge-answer :deep(td) { padding: 8px 10px; border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 60%, transparent); text-align: left; vertical-align: top; }
.knowledge-answer :deep(tr:last-child td) { border-bottom: 0; }

.knowledge-answer-skeleton {
  --ai-skeleton-stream-width: min(100%, 460px);
  --ai-skeleton-stream-padding: 4px 0 0;
}

.knowledge-composer-shell {
  position: relative;
  z-index: 5;
  width: min(calc(100% - clamp(24px, 6vw, 96px)), 920px);
  max-width: 100%;
  min-width: 0;
  margin: 0 auto;
  padding: 10px 0 clamp(16px, 2.5vh, 28px);
}

.knowledge-notice {
  width: fit-content;
  max-width: min(100%, 620px);
  margin: 0 0 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--vk-bg-panel);
  box-shadow: 0 5px 16px color-mix(in srgb, var(--vk-text) 7%, transparent);
  font-size: 12px;
  line-height: 1.45;
}

.knowledge-notice.success { color: var(--el-color-success); }
.knowledge-notice.warning { color: var(--el-color-warning); }
.knowledge-notice.error { color: var(--el-color-danger); }

.knowledge-composer {
  display: grid;
  gap: 7px;
}

.knowledge-scope {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  padding: 0 3px;
}

.knowledge-scope-select { width: min(210px, 30vw); flex: 1 1 156px; }
.knowledge-scope-spacer { flex: 1 1 12px; min-width: 0; }
.knowledge-index-status { flex: 0 0 auto; color: var(--vk-muted); font-size: 11px; white-space: nowrap; }

.knowledge-answer-model {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  min-width: 0;
  margin-left: auto;
}

.knowledge-answer-model-select { width: min(168px, 40vw); }

.knowledge-scope :deep(.el-select__wrapper) {
  min-height: 28px;
  border-radius: 999px;
  box-shadow: none !important;
  background: color-mix(in srgb, var(--vk-bg-panel) 88%, transparent);
}

.knowledge-scope :deep(.el-select__selected-item), .knowledge-scope :deep(.el-select__placeholder) { font-size: 12px; }

.knowledge-tool-button, .el-dialog__footer button {
  min-height: 28px;
  padding: 0 9px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.knowledge-tool-button:hover:not(:disabled), .el-dialog__footer button:hover:not(:disabled) { background: var(--vk-bg-hover); color: var(--vk-text); }
.knowledge-tool-button:disabled, .el-dialog__footer button:disabled { opacity: .45; cursor: default; }

.knowledge-composer-panel {
  position: relative;
  padding: 11px 12px 12px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--vk-bg-panel) 88%, transparent);
  box-shadow: 0 10px 28px color-mix(in srgb, var(--vk-text) 9%, transparent);
  backdrop-filter: blur(16px) saturate(135%);
  -webkit-backdrop-filter: blur(16px) saturate(135%);
  transition: border-color var(--vk-motion-fast) var(--vk-ease-out), box-shadow var(--vk-motion-fast) var(--vk-ease-out);
}

.knowledge-composer textarea {
  width: 100%;
  min-height: 58px;
  max-height: 180px;
  padding: 0 0 34px;
  border: 0;
  outline: 0;
  resize: none;
  box-sizing: border-box;
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: 15px;
  line-height: 1.58;
}

.knowledge-composer textarea::placeholder { color: color-mix(in srgb, var(--vk-muted) 68%, transparent); }

.knowledge-composer-actions {
  position: absolute;
  right: 10px;
  bottom: 10px;
  left: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  pointer-events: none;
}

.knowledge-composer-actions > * { pointer-events: auto; }

.knowledge-composer-context-actions { display: flex; align-items: center; gap: var(--vk-space-xs); }

.knowledge-new-chat, .knowledge-export-chat {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
}

.knowledge-new-chat:hover:not(:disabled), .knowledge-export-chat:hover:not(:disabled) { background: var(--vk-bg-hover); color: var(--vk-text); }
.knowledge-new-chat:disabled, .knowledge-export-chat:disabled { opacity: .4; cursor: default; }
.knowledge-export-chat.loading :deep(.svg-mask-icon) { animation: knowledge-export-pulse .95s ease-in-out infinite alternate; }

@keyframes knowledge-export-pulse { from { opacity: .45; transform: scale(.9); } to { opacity: 1; transform: scale(1); } }

.knowledge-notice-enter-active, .knowledge-notice-leave-active { transition: opacity var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out); }
.knowledge-notice-enter-from, .knowledge-notice-leave-to { opacity: 0; transform: translateY(3px); }

@keyframes knowledge-answer-arrive { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) {
  .knowledge-message-new, .knowledge-notice-enter-active, .knowledge-notice-leave-active { animation: none; transition: opacity var(--vk-motion-fast) ease; }
}

@media (prefers-reduced-transparency: reduce) {
  .knowledge-composer-panel { background: var(--vk-bg-panel); backdrop-filter: none; -webkit-backdrop-filter: none; }
}

@media (max-width: 720px) {
  .knowledge-conversation-content { width: min(calc(100% - 32px), 920px); padding-top: 28px; }
  .knowledge-composer-shell { width: min(calc(100% - 20px), 920px); }
  .knowledge-scope { overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
  .knowledge-scope::-webkit-scrollbar { display: none; }
  .knowledge-scope-select { width: 164px; flex: 0 0 164px; }
  .knowledge-answer-model-select { width: 148px; }
  .knowledge-scope-spacer { display: none; }
  .knowledge-tool-button { flex: 0 0 auto; }
  .knowledge-message-user { max-width: 88%; }
}
</style>
