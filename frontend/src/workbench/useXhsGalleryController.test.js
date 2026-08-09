import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useXhsGalleryController } from './useXhsGalleryController.js'

function createController({ tabId = 'content:1', gallery = [{}, {}, {}] } = {}) {
  const activeContentTab = ref({ id: tabId })
  const controller = useXhsGalleryController({
    activeContentTab,
    articlePreviewForTab: (id) => (id === tabId ? { gallery } : null),
  })
  const scrolls = []
  controller.xhsGalleryTrack.value = {
    clientWidth: 240,
    scrollLeft: 0,
    scrollTo: (options) => scrolls.push(options),
  }
  return { controller, scrolls }
}

test('keeps gallery movement within the available image range', () => {
  const { controller, scrolls } = createController()

  assert.equal(controller.canNavigateXhsGallery('content:1', -1), false)
  assert.equal(controller.canNavigateXhsGallery('content:1', 1), true)
  controller.scrollXhsGallery(1)
  controller.scrollXhsGallery(10)

  assert.equal(controller.xhsGalleryIndex.value, 2)
  assert.deepEqual(scrolls, [
    { left: 240, behavior: 'smooth' },
    { left: 480, behavior: 'smooth' },
  ])
})

test('synchronizes native scrolling, keyboard movement, and tab reset', async () => {
  const { controller, scrolls } = createController()
  controller.xhsGalleryTrack.value.scrollLeft = 430
  controller.syncXhsGalleryPosition()
  assert.equal(controller.xhsGalleryIndex.value, 2)

  let prevented = false
  controller.handleXhsGalleryKeydown({ key: 'ArrowLeft', preventDefault: () => { prevented = true } })
  assert.equal(prevented, true)
  assert.equal(controller.xhsGalleryIndex.value, 1)

  controller.resetXhsGallery()
  await nextTick()
  assert.equal(controller.xhsGalleryIndex.value, 0)
  assert.deepEqual(scrolls.at(-1), { left: 0, behavior: 'auto' })
})
