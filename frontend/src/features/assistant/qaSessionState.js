export const TRANSIENT_QA_SESSION_ID = '__transient__'

export function qaSessionKey(contentItemId) {
  return contentItemId ? String(contentItemId) : TRANSIENT_QA_SESSION_ID
}

export function createQaSession() {
  return {
    draft: '',
    history: [],
    asking: false,
    generatingSummary: false,
    generatingSummaryText: '',
    generatingSummaryReasoning: '',
    generatingSummaryReasoningExpanded: false,
    suggestedQuestions: [],
    lastProjectedSummaryTaskId: '',
    lastSaved: false,
    historyLoaded: false,
    historyLoading: false,
    historyLoadingMore: false,
    historyHasMore: false,
    historyNextBefore: '',
    historyError: '',
    historyRequestId: 0
  }
}

export function clearQaSessionState(session) {
  session.historyRequestId += 1
  session.draft = ''
  session.history = []
  session.asking = false
  session.generatingSummary = false
  session.generatingSummaryText = ''
  session.generatingSummaryReasoning = ''
  session.generatingSummaryReasoningExpanded = false
  session.suggestedQuestions = []
  // Keep the consumed task marker across an explicit clear/new conversation.
  // Otherwise the same completed pipeline task would immediately restore its
  // old suggestions into the newly emptied conversation.
  session.lastSaved = false
  session.historyLoading = false
  session.historyLoadingMore = false
  session.historyHasMore = false
  session.historyNextBefore = ''
  session.historyError = ''
  // A clear follows an explicit new-conversation action or a full task reset,
  // so a delayed history response must not restore the old thread.
  session.historyLoaded = true
  return session
}
