import { computed, ref, watch } from 'vue'

const SELECTED_TEXT_TOKEN = '@选中文本'

export function useSelectedTextContext({
  questionInput,
  getActiveContent = () => null,
  getFallbackContentItemId = () => '',
  getFallbackContentTitle = () => '',
  now = () => Date.now(),
} = {}) {
  const selectedTextContext = ref(null)

  function activeContentItemId() {
    return String(getActiveContent()?.id || getFallbackContentItemId() || '')
  }

  const activeSelectedTextContext = computed(() => {
    const context = selectedTextContext.value
    const contentItemId = activeContentItemId()
    return context?.contentItemId && context.contentItemId === contentItemId ? context : null
  })

  function hasSelectedTextContextToken(value) {
    return /(?:^|\s)@选中文本(?=\s|$)/u.test(String(value || ''))
  }

  function addSelectedTextContextToken(value) {
    const current = String(value || '')
    if (hasSelectedTextContextToken(current)) return current
    return `${current}${current && !/\s$/u.test(current) ? ' ' : ''}${SELECTED_TEXT_TOKEN} `
  }

  function removeSelectedTextContextToken(value) {
    return String(value || '')
      .replace(/(?:^|\s)@选中文本(?=\s|$)/gu, ' ')
      .replace(/[ \t]{2,}/gu, ' ')
      .trimStart()
  }

  function setSelectedTextContext(context) {
    const activeContent = getActiveContent()
    const text = String(context?.text || '').replace(/\s+/gu, ' ').trim()
    const contentItemId = String(
      context?.contentItemId || activeContent?.id || getFallbackContentItemId() || '',
    ).trim()
    if (!text || !contentItemId) return
    selectedTextContext.value = {
      id: `${contentItemId}:${now()}`,
      contentItemId,
      contentTitle: String(
        context?.contentTitle || activeContent?.title || getFallbackContentTitle() || '当前内容',
      ).trim(),
      text: text.slice(0, 12000),
    }
    questionInput.value = addSelectedTextContextToken(questionInput.value)
  }

  function clearSelectedTextContext() {
    selectedTextContext.value = null
    questionInput.value = removeSelectedTextContextToken(questionInput.value)
  }

  const stopQuestionWatch = watch(questionInput, (value) => {
    if (
      selectedTextContext.value?.contentItemId === activeContentItemId()
      && !hasSelectedTextContextToken(value)
    ) {
      selectedTextContext.value = null
    }
  })

  return {
    activeSelectedTextContext,
    addSelectedTextContextToken,
    clearSelectedTextContext,
    disposeSelectedTextContext: stopQuestionWatch,
    hasSelectedTextContextToken,
    removeSelectedTextContextToken,
    selectedTextContext,
    setSelectedTextContext,
  }
}
