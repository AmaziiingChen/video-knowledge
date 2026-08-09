import { nextTick, ref } from 'vue'

export function useXhsGalleryController({ activeContentTab, articlePreviewForTab }) {
  const xhsGalleryTrack = ref(null)
  const xhsGalleryIndex = ref(0)

  function xhsGalleryImageCount(tabId) {
    return articlePreviewForTab(tabId)?.gallery?.length || 0
  }

  function canNavigateXhsGallery(tabId, direction) {
    const next = xhsGalleryIndex.value + direction
    return next >= 0 && next < xhsGalleryImageCount(tabId)
  }

  function scrollXhsGallery(direction) {
    const track = xhsGalleryTrack.value
    if (!track) return
    const count = xhsGalleryImageCount(activeContentTab.value?.id)
    const next = Math.max(0, Math.min(Math.max(0, count - 1), xhsGalleryIndex.value + direction))
    if (next === xhsGalleryIndex.value) return
    xhsGalleryIndex.value = next
    track.scrollTo({ left: next * track.clientWidth, behavior: 'smooth' })
  }

  function syncXhsGalleryPosition() {
    const track = xhsGalleryTrack.value
    if (!track || track.clientWidth <= 0) return
    const count = xhsGalleryImageCount(activeContentTab.value?.id)
    xhsGalleryIndex.value = Math.max(0, Math.min(Math.max(0, count - 1), Math.round(track.scrollLeft / track.clientWidth)))
  }

  function handleXhsGalleryKeydown(event) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    scrollXhsGallery(event.key === 'ArrowLeft' ? -1 : 1)
  }

  function resetXhsGallery() {
    xhsGalleryIndex.value = 0
    void nextTick(() => xhsGalleryTrack.value?.scrollTo({ left: 0, behavior: 'auto' }))
  }

  return {
    xhsGalleryTrack,
    xhsGalleryIndex,
    xhsGalleryImageCount,
    canNavigateXhsGallery,
    scrollXhsGallery,
    syncXhsGalleryPosition,
    handleXhsGalleryKeydown,
    resetXhsGallery,
  }
}
