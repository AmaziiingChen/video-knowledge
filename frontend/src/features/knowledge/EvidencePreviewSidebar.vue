<template>
  <aside class="evidence-preview" aria-label="引用文章预览">
    <template v-if="evidence">
      <article class="evidence-reader">
        <div class="evidence-reader-head">
          <div class="evidence-reader-heading">
            <h2>{{ evidence.title || '未选择引用' }}</h2>
            <p class="evidence-reader-meta">
              <span>{{ evidence.source_label || '未知来源' }}</span>
              <span>{{ evidence.published_at || '日期未知' }}</span>
            </p>
          </div>
        </div>
      </article>
      <article class="evidence-preview-body">
        <div v-if="loadingSource" class="evidence-preview-status">正在载入原文…</div>
        <div v-else-if="sourceError" class="evidence-preview-status is-error">{{ sourceError }}</div>
        <iframe
          v-else-if="previewHtml"
          ref="previewFrame"
          class="evidence-preview-frame"
          :srcdoc="previewHtml"
          sandbox="allow-same-origin"
          referrerpolicy="no-referrer"
          title="引用原文预览"
          @load="handlePreviewFrameReady"
        />
        <div v-else class="evidence-preview-status">原文暂不可预览</div>
      </article>
      <div class="evidence-overlay-actions" :class="{ 'is-suppressed': previewFindOpen }">
        <el-popover
          v-model:visible="contentActionsOpen"
          placement="bottom-end"
          :width="240"
          trigger="hover"
          :show-after="90"
          :hide-after="180"
          :show-arrow="false"
          transition="content-action-pop"
          popper-class="content-action-popover"
        >
          <template #reference>
            <button class="content-fact-button" type="button" aria-label="内容操作">
              <SvgMaskIcon :src="ellipsisIcon" :size="15" />
            </button>
          </template>
          <div class="content-action-menu">
            <div class="content-action-menu-heading">内容操作</div>
            <button v-if="evidence.source_url" type="button" @click="copySourceLink">复制原链接</button>
            <button v-if="evidence.source_url" type="button" @click="openSourceLink">在外部浏览器打开</button>
          </div>
        </el-popover>
      </div>
      <PreviewFindBar
        :available="Boolean(previewHtml)"
        :open="previewFindOpen"
        :query="previewFindQuery"
        :match-count="previewFindMatchCount"
        :active-match-index="previewFindActiveIndex"
        :truncated="previewFindTruncated"
        :focus-request="previewFindFocusRequest"
        @update:query="updatePreviewFindQuery"
        @previous="navigatePreviewFind(-1)"
        @next="navigatePreviewFind(1)"
        @open="openPreviewFind"
        @close="closePreviewFind"
      />
    </template>
    <div v-else class="evidence-preview-status">未选择引用原文</div>
  </aside>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'
import PreviewFindBar from '../../workbench/PreviewFindBar.vue'
import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../../utils/localApiAuth.js'
const ellipsisIcon = 'ellipsis'
import { clearPreviewTextHighlights, highlightPreviewText } from '../../utils/previewTextSearch'

const props = defineProps({ evidence: { type: Object, default: null } })
const previewFrame = ref(null)
const previewHtml = ref('')
const sourceError = ref('')
const loadingSource = ref(false)
const contentActionsOpen = ref(false)
const previewFindOpen = ref(false)
const previewFindQuery = ref('')
const previewFindMatchCount = ref(0)
const previewFindActiveIndex = ref(-1)
const previewFindTruncated = ref(false)
const previewFindFocusRequest = ref(0)
let previewRequest = 0
let previewFindMatches = []
let previewFindHighlightRoot = null
let previewFindRestoreFocus = null

