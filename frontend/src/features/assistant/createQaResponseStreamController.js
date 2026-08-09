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
          handleQaStreamBlock(block, contentItemId, streamRenderer.enqueue, streamState, options)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleQaStreamBlock(buffer, contentItemId, streamRenderer.enqueue, streamState, options)
      }
      await streamRenderer.drain()
      if (!streamState.receivedDone) throw new Error('AI 流式响应提前结束，请重试')
      finalizeQaStreamDone(streamState.doneData, pendingItem, contentItemId, options.session)
    } catch (error) {
      streamRenderer.flush()
      throw error
    }
  }

  function handleQaStreamBlock(block, contentItemId, queueDelta, streamState, options = {}) {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const dataLine = lines.find((line) => line.startsWith('data:'))
    if (!dataLine) return
    const data = JSON.parse(dataLine.slice(5).trim())

    if (event === 'delta') {
      if (!options.receivedFirstDelta) {
        options.receivedFirstDelta = true
        options.onFirstDelta?.()
      }
      queueDelta(data.text || '')
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

  function finalizeQaStreamDone(data, pendingItem, contentItemId, session = null) {
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
    if (typeof data.assistant_message_id === 'string' && data.assistant_message_id) {
      pendingItem.id = data.assistant_message_id
    }
    pendingItem.pending = false
    pendingItem.saved = Boolean(data.saved_to_markdown || data.saved_to_obsidian)
    pendingItem.savedToContent = Boolean(data.saved_to_content)
    pendingItem.obsidianError = data.obsidian_error || ''
    if (session) {
      session.lastSaved = pendingItem.saved
      refreshQaSessionHistory(contentItemId, session)
      return
    }
    setLastQaSaved(pendingItem.saved)
    refreshFallbackHistory()
  }

  return { readQaStream }
}
