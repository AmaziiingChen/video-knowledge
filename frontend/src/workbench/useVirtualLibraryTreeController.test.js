import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useVirtualLibraryTreeController } from './useVirtualLibraryTreeController.js'

function createController() {
  const scheduled = []
  const cancelled = []
  const observers = []
  let scrollStarts = 0
  const controller = useVirtualLibraryTreeController({
    renderedLibraryNodes: ref(Array.from({ length: 100 }, (_value, index) => ({ id: index }))),
    onScrollStart: () => { scrollStarts += 1 },
    schedule: (callback, delay) => {
      const timer = { callback, delay }
      scheduled.push(timer)
      return timer
    },
    cancelSchedule: (timer) => cancelled.push(timer),
    createResizeObserver: (callback) => {
      const observer = {
        callback,
        observed: null,
        disconnected: false,
        observe: (tree) => { observer.observed = tree },
        disconnect: () => { observer.disconnected = true },
      }
      observers.push(observer)
      return observer
    },
  })
  const tree = { scrollTop: 0, clientHeight: 52 }
  controller.treeRef.value = tree
  return { controller, tree, scheduled, cancelled, observers, scrollStarts: () => scrollStarts }
}

test('virtualizes rows with fixed overscan and maps the scroll offset into its canvas', () => {
  const { controller, tree, scheduled, scrollStarts } = createController()
  controller.mountVirtualTree()
  assert.equal(controller.virtualLibraryNodes.value.length, 26)
  assert.deepEqual(controller.virtualTreeCanvasStyle.value, { height: '2600px' })

  tree.scrollTop = 520
  controller.handleTreeScroll({ currentTarget: tree })
  assert.equal(scrollStarts(), 1)
  assert.equal(controller.treeIsScrolling.value, true)
  assert.deepEqual(controller.virtualLibraryNodes.value.map((node) => node.id), Array.from({ length: 26 }, (_value, index) => index + 8))
  assert.deepEqual(controller.virtualTreeListStyle.value, { transform: 'translateY(208px)' })
  assert.equal(scheduled[0].delay, 80)
  scheduled[0].callback()
  assert.equal(controller.treeIsScrolling.value, false)
})

test('updates viewport height through ResizeObserver and releases observer and timer resources', () => {
  const { controller, tree, scheduled, cancelled, observers } = createController()
  controller.mountVirtualTree()
  tree.clientHeight = 78
  observers[0].callback()
  assert.equal(controller.virtualLibraryNodes.value.length, 27)

  controller.handleTreeScroll({ currentTarget: tree })
  controller.disposeVirtualTree()
  assert.equal(observers[0].disconnected, true)
  assert.deepEqual(cancelled, [scheduled[0]])
  assert.equal(controller.treeIsScrolling.value, false)
})
