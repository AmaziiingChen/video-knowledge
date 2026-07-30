const MAX_PROMPT_HISTORY_ITEMS = 12

export function savedQaHistoryItems(items) {
  if (!Array.isArray(items)) return []
  return items
    .filter((item) => item && typeof item.question === 'string' && typeof item.answer === 'string')
    .map((item) => ({
      id: item.id || '',
      question: item.question,
      answer: item.answer,
      saved: true,
      pending: false,
      error: false,
      time: item.created_at || ''
    }))
}

export function qaHistoryForPrompt(items) {
  if (!Array.isArray(items)) return []
  return items
    .filter((item) => (
      !item?.pending
      && !item?.error
      && String(item?.question || '').trim()
      && String(item?.answer || '').trim()
    ))
    .slice(-MAX_PROMPT_HISTORY_ITEMS)
    .map((item) => ({
      // The UI keeps the user's original wording, while a shortcut may add
      // instructions only for the model. Reusing that exact model wording in
      // the next request preserves the assistant-message cache prefix.
      question: String(item.modelQuestion || item.question).trim(),
      answer: item.answer
    }))
}
