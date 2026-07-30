export const WECHAT_REMOTE_SELECTION_PREFIX = '__knowledgehub_wechat_selection__:'

function finiteCoordinate(value) {
  const coordinate = Number(value)
  return Number.isFinite(coordinate) ? coordinate : null
}

export function parseWechatRemoteSelectionMessage(message) {
  if (typeof message !== 'string' || !message.startsWith(WECHAT_REMOTE_SELECTION_PREFIX)) return null

  try {
    const payload = JSON.parse(message.slice(WECHAT_REMOTE_SELECTION_PREFIX.length))
    if (payload?.kind === 'clear') return { kind: 'clear' }
    if (payload?.kind !== 'selection') return null

    const text = String(payload.text || '').replace(/\s+/gu, ' ').trim()
    const rect = payload.rect || {}
    const left = finiteCoordinate(rect.left)
    const top = finiteCoordinate(rect.top)
    const right = finiteCoordinate(rect.right)
    const bottom = finiteCoordinate(rect.bottom)
    if (text.length < 2 || left === null || top === null || right === null || bottom === null) return null

    return {
      kind: 'selection',
      text: text.slice(0, 12000),
      rect: { left, top, right, bottom },
    }
  } catch {
    return null
  }
}

export function wechatRemoteSelectionBridgeScript() {
  const prefix = JSON.stringify(WECHAT_REMOTE_SELECTION_PREFIX)
  return `(() => {
    if (window.__knowledgeHubWechatSelectionBridgeInstalled) return
    window.__knowledgeHubWechatSelectionBridgeInstalled = true

    const send = (payload) => console.debug(${prefix} + JSON.stringify(payload))
    let scheduled = false
    const publishSelection = () => {
      scheduled = false
      const selection = window.getSelection?.()
      if (!selection || selection.isCollapsed || !selection.rangeCount) {
        send({ kind: 'clear' })
        return
      }
      const text = String(selection.toString() || '').replace(/\\s+/gu, ' ').trim()
      const rect = selection.getRangeAt(0).getBoundingClientRect()
      if (text.length < 2 || (!rect.width && !rect.height)) {
        send({ kind: 'clear' })
        return
      }
      send({
        kind: 'selection',
        text: text.slice(0, 12000),
        rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
      })
    }
    const scheduleSelection = () => {
      if (scheduled) return
      scheduled = true
      window.requestAnimationFrame(publishSelection)
    }
    document.addEventListener('pointerdown', () => send({ kind: 'clear' }), true)
    document.addEventListener('pointerup', scheduleSelection, true)
    document.addEventListener('pointercancel', () => send({ kind: 'clear' }), true)
  })()`
}
