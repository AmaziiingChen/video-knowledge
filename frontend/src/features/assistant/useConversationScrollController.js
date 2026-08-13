import { nextTick, onScopeDispose, ref, watch } from 'vue'

const CONVERSATION_BOTTOM_THRESHOLD = 56

export function useConversationScrollController({
  props,
  emit,
  scheduleFrame = requestAnimationFrame,
  cancelFrame = cancelAnimationFrame,
  scheduleNextTick = nextTick,
  isElement = (value) => value instanceof Element,
}) {
  const conversationRef = ref(null)
  const conversationAutoFollow = ref(true)
  let conversationScrollFrame = null
  let historyRestorePosition = null

  function conversationDistanceFromBottom(container) {
    return Math.max(0, container.scrollHeight - container.clientHeight - container.scrollTop)
  }

  function handleConversationWheel(event) {
    if (event.deltaY < 0) conversationAutoFollow.value = false
  }

  function handleTimestampLinkClick(event) {
    const target = isElement(event.target) ? event.target.closest('a[href^="#video-t="]') : null
    if (!target) return
    const seconds = Number(new URL(target.href).hash.replace(/^#video-t=/, ''))
    if (!Number.isFinite(seconds) || seconds < 0) return
    event.preventDefault()
    emit('seek-video', seconds)
  }

  function handleConversationScroll() {
    const container = conversationRef.value
    if (!container) return
    if (
      container.scrollTop <= 48
      && props.qaHistoryHasMore
      && !props.qaHistoryLoading
      && !props.qaHistoryLoadingMore
      && historyRestorePosition === null
    ) {
      historyRestorePosition = {
        height: container.scrollHeight,
        top: container.scrollTop,
        historyLength: props.qaHistory.length,
      }
      emit('load-more-qa-history')
    }
    conversationAutoFollow.value = conversationDistanceFromBottom(container) <= CONVERSATION_BOTTOM_THRESHOLD
  }

  function scrollConversationToBottom({ force = false } = {}) {
    if (!force && !conversationAutoFollow.value) return
    if (conversationScrollFrame !== null) cancelFrame(conversationScrollFrame)
    conversationScrollFrame = scheduleFrame(() => {
      conversationScrollFrame = null
      const container = conversationRef.value
      if (!container || (!force && !conversationAutoFollow.value)) return
      container.scrollTo({ top: container.scrollHeight, behavior: 'auto' })
    })
  }

  function resumeConversationAutoFollow() {
    conversationAutoFollow.value = true
    scheduleNextTick(() => scrollConversationToBottom({ force: true }))
  }

  watch(
    () => props.conversationKey,
    () => resumeConversationAutoFollow(),
  )

  watch(
    () => [props.qaHistory.length, props.qaHistoryLoadingMore],
    ([historyLength, loadingMore]) => {
      const restore = historyRestorePosition
      if (!restore || loadingMore || historyLength <= restore.historyLength) return
      scheduleNextTick(() => {
        const container = conversationRef.value
        if (container) container.scrollTop = restore.top + container.scrollHeight - restore.height
        historyRestorePosition = null
      })
    },
  )

  watch(
    () => [props.qaHistoryLoadingMore, props.qaHistoryHasMore],
    ([loadingMore, hasMore]) => {
      if (!loadingMore && !hasMore) historyRestorePosition = null
    },
  )

  watch(
    () => props.askingQuestion,
    (asking) => {
      if (asking) resumeConversationAutoFollow()
    },
  )

  watch(
    () => [
      props.qaHistory.length,
      props.qaHistory.at(-1)?.answer?.length || 0,
      props.qaHistory.at(-1)?.pending || false,
      props.currentInsightHtml.length,
      props.generatingAiSummary,
      props.generatingSummaryText.length,
    ],
    () => {
      if (!conversationAutoFollow.value) return
      scheduleNextTick(() => scrollConversationToBottom())
    },
  )

  onScopeDispose(() => {
    if (conversationScrollFrame !== null) cancelFrame(conversationScrollFrame)
  })

  return {
    conversationRef,
    handleConversationScroll,
    handleConversationWheel,
    handleTimestampLinkClick,
    resumeConversationAutoFollow,
  }
}
