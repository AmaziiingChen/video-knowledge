import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useTreeBoxSelectionController } from './useTreeBoxSelectionController.js'

function treeNode(key, left, top, right, bottom) {
  return {
    dataset: { nodeKey: key },
    getBoundingClientRect: () => ({ left, top, right, bottom }),
  }
}

function createController() {
  const listeners = new Map()
  const treeRef = ref({
    scrollTop: 20,
    getBoundingClientRect: () => ({ left: 100, top: 50 }),
    setPointerCapture: () => {},
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: (name) => listeners.delete(name),
    querySelectorAll: () => [
      treeNode('content:one', 110, 80, 240, 104),
      treeNode('content:two', 110, 108, 240, 132),
      treeNode('content:three', 110, 170, 240, 194),
    ],
  })
  const selectedKeys = ref(new Set(['content:existing']))
  const anchors = []
  const controller = useTreeBoxSelectionController({
    treeRef,
    selectedKeys,
    setSelectedKeys: (keys) => { selectedKeys.value = new Set(keys) },
    setAnchorKey: (key) => anchors.push(key),
    isElement: (value) => Boolean(value?.isElement),
  })
  return { controller, listeners, selectedKeys, anchors }
}

test('box selection replaces the selection with intersecting visible tree rows', () => {
  const { controller, listeners, selectedKeys, anchors } = createController()
  controller.startBoxSelection({
    button: 0,
    target: { isElement: true, closest: () => null },
    pointerId: 1,
    clientX: 105,
    clientY: 75,
    metaKey: false,
    ctrlKey: false,
  })
  controller.updateBoxSelection({ clientX: 245, clientY: 135 })

  assert.deepEqual([...selectedKeys.value].sort(), ['content:one', 'content:two'])
  assert.deepEqual(controller.selectionBox.value, { left: 5, top: 45, width: 140, height: 60 })
  controller.finishBoxSelection()
  assert.equal(controller.selectionBox.value, null)
  assert.equal(listeners.has('pointermove'), false)
  assert.deepEqual(anchors, ['content:two'])
})

test('additive box selection retains the existing selection and ignores row gestures', () => {
  const { controller, listeners, selectedKeys } = createController()
  controller.startBoxSelection({
    button: 0,
    target: { isElement: true, closest: () => ({}) },
    clientX: 105,
    clientY: 75,
  })
  assert.equal(listeners.size, 0)

  controller.startBoxSelection({
    button: 0,
    target: { isElement: true, closest: () => null },
    pointerId: 1,
    clientX: 105,
    clientY: 75,
    metaKey: true,
    ctrlKey: false,
  })
  controller.updateBoxSelection({ clientX: 245, clientY: 105 })
  assert.deepEqual([...selectedKeys.value].sort(), ['content:existing', 'content:one'])
  controller.cancelBoxSelection()
  assert.equal(listeners.has('pointermove'), false)
})
