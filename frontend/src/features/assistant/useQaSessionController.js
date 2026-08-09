import { reactive, ref, watch } from 'vue'
import { clearQaSessionState, createQaSession, qaSessionKey } from './qaSessionState'

export function useQaSessionController() {
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
    resetActiveQaSession
  }
}
