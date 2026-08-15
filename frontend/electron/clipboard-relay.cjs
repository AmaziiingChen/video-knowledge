const DEFAULT_MAX_CLIPBOARD_CHARS = 50_000

function clipboardText(value, maxChars = DEFAULT_MAX_CLIPBOARD_CHARS) {
  const text = typeof value === 'string' ? value.trim() : ''
  return text && text.length <= maxChars ? text : ''
}

function createClipboardRelay({
  readText,
  sendText,
  onError = () => {},
  intervalMs = 750,
  setIntervalFn = setInterval,
  clearIntervalFn = clearInterval,
  maxChars = DEFAULT_MAX_CLIPBOARD_CHARS,
} = {}) {
  if (typeof readText !== 'function' || typeof sendText !== 'function') {
    throw new TypeError('clipboard relay requires readText and sendText')
  }

  let lastText = ''
  let timer = null
  let inFlight = false

  function readCandidate() {
    try {
      return clipboardText(readText(), maxChars)
    } catch (error) {
      onError(error)
      return ''
    }
  }

  async function scanOnce() {
    if (inFlight) return false
    const candidate = readCandidate()
    if (!candidate || candidate === lastText) return false

    inFlight = true
    try {
      await sendText(candidate)
      lastText = candidate
      return true
    } catch (error) {
      onError(error)
      return false
    } finally {
      inFlight = false
    }
  }

  function start() {
    if (timer) return false
    // Match the backend restore contract: content already present when the app
    // starts is a baseline, while every later clipboard change is eligible.
    lastText = readCandidate()
    timer = setIntervalFn(() => { void scanOnce() }, intervalMs)
    timer?.unref?.()
    return true
  }

  function stop() {
    if (!timer) return false
    clearIntervalFn(timer)
    timer = null
    return true
  }

  return { scanOnce, start, stop }
}

module.exports = {
  DEFAULT_MAX_CLIPBOARD_CHARS,
  clipboardText,
  createClipboardRelay,
}
