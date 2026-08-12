import { createQaStreamRenderer } from './qaStreamRenderer.js'

export function createQaResponseStreamController({
  appendContentAiCall,
  getSelectedContentItem,
  applyMarkdownState,
  refreshQaSessionHistory,
  refreshFallbackHistory,
  setLastQaSaved,
  createStreamRenderer = createQaStreamRenderer,
}) {
  async function readQaStream(response, pendingItem, contentItemId, options = {}) {
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式响应')

    const decoder = new TextDecoder()
    let buffer = ''
    const streamState = { receivedDone: false, doneData: null }
    let reasoningBuffer = ''
    let reasoningTimer = null
    const commitReasoning = () => {
      reasoningTimer = null
      if (!reasoningBuffer) return
      pendingItem.reasoning = `${pendingItem.reasoning || ''}${reasoningBuffer}`
      reasoningBuffer = ''
      options.onReasoning?.(pendingItem.reasoning)
      if (options.session) refreshQaSessionHistory(contentItemId, options.session)
      else refreshFallbackHistory()
    }
    const queueReasoning = (text) => {
      reasoningBuffer += text
      if (!pendingItem.reasoning && reasoningBuffer) commitReasoning()
      else if (reasoningTimer === null) reasoningTimer = setTimeout(commitReasoning, 60)
    }
    const streamRenderer = createStreamRenderer({
      onCommit: (text) => {
        pendingItem.answer += text
        if (options.session) {
          refreshQaSessionHistory(contentItemId, options.session)
        } else {
          refreshFallbackHistory()
        }
        options.onCommit?.(pendingItem.answer)
      }
    })

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          handleQaStreamBlock(block, contentItemId, streamRenderer.enqueue, queueReasoning, streamState, pendingItem, options)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleQaStreamBlock(buffer, contentItemId, streamRenderer.enqueue, queueReasoning, streamState, pendingItem, options)
      }
      await streamRenderer.drain()
      if (reasoningTimer !== null) clearTimeout(reasoningTimer)
      commitReasoning()
      if (!streamState.receivedDone) throw new Error('AI 流式响应提前结束，请重试')
      finalizeQaStreamDone(streamState.doneData, pendingItem, contentItemId, options)
    } catch (error) {
      streamRenderer.flush()
      if (reasoningTimer !== null) clearTimeout(reasoningTimer)
      throw error
    }
  }

  function handleQaStreamBlock(block, contentItemId, queueDelta, queueReasoning, streamState, pendingItem, options = {}) {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const dataLine = lines.find((line) => line.startsWith('data:'))
    if (!dataLine) return
    const data = JSON.parse(dataLine.slice(5).trim())

    if (event === 'delta') {
      if (!options.receivedFirstDelta) {
        options.receivedFirstDelta = true
        options.onFirstDelta?.()
        if (pendingItem.reasoning) pendingItem.reasoningExpanded = false
      }
      queueDelta(data.text || '')
      return
    }
    if (event === 'reasoning_delta') {
      if (!pendingItem.reasoning && data.text) {
        pendingItem.reasoningExpanded = true
        options.onFirstReasoning?.()
      }
      queueReasoning(data.text || '')
      return
    }
    if (event === 'usage') {
      appendContentAiCall(contentItemId, data)
      return
    }
    if (event === 'log') {
      options.onLog?.(data)
      return
    }
    if (event === 'done') {
      streamState.receivedDone = true
      streamState.doneData = data
      return
    }
    if (event === 'error') {
      throw new Error(data.error || '追问失败')
    }
  }

  function finalizeQaStreamDone(data, pendingItem, contentItemId, options = {}) {
    const session = options.session || null
    // A response belonging to article A can finish after the user has opened
    // article B. Persisting happened server-side already; only update the
    // visible Markdown pane when it still represents A.
    if (
      data.markdown_state
      && (!contentItemId || String(getSelectedContentItem()?.id || '') === String(contentItemId))
    ) {
      applyMarkdownState(data.markdown_state)
    }
    if (typeof data.answer === 'string') pendingItem.answer = data.answer
    pendingItem.reasoning = typeof data.reasoning_content === 'string' ? data.reasoning_content : (pendingItem.reasoning || '')
    pendingItem.suggestedQuestions = Array.isArray(data.suggested_questions) ? data.suggested_questions.slice(0, 3) : []
    options.onSuggestions?.(pendingItem.suggestedQuestions)
    if (typeof data.assistant_message_id === 'string' && data.assistant_message_id) {
      pendingItem.id = data.assistant_message_id
    }
    pendingItem.pending = false
    pendingItem.saved = Boolean(data.saved_to_markdown || data.saved_to_obsidian)
    pendingItem.savedToContent = Boolean(data.saved_to_content)
    pendingItem.obsidianError = data.obsidian_error || ''
    if (session) {
      session.lastSaved = pendingItem.saved
      session.suggestedQuestions = pendingItem.suggestedQuestions
      refreshQaSessionHistory(contentItemId, session)
      return
    }
    setLastQaSaved(pendingItem.saved)
    refreshFallbackHistory()
  }

  return { readQaStream }
}
