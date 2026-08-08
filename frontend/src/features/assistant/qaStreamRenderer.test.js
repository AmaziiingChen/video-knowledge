import assert from 'node:assert/strict'
import test from 'node:test'

import { createQaStreamRenderer } from './qaStreamRenderer.js'

function frameHarness() {
  let nextId = 1
  const callbacks = new Map()
  return {
    request(callback) {
      const id = nextId++
      callbacks.set(id, callback)
      return id
    },
    cancel(id) {
      callbacks.delete(id)
    },
    run(timestamp) {
      const queued = [...callbacks.values()]
      callbacks.clear()
      queued.forEach((callback) => callback(timestamp))
    },
    get size() {
      return callbacks.size
    }
  }
}

test('coalesces a burst only until the next visual frame', async () => {
  const frames = frameHarness()
  const commits = []
  let renderedLength = 0
  const renderer = createQaStreamRenderer({
    getRenderedLength: () => renderedLength,
    onCommit(text) {
      commits.push(text)
      renderedLength += text.length
    },
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
    isDocumentHidden: () => false
  })

  const expected = '第一段突发内容abcdefghijklmnopqrstuvwxyz第二段'
  renderer.enqueue(expected)
  const drained = renderer.drain()
  for (let timestamp = 0; frames.size; timestamp += 50) frames.run(timestamp)
  await drained

  assert.equal(commits.join(''), expected)
  assert.equal(commits.length, 1)
  assert.ok(commits.every(Boolean))
})

test('a visual frame preserves a complete emoji-containing model delta', () => {
  const frames = frameHarness()
  const commits = []
  const renderer = createQaStreamRenderer({
    getRenderedLength: () => commits.join('').length,
    onCommit: (text) => commits.push(text),
    requestFrame: frames.request,
    cancelFrame: frames.cancel,
    isDocumentHidden: () => false
  })

  renderer.enqueue('123🙂abcd')
  frames.run(0)
  assert.equal(commits[0], '123🙂abcd')
  renderer.flush()

  assert.equal(commits.join(''), '123🙂abcd')
  assert.ok(commits.every((text) => !text.includes('\uFFFD')))
})
