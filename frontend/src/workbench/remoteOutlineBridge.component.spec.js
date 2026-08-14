import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  parseRemoteOutlineMessage,
  remoteOutlineBridgeScript,
} from './remoteOutlineBridge.js'

beforeEach(() => {
  vi.useFakeTimers()
  delete window.__knowledgeHubRemoteOutlineBridgeInstalled
  delete window.__knowledgeHubRemoteOutlineScrollTo
  document.body.innerHTML = ''
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({
    left: 0,
    top: 0,
    right: 320,
    bottom: 32,
    width: 320,
    height: 32,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }))
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
  delete window.__knowledgeHubRemoteOutlineBridgeInstalled
  delete window.__knowledgeHubRemoteOutlineScrollTo
})

describe('remoteOutlineBridgeScript', () => {
  it('derives an outline from standalone rich-text headings without semantic h-tags', () => {
    document.body.innerHTML = `
      <main>
        <p><strong>一、政策背景</strong></p>
        <p>这里是第一节正文。</p>
        <p><strong>二、实施安排</strong></p>
        <p>这里是第二节正文。</p>
      </main>
    `
    const messages = []
    vi.spyOn(console, 'debug').mockImplementation((message) => messages.push(message))

    window.eval(remoteOutlineBridgeScript())

    const outline = messages.map(parseRemoteOutlineMessage).find((message) => message?.kind === 'outline')
    expect(outline?.entries.map((entry) => entry.text)).toEqual([
      '一、政策背景',
      '二、实施安排',
    ])
  })
})
