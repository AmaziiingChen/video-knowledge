import { computed, ref } from 'vue'

function targetIdFromEvent(event) {
  if (event?.defaultPrevented || event?.button !== 0) return ''
  const target = event?.target
  if (!(target instanceof Element)) return ''
  const reference = target.closest('.markdown-footnote-ref a[href^="#fn-"]')
  return reference instanceof HTMLAnchorElement ? (reference.getAttribute('href')?.slice(1) || '') : ''
}

function elementWithId(root, id) {
  return [...(root?.querySelectorAll?.('[id]') || [])].find((element) => element.id === id) || null
}

export function useMarkdownFootnoteNavigation({ scrollRoot, scopeKey }) {
  const returnPoint = ref(null)
  const scope = () => typeof scopeKey === 'function' ? scopeKey() : scopeKey?.value
  const hasFootnoteReturn = computed(() => returnPoint.value?.scope === scope())

  function positionFootnotePreview(event) {
    const target = event?.target
    if (!(target instanceof Element)) return
    const reference = target.closest('.markdown-footnote-ref a')
    const preview = reference?.querySelector('.markdown-footnote-preview')
    if (!(reference instanceof HTMLElement) || !(preview instanceof HTMLElement)) return
    const bounds = scrollRoot.value?.getBoundingClientRect() || document.documentElement.getBoundingClientRect()
    const referenceBounds = reference.getBoundingClientRect()
    const leftSpace = referenceBounds.right - bounds.left
    const rightSpace = bounds.right - referenceBounds.left
    preview.classList.toggle('is-open-right', leftSpace < preview.getBoundingClientRect().width - 10 && rightSpace > leftSpace)
  }

  function handleFootnoteClick(event) {
    const targetId = targetIdFromEvent(event)
    const reader = scrollRoot.value
    const footnote = elementWithId(reader, targetId) || document.getElementById(targetId)
    if (!targetId || !(footnote instanceof HTMLElement) || !reader) return ''
    event.preventDefault()
    returnPoint.value = { scope: scope(), scrollTop: reader.scrollTop }
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    footnote.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start', inline: 'nearest' })
    return targetId
  }

  function returnToFootnoteReference() {
    const reader = scrollRoot.value
    if (!reader || !hasFootnoteReturn.value) { returnPoint.value = null; return }
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    reader.scrollTo({ top: returnPoint.value.scrollTop, behavior: reducedMotion ? 'auto' : 'smooth' })
    returnPoint.value = null
  }

  function clearFootnoteReturn() {
    returnPoint.value = null
  }

  return { clearFootnoteReturn, handleFootnoteClick, hasFootnoteReturn, positionFootnotePreview, returnToFootnoteReference }
}
