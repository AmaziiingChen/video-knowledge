export function createQaStreamRenderer({
  onCommit,
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (frame) => cancelAnimationFrame(frame),
  isDocumentHidden = () => document.hidden
}) {
  let pendingText = ''
  let frame = null
  let drainResolvers = []

  function resolveDrainWaiters() {
    if (pendingText || frame !== null) return
    const resolvers = drainResolvers
    drainResolvers = []
    resolvers.forEach((resolve) => resolve())
  }

  function paint() {
    frame = null
    if (!pendingText) {
      resolveDrainWaiters()
      return
    }
    // Render the complete model delta on the next visual frame. This limits
    // DOM work to the display refresh rate without inventing a character
    // speed or leaving text in a local queue after the model has finished.
    const text = pendingText
    pendingText = ''
    onCommit(text)
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
