import { reactive, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'
import { savedQaHistoryItems } from './qaHistory.js'
import { clearQaSessionState, createQaSession, qaSessionKey } from './qaSessionState.js'

export function useQaSessionController({
  request = axios,
  apiBase = API,
  getActiveContentId = () => null,
  notify = ElMessage,
  wait = (milliseconds) => new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds)),
} = {}) {
  const questionInput = ref('')
  const qaHistory = ref([])
  const qaHistoryLoading = ref(false)
  const qaHistoryLoadingMore = ref(false)
  const qaHistoryHasMore = ref(false)
  const qaHistoryError = ref('')
  const askingQuestion = ref(false)
  const generatingAiSummary = ref(false)
  const generatingSummaryText = ref('')
  const startingNewChat = ref(false)
  const lastQaSaved = ref(false)

  // A response may finish after another document becomes active. Keep every
  // transient conversation attached to its content id and mirror only the
  // active session into the stable panel-facing refs above.
  const qaSessionsByContentId = reactive({})
  const activeQaSessionId = ref('')

  function ensureQaSession(contentItemId) {
    const id = qaSessionKey(contentItemId)
    if (!qaSessionsByContentId[id]) qaSessionsByContentId[id] = createQaSession()
    return qaSessionsByContentId[id]
  }

  function isQaSessionActive(contentItemId) {
    return activeQaSessionId.value === qaSessionKey(contentItemId)
  }

  function syncQaSessionToPanel(session) {
    questionInput.value = session.draft
    qaHistory.value = session.history
    askingQuestion.value = session.asking
    generatingAiSummary.value = session.generatingSummary
    generatingSummaryText.value = session.generatingSummaryText
    lastQaSaved.value = session.lastSaved
    qaHistoryLoading.value = session.historyLoading
    qaHistoryLoadingMore.value = session.historyLoadingMore
    qaHistoryHasMore.value = session.historyHasMore
    qaHistoryError.value = session.historyError
  }

  function activateQaSession(contentItemId) {
    const session = ensureQaSession(contentItemId)
    activeQaSessionId.value = qaSessionKey(contentItemId)
    syncQaSessionToPanel(session)
    return session
  }

  function detachQaSession() {
    activeQaSessionId.value = ''
    questionInput.value = ''
    qaHistory.value = []
    askingQuestion.value = false
    generatingAiSummary.value = false
    generatingSummaryText.value = ''
    lastQaSaved.value = false
    qaHistoryLoading.value = false
    qaHistoryLoadingMore.value = false
    qaHistoryHasMore.value = false
    qaHistoryError.value = ''
  }

  function syncQaSessionIfActive(contentItemId, session) {
    if (isQaSessionActive(contentItemId)) syncQaSessionToPanel(session)
  }

  function refreshQaSessionHistory(contentItemId, session) {
    session.history = [...session.history]
    if (isQaSessionActive(contentItemId)) qaHistory.value = session.history
  }

  function clearQaSession(contentItemId, session = ensureQaSession(contentItemId)) {
    clearQaSessionState(session)
    syncQaSessionIfActive(contentItemId, session)
  }

  function resetActiveQaSession() {
    const session = activeQaSessionId.value
      ? qaSessionsByContentId[activeQaSessionId.value]
      : null
    if (!session) {
      detachQaSession()
      return
    }
    clearQaSession(activeQaSessionId.value, session)
  }

  async function startNewChat() {
    const contentItemId = getActiveContentId()
    const session = ensureQaSession(contentItemId)
    if (session.asking || session.generatingSummary || startingNewChat.value) return
    if (!contentItemId) {
      clearQaSession(contentItemId, session)
      notify.success('已开启新对话')
      return
    }

    startingNewChat.value = true
    try {
      const response = await request.post(
        `${apiBase}/content/${contentItemId}/qa/new-conversation`,
        {},
        { timeout: 10000 },
      )
      clearQaSession(contentItemId, session)
      if (response.data?.archived) {
        notify.success('已开启新对话；上一轮追问已归档到 Markdown')
      } else {
        notify.success('已开启新对话')
      }
    } catch (error) {
      const message = error?.response?.data?.detail || error?.message || '开启新对话失败'
      notify.error(typeof message === 'string' ? message : '开启新对话失败')
    } finally {
      startingNewChat.value = false
    }
  }

  async function loadContentQaHistory(contentItemId, session = ensureQaSession(contentItemId)) {
    if (!contentItemId || session.historyLoaded || session.historyLoading) return
    const requestId = ++session.historyRequestId
    const initialHistoryLength = session.history.length
    session.historyLoading = true
    session.historyError = ''
    syncQaSessionIfActive(contentItemId, session)
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await request.get(`${apiBase}/content/${contentItemId}/qa-history`, {
          params: { limit: 12 },
          timeout: 10000,
        })
        if (requestId !== session.historyRequestId) return
        const savedItems = savedQaHistoryItems(response.data?.items)
        // A question may be sent before supplementary history returns. Keep
        // that pending local turn after the older persisted conversation.
        session.history = session.history.length === initialHistoryLength
          ? savedItems
          : [...savedItems, ...session.history]
        session.historyLoaded = true
        session.historyHasMore = Boolean(response.data?.has_more)
        session.historyNextBefore = String(response.data?.next_before || '')
        return
      } catch (error) {
        if (requestId !== session.historyRequestId) return
        if (attempt < 2) {
          await wait(500 * (attempt + 1))
          if (requestId !== session.historyRequestId) return
          continue
        }
        session.historyError = error?.response?.data?.detail || '历史对话加载失败，可重试'
      } finally {
        if (attempt === 2 || session.historyLoaded || requestId !== session.historyRequestId) {
          session.historyLoading = false
          syncQaSessionIfActive(contentItemId, session)
        }
      }
    }
  }

  async function loadMoreContentQaHistory() {
    const contentItemId = getActiveContentId()
    if (!contentItemId) return
    const session = ensureQaSession(contentItemId)
    if (
      !session.historyLoaded
      || !session.historyHasMore
      || !session.historyNextBefore
      || session.historyLoadingMore
    ) return
    const requestId = session.historyRequestId
    session.historyLoadingMore = true
    session.historyError = ''
    syncQaSessionIfActive(contentItemId, session)
    try {
      const response = await request.get(`${apiBase}/content/${contentItemId}/qa-history`, {
        params: { limit: 12, before: session.historyNextBefore },
        timeout: 10000,
      })
      if (requestId !== session.historyRequestId) return
      session.history = [...savedQaHistoryItems(response.data?.items), ...session.history]
      session.historyHasMore = Boolean(response.data?.has_more)
      session.historyNextBefore = String(response.data?.next_before || '')
    } catch (error) {
      if (requestId === session.historyRequestId) {
        session.historyError = error?.response?.data?.detail || '加载更早对话失败，可重试'
      }
    } finally {
      session.historyLoadingMore = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  async function retryContentQaHistory() {
    const contentItemId = getActiveContentId()
    if (!contentItemId) return
    const session = ensureQaSession(contentItemId)
    if (session.historyHasMore && session.historyNextBefore) {
      await loadMoreContentQaHistory()
      return
    }
    session.historyLoaded = false
    await loadContentQaHistory(contentItemId, session)
  }

  watch(questionInput, (value) => {
    if (!activeQaSessionId.value) return
    const session = qaSessionsByContentId[activeQaSessionId.value]
    if (session) session.draft = value
  })

  return {
    questionInput,
    qaHistory,
    qaHistoryLoading,
    qaHistoryLoadingMore,
    qaHistoryHasMore,
    qaHistoryError,
    askingQuestion,
    generatingAiSummary,
    generatingSummaryText,
    startingNewChat,
    lastQaSaved,
    ensureQaSession,
    isQaSessionActive,
    activateQaSession,
    detachQaSession,
    syncQaSessionIfActive,
    refreshQaSessionHistory,
    clearQaSession,
    resetActiveQaSession,
    startNewChat,
    loadContentQaHistory,
    loadMoreContentQaHistory,
    retryContentQaHistory,
  }
}