watch(
  () => `${props.evidence?.content_item_id || ''}:${props.evidence?.chunk_id || ''}`,
  async (contentItemId) => {
    const [itemId] = String(contentItemId).split(':')
    const request = ++previewRequest
    previewHtml.value = ''
    sourceError.value = ''
    resetPreviewFind()
    if (!itemId) return
    loadingSource.value = true
    try {
      const response = await fetch(localApiRequestUrl(`${API}/content/${encodeURIComponent(itemId)}/article-preview`), {
        headers: await localApiAuthHeaders(),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw Error(payload.detail || '原文暂不可预览')
      if (request !== previewRequest) return
      previewHtml.value = String(payload.html || '')
    } catch (error) {
      if (request !== previewRequest) return
      sourceError.value = error.message || '原文暂不可预览'
    } finally {
      if (request === previewRequest) loadingSource.value = false
    }
  },
  { immediate: true },
)

function normalizedText(value) {
  return String(value || '').replace(/[\s\u00a0]+/g, ' ').trim()
}

function highlightNeedle(value) {
  const source = normalizedText(value)
  if (!source) return ''
  const sentence = source.match(/^.{18,160}?(?:[。！？；.!?;]|$)/u)?.[0] || source.slice(0, 120)
  return sentence.trim()
}

function highlightEvidence() {
  const frameDocument = previewFrame.value?.contentDocument
  const needle = highlightNeedle(props.evidence?.child_text)
  if (!frameDocument?.body || !needle) return
  const nodes = []
  const showText = frameDocument.defaultView?.NodeFilter?.SHOW_TEXT || NodeFilter.SHOW_TEXT
  const walker = frameDocument.createTreeWalker(frameDocument.body, showText)
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (normalizedText(node.textContent)) nodes.push(node)
  }
  let text = ''
  const positions = []
  for (const node of nodes) {
    for (let offset = 0; offset < node.textContent.length; offset += 1) {
      const character = node.textContent[offset]
      if (/\s/u.test(character)) {
        if (text.endsWith(' ')) continue
        text += ' '
      } else {
        text += character
      }
      positions.push({ node, offset })
    }
  }
  const start = text.indexOf(needle)
  if (start < 0 || !positions[start] || !positions[start + needle.length - 1]) return
  const range = frameDocument.createRange()
  const finish = positions[start + needle.length - 1]
  range.setStart(positions[start].node, positions[start].offset)
  range.setEnd(finish.node, finish.offset + 1)
  const mark = frameDocument.createElement('mark')
  mark.className = 'knowledge-evidence-highlight'
  try {
    range.surroundContents(mark)
  } catch {
    const fragment = range.extractContents()
    mark.append(fragment)
    range.insertNode(mark)
  }
  const style = frameDocument.createElement('style')
  const rootStyle = getComputedStyle(document.documentElement)
  const accent = rootStyle.getPropertyValue('--vk-accent').trim()
  const accentStrong = rootStyle.getPropertyValue('--vk-accent-strong').trim()
  style.textContent = `.knowledge-evidence-highlight { padding: .04em .12em; border-radius: 3px; background: color-mix(in srgb, ${accent} 18%, transparent); box-shadow: inset 0 -1px 0 color-mix(in srgb, ${accentStrong} 52%, transparent); color: inherit; font-weight: 650; }`
  frameDocument.head.append(style)
  nextTick(() => mark.scrollIntoView({ block: 'center', behavior: 'auto' }))
}

function handlePreviewFrameReady() {
  highlightEvidence()
  refreshPreviewFind()
}

function previewFindRoot() {
  return previewFrame.value?.contentDocument?.body || null
}

function clearPreviewFindHighlights() {
  if (previewFindHighlightRoot) clearPreviewTextHighlights(previewFindHighlightRoot)
  previewFindHighlightRoot = null
  previewFindMatches = []
  previewFindMatchCount.value = 0
  previewFindActiveIndex.value = -1
  previewFindTruncated.value = false
}

function refreshPreviewFind() {
  if (!previewFindOpen.value) return
  const root = previewFindRoot()
  if (previewFindHighlightRoot && previewFindHighlightRoot !== root) clearPreviewTextHighlights(previewFindHighlightRoot)
  previewFindHighlightRoot = root
  const highlighted = highlightPreviewText(root, previewFindQuery.value)
  previewFindMatches = highlighted.matches
  previewFindTruncated.value = highlighted.truncated
  previewFindMatchCount.value = previewFindMatches.length
  updatePreviewFindActiveMatch(0)
}

function updatePreviewFindActiveMatch(index) {
  for (const match of previewFindMatches) match.classList.remove('preview-find-active')
  if (!previewFindMatches.length) {
    previewFindActiveIndex.value = -1
    return
  }
  const nextIndex = (index + previewFindMatches.length) % previewFindMatches.length
  const match = previewFindMatches[nextIndex]
  match.classList.add('preview-find-active')
  previewFindActiveIndex.value = nextIndex
}

function updatePreviewFindQuery(query) {
  previewFindQuery.value = query
  refreshPreviewFind()
}

function navigatePreviewFind(direction) {
  if (!previewFindMatches.length) return
  updatePreviewFindActiveMatch(previewFindActiveIndex.value + direction)
  const match = previewFindMatches[previewFindActiveIndex.value]
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  match?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center', inline: 'nearest' })
}

function openPreviewFind() {
  if (!previewHtml.value) return
  if (!previewFindOpen.value) {
    previewFindRestoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previewFindOpen.value = true
  }
  previewFindFocusRequest.value += 1
  nextTick(refreshPreviewFind)
}

function closePreviewFind() {
  previewFindOpen.value = false
  previewFindQuery.value = ''
  clearPreviewFindHighlights()
  const target = previewFindRestoreFocus?.isConnected ? previewFindRestoreFocus : null
  previewFindRestoreFocus = null
  target?.focus?.({ preventScroll: true })
}

function resetPreviewFind() {
  previewFindOpen.value = false
  previewFindQuery.value = ''
  clearPreviewFindHighlights()
  previewFindRestoreFocus = null
}

async function copySourceLink() {
  const value = String(props.evidence?.source_url || '')
  if (!value) return
  try {
    const desktopCopy = window.knowledgeHubDesktop?.copyText
    if (desktopCopy) await desktopCopy(value)
    else await navigator.clipboard.writeText(value)
    ElMessage.success('链接已复制')
  } catch {
    ElMessage.error('复制失败')
  } finally {
    contentActionsOpen.value = false
  }
}

function openSourceLink() {
  const value = String(props.evidence?.source_url || '')
  if (!value) return
  if (window.knowledgeHubDesktop?.openExternal) {
    window.knowledgeHubDesktop.openExternal(value).catch(() => ElMessage.error('无法使用默认浏览器打开链接'))
  } else {
    window.open(value, '_blank', 'noopener,noreferrer')
  }
  contentActionsOpen.value = false
}

onBeforeUnmount(resetPreviewFind)
</script>

<style scoped>
.evidence-preview { position: relative; height: 100%; min-height: 0; display: flex; flex-direction: column; background: var(--vk-bg-center); color: var(--vk-text); }
.evidence-reader { flex: 0 0 auto; min-width: 0; padding: 22px 22px 0; }
.evidence-reader-head { display: flex; min-width: 0; padding-right: 78px; }
.evidence-reader-heading { display: grid; gap: 5px; min-width: 0; }
.evidence-reader-heading h2 { margin: 0; color: var(--vk-text); font-family: "Songti SC", "STSong", "SimSun", "NSimSun", "Noto Serif CJK SC", "Source Han Serif SC", serif; font-size: 1.25rem; font-weight: 700; letter-spacing: var(--vk-tracking-display); line-height: 1.35; }
.evidence-reader-meta { display: flex; flex-wrap: wrap; gap: 0; margin: 0; color: var(--vk-muted); font-size: var(--vk-type-label-size); letter-spacing: var(--vk-tracking-meta); line-height: var(--vk-leading-label); }
.evidence-reader-meta span + span::before { content: "·"; margin: 0 7px; color: color-mix(in srgb, var(--vk-muted) 54%, transparent); }
.evidence-preview-body { min-height: 0; flex: 1; overflow: hidden; padding-top: 18px; }.evidence-preview-frame { display:block; width:100%; height:100%; border:0; background:var(--vk-bg-center); }.evidence-preview-status { padding:var(--vk-space-panel); color:var(--vk-muted); font-size:var(--vk-type-body-size); }.evidence-preview-status.is-error { color:var(--vk-danger); }
.evidence-overlay-actions { position: absolute; top: 10px; right: 10px; z-index: 9; display: flex; align-items: center; opacity: 1; pointer-events: auto; transition: opacity .14s ease; }.evidence-overlay-actions.is-suppressed { opacity: 0; pointer-events: none; }
.content-fact-button { display: grid; width: 28px; height: 28px; padding: 0; place-items: center; border: 0; border-radius: var(--vk-radius-control); background: color-mix(in srgb, var(--vk-bg-panel) 76%, transparent); color: var(--vk-muted); cursor: pointer; transition: transform var(--vk-motion-fast) var(--vk-ease-out), background-color var(--vk-motion-fast) var(--vk-ease-out), color var(--vk-motion-fast) var(--vk-ease-out); }.content-fact-button:hover,.content-fact-button:focus-visible { outline: 0; background: var(--vk-bg-panel); color: var(--vk-accent-strong); transform: scale(1.02); box-shadow: 0 6px 14px color-mix(in srgb, var(--vk-text) 10%, transparent); }.content-fact-button:active { transform: scale(.95); }
:global(.content-action-popover .content-action-menu-heading) { padding: 3px 7px 5px; color: var(--vk-muted); font-size: 11px; }
:global(.content-action-popover .content-action-menu > button) { width: 100%; padding: 7px; border: 0; border-radius: var(--vk-radius-control); background: transparent; color: var(--vk-text); text-align: left; font: inherit; font-size: 12px; cursor: pointer; }
:global(.content-action-popover .content-action-menu > button:hover:not(:disabled)) { background: color-mix(in srgb, var(--vk-accent) 10%, transparent); color: var(--vk-accent-strong); }
</style>
