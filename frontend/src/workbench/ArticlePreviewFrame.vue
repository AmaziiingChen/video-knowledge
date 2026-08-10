<template>
  <iframe
    ref="frame"
    class="article-preview-frame"
    :class="{
      'is-hidden': hidden,
      'local-html-original-frame': localHtmlOriginal,
    }"
    :srcdoc="srcdoc"
    sandbox="allow-same-origin"
    referrerpolicy="no-referrer"
    :title="title"
    @load="handleLoad"
  ></iframe>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import katex from 'katex'
import { isPreviewFindShortcut } from './previewFindShortcut.js'

defineProps({
  srcdoc: { type: String, default: '' },
  title: { type: String, required: true },
  hidden: { type: Boolean, default: false },
  localHtmlOriginal: { type: Boolean, default: false },
})

const emit = defineEmits(['open-external-link', 'open-find', 'ready'])
const frame = ref(null)
let attachedDocument = null

function detachDocumentListeners() {
  attachedDocument?.removeEventListener('keydown', handleKeydown)
  attachedDocument?.removeEventListener('click', handleLinkClick)
  attachedDocument?.removeEventListener('auxclick', handleLinkClick)
  attachedDocument = null
}

function handleLoad(event) {
  const frameDocument = event?.target?.contentDocument
  if (!frameDocument) return
  detachDocumentListeners()
  attachedDocument = frameDocument
  renderMath(frameDocument)
  frameDocument.addEventListener('keydown', handleKeydown)
  frameDocument.addEventListener('click', handleLinkClick)
  frameDocument.addEventListener('auxclick', handleLinkClick)
  installFindHighlightStyles(frameDocument)
  emit('ready', frameDocument)
}

function renderMath(frameDocument) {
  const nodes = frameDocument.querySelectorAll('.article-math[data-latex]')
  for (const node of nodes) {
    const expression = String(node.dataset.latex || '').trim()
    if (!expression || expression.length > 4000 || node.dataset.rendered === 'true') continue
    try {
      node.innerHTML = katex.renderToString(expression, {
        displayMode: node.dataset.display === 'block',
        throwOnError: false,
        strict: 'warn',
        trust: false,
        maxExpand: 1000,
        maxSize: 20,
        output: 'mathml',
      })
      node.dataset.rendered = 'true'
    } catch {
      // Keep sanitized LaTeX text as the readable fallback.
    }
  }
}

function handleLinkClick(event) {
  if (event.type === 'click' && event.button !== 0) return
  if (event.type === 'auxclick' && event.button !== 1) return
  const target = event?.target
  const anchor = target?.closest?.('a[href]') || target?.parentElement?.closest?.('a[href]')
  if (!anchor) return
  let url
  try {
    url = new URL(anchor.href)
  } catch {
    return
  }
  if (!['http:', 'https:'].includes(url.protocol)) return
  event.preventDefault()
  event.stopPropagation()
  emit('open-external-link', url.toString())
}

function handleKeydown(event) {
  if (!isPreviewFindShortcut(event)) return
  event.preventDefault()
  emit('open-find')
}

function installFindHighlightStyles(frameDocument) {
  if (frameDocument.getElementById('knowledgehub-preview-find-styles')) return
  const rootStyle = getComputedStyle(document.documentElement)
  const highlight = rootStyle.getPropertyValue('--vk-highlight').trim()
  const accent = rootStyle.getPropertyValue('--vk-accent').trim()
  const accentStrong = rootStyle.getPropertyValue('--vk-accent-strong').trim()
  const style = frameDocument.createElement('style')
  style.id = 'knowledgehub-preview-find-styles'
  style.textContent = `
    mark.preview-find-highlight { background: color-mix(in srgb, ${highlight} 42%, transparent); color: inherit; border-radius: 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
    mark.preview-find-highlight.preview-find-active { background: color-mix(in srgb, ${accent} 48%, transparent); outline: 1px solid color-mix(in srgb, ${accentStrong} 52%, transparent); }
  `
  frameDocument.head?.append(style)
}

onBeforeUnmount(detachDocumentListeners)

defineExpose({
  getDocument: () => frame.value?.contentDocument || null,
  getFrame: () => frame.value,
})
</script>

<style scoped>
.article-preview-frame {
  display: block;
  flex: 1 1 auto;
  width: 100%;
  min-height: 360px;
  border: 0;
  background: transparent;
}

.article-preview-frame.local-html-original-frame {
  min-height: 0;
  background: var(--vk-bg-center);
}

.article-preview-frame.is-hidden {
  display: none;
}
</style>
