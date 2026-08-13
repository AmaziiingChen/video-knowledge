import { computed, ref } from 'vue'

export function useVirtualLibraryTreeController({
  renderedLibraryNodes,
  onScrollStart = () => {},
  rowHeight = 26,
  overscan = 12,
  schedule = (callback, delay) => window.setTimeout(callback, delay),
  cancelSchedule = (timer) => window.clearTimeout(timer),
  createResizeObserver = (callback) => new ResizeObserver(callback),
}) {
  const treeRef = ref(null)
  const treeScrollTop = ref(0)
  const treeViewportHeight = ref(0)
  const treeIsScrolling = ref(false)
  let resizeObserver = null
  let scrollEndTimer = null

  const virtualTreeStart = computed(() => {
    if (!renderedLibraryNodes.value.length) return 0
    return Math.max(0, Math.floor(treeScrollTop.value / rowHeight) - overscan)
  })

  const virtualTreeEnd = computed(() => {
    const viewportRows = Math.ceil(treeViewportHeight.value / rowHeight)
    return Math.min(
      renderedLibraryNodes.value.length,
      virtualTreeStart.value + viewportRows + overscan * 2,
    )
  })

  const virtualLibraryNodes = computed(() => (
    renderedLibraryNodes.value.slice(virtualTreeStart.value, virtualTreeEnd.value)
  ))

  const virtualTreeCanvasStyle = computed(() => ({
    height: `${renderedLibraryNodes.value.length * rowHeight}px`,
  }))

  const virtualTreeListStyle = computed(() => ({
    transform: `translateY(${virtualTreeStart.value * rowHeight}px)`,
  }))

  function handleTreeScroll(event) {
    onScrollStart()
    treeScrollTop.value = event.currentTarget.scrollTop
    treeIsScrolling.value = true
    if (scrollEndTimer) cancelSchedule(scrollEndTimer)
    scrollEndTimer = schedule(() => {
      scrollEndTimer = null
      treeIsScrolling.value = false
    }, 80)
  }

  function mountVirtualTree() {
    const tree = treeRef.value
    if (!tree) return
    treeScrollTop.value = tree.scrollTop
    treeViewportHeight.value = tree.clientHeight
    resizeObserver = createResizeObserver(() => {
      treeViewportHeight.value = tree.clientHeight
    })
    resizeObserver.observe(tree)
  }

  function disposeVirtualTree() {
    resizeObserver?.disconnect()
    resizeObserver = null
    if (scrollEndTimer) cancelSchedule(scrollEndTimer)
    scrollEndTimer = null
    treeIsScrolling.value = false
  }

  return {
    treeRef,
    treeIsScrolling,
    virtualLibraryNodes,
    virtualTreeCanvasStyle,
    virtualTreeListStyle,
    handleTreeScroll,
    mountVirtualTree,
    disposeVirtualTree,
  }
}
