const SHORT_ANSWER_INTERVAL = 44
const MEDIUM_ANSWER_INTERVAL = 58
const LONG_ANSWER_INTERVAL = 72

export function createQaStreamRenderer({
  getRenderedLength,
  onCommit,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (frame) => cancelAnimationFrame(frame),
  isDocumentHidden = () => document.hidden
}) {
  let pendingText = ''
  let frame = null
  let lastRenderAt = Number.NEGATIVE_INFINITY
  let drainResolvers = []

  function renderInterval() {
    const renderedLength = getRenderedLength()
    if (renderedLength >= 8000) return LONG_ANSWER_INTERVAL
    if (renderedLength >= 4000) return MEDIUM_ANSWER_INTERVAL
    return SHORT_ANSWER_INTERVAL
  }

  function resolveDrainWaiters() {
    if (pendingText || frame !== null) return
    const resolvers = drainResolvers
    drainResolvers = []
    resolvers.forEach((resolve) => resolve())
  }

  function nextBatchSize() {
    if (pendingText.length <= 4) return pendingText.length
    let size = Math.min(96, Math.max(4, Math.ceil(pendingText.length / 4)))
    const lastCodeUnit = pendingText.charCodeAt(size - 1)
    const nextCodeUnit = pendingText.charCodeAt(size)
    const splitsSurrogatePair = (
      lastCodeUnit >= 0xD800
      && lastCodeUnit <= 0xDBFF
      && nextCodeUnit >= 0xDC00
      && nextCodeUnit <= 0xDFFF
    )
    if (splitsSurrogatePair) size += 1
    return size
  }

  function commitNextBatch() {
    if (!pendingText) return
    const batchSize = nextBatchSize()
    const batch = pendingText.slice(0, batchSize)
    pendingText = pendingText.slice(batchSize)
    onCommit(batch)
  }

  function paint(timestamp) {
    frame = null
    if (!pendingText) {
      resolveDrainWaiters()
      return
    }
    if (timestamp - lastRenderAt < renderInterval()) {
      frame = requestFrame(paint)
      return
    }
    commitNextBatch()
    lastRenderAt = timestamp
    if (pendingText) {
      frame = requestFrame(paint)
    } else {
      resolveDrainWaiters()
    }
  }

  function enqueue(text) {
    pendingText += text || ''
    if (frame === null) frame = requestFrame(paint)
  }

  function flush() {
    if (frame !== null) {
      cancelFrame(frame)
      frame = null
    }
    if (pendingText) {
      const text = pendingText
      pendingText = ''
      onCommit(text)
    }
    resolveDrainWaiters()
  }

  function drain() {
    if (!pendingText && frame === null) return Promise.resolve()
    if (isDocumentHidden()) {
      flush()
      return Promise.resolve()
    }
    return new Promise((resolve) => {
      drainResolvers.push(resolve)
      if (frame === null) frame = requestFrame(paint)
    })
  }

  return { drain, enqueue, flush }
}
