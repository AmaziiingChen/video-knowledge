import assert from 'node:assert/strict'
import test from 'node:test'

import { usePreviewFindController } from './usePreviewFindController.js'

function fakeWindow() {
  let nextFrame = 0
  const frames = new Map()
  return {
    frames,
    HTMLElement: class {},
    cancelAnimationFrame(id) { frames.delete(id) },
    getSelection: () => ({ toString: () => '预填查询' }),
    matchMedia: () => ({ matches: true }),
    requestAnimationFrame(callback) {
      const id = ++nextFrame
      frames.set(id, callback)
      return id
    },
  }
}

test('delegates remote preview search while retaining shared result state', () => {
  const remoteCalls = []
  const windowObject = fakeWindow()
  const controller = usePreviewFindController({
    hasActiveContent: () => true,
    getMode: () => 'wechat',
    refreshRemote: (mode, query) => remoteCalls.push(['refresh', mode, query]),
    navigateRemote: (mode, query, direction) => remoteCalls.push(['navigate', mode, query, direction]),
    clearRemote: (options) => remoteCalls.push(['clear', options.clearSelection]),
    windowObject,
    documentObject: { activeElement: null },
  })

  controller.openPreviewFind()
  controller.updatePreviewFindQuery('校报')
  controller.setRemoteFindResult({ matchCount: 3, activeMatchOrdinal: 2 })
  controller.navigatePreviewFind(-1)

  assert.equal(controller.previewFindOpen.value, true)
  assert.equal(controller.previewFindMatchCount.value, 3)
  assert.equal(controller.previewFindActiveIndex.value, 1)
  assert.deepEqual(remoteCalls, [
    ['refresh', 'wechat', '校报'],
    ['navigate', 'wechat', '校报', -1],
  ])

  controller.closePreviewFind()
  assert.equal(controller.previewFindQuery.value, '')
  assert.deepEqual(remoteCalls.at(-1), ['clear', true])
  controller.disposePreviewFindController()
  assert.equal(windowObject.frames.size, 0)
})
