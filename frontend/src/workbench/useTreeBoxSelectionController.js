import { computed, ref } from 'vue'

export function useTreeBoxSelectionController({
  treeRef,
  selectedKeys,
  setSelectedKeys = (keys) => { selectedKeys.value = new Set(keys) },
  setAnchorKey = () => {},
  isElement = (value) => typeof Element !== 'undefined' && value instanceof Element,
}) {
  const selectionBox = ref(null)
  const selectionStart = ref(null)

  const selectionBoxStyle = computed(() => {
    const box = selectionBox.value
    if (!box) return {}
    return {
      left: `${box.left}px`,
      top: `${box.top}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    }
  })

  function startBoxSelection(event) {
    if (event.button !== 0) return
    const target = isElement(event.target) ? event.target : null
    if (target?.closest('[data-node-key],button,input,.sidebar-tree-row-actions,.sidebar-selection-bar,.el-popper')) return
    const tree = treeRef.value
    if (!tree) return
    tree.setPointerCapture?.(event.pointerId)
    const rect = tree.getBoundingClientRect()
    selectionStart.value = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top + tree.scrollTop,
      additive: event.metaKey || event.ctrlKey,
      base: new Set(event.metaKey || event.ctrlKey ? selectedKeys.value : []),
    }
    selectionBox.value = {
      left: selectionStart.value.x,
      top: selectionStart.value.y,
      width: 0,
      height: 0,
    }
    tree.addEventListener('pointermove', updateBoxSelection)
    tree.addEventListener('pointerup', finishBoxSelection, { once: true })
  }

  function updateBoxSelection(event) {
    const tree = treeRef.value
    const start = selectionStart.value
    if (!tree || !start) return
    const rect = tree.getBoundingClientRect()
    const currentX = event.clientX - rect.left
    const currentY = event.clientY - rect.top + tree.scrollTop
    const left = Math.min(start.x, currentX)
    const top = Math.min(start.y, currentY)
    const right = Math.max(start.x, currentX)
    const bottom = Math.max(start.y, currentY)
    selectionBox.value = {
      left,
      top,
      width: right - left,
      height: bottom - top,
    }
    const next = new Set(start.base)
    tree.querySelectorAll('[data-node-key]').forEach((element) => {
      const nodeRect = element.getBoundingClientRect()
      const nodeBox = {
        left: nodeRect.left - rect.left,
        right: nodeRect.right - rect.left,
        top: nodeRect.top - rect.top + tree.scrollTop,
        bottom: nodeRect.bottom - rect.top + tree.scrollTop,
      }
      const intersects = nodeBox.left < right
        && nodeBox.right > left
        && nodeBox.top < bottom
        && nodeBox.bottom > top
      if (intersects) next.add(element.dataset.nodeKey)
    })
    setSelectedKeys(next)
  }

  function finishBoxSelection() {
    cancelBoxSelection()
    setAnchorKey([...selectedKeys.value].at(-1) || null)
  }

  function cancelBoxSelection() {
    treeRef.value?.removeEventListener('pointermove', updateBoxSelection)
    selectionBox.value = null
    selectionStart.value = null
  }

  return {
    selectionBox,
    selectionBoxStyle,
    startBoxSelection,
    updateBoxSelection,
    finishBoxSelection,
    cancelBoxSelection,
  }
}
