import { nextTick, ref, watch } from 'vue'

import {
  activeTimelineSegmentKey,
  mediaTranscriptState,
  timelineSegmentKey,
} from './mediaTranscriptModel.js'
import {
  clampVerticalContentSplit,
  verticalContentSplitBounds,
} from './splitterDragState.js'

const MEDIA_TRANSCRIPT_HEIGHT_KEY = 'knowledgehub.media-transcript-height.v1'
const XHS_IMAGE_TEXT_HEIGHT_KEY = 'knowledgehub.xhs-image-text-height.v1'

function readStoredVerticalSplit(key) {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isFinite(value) ? Math.max(25, Math.min(75, value)) : 56
  } catch {
    return 56
  }
}

export function useMediaTranscriptWorkspaceController({
  contentHero,
  activeContentTab,
  activePlayer,
  contentForTab,
  isAudioTab,
  isArticleTab,
  isTimedMediaTab,
  resultForTab,
  transcriptForTab,
}) {
  const mediaTranscriptHeight = ref(readStoredVerticalSplit(MEDIA_TRANSCRIPT_HEIGHT_KEY))
  const mediaTranscriptResizing = ref(false)
  const xhsImageTextHeight = ref(readStoredVerticalSplit(XHS_IMAGE_TEXT_HEIGHT_KEY))
  const xhsImageTextResizing = ref(false)
  const currentPlaybackTime = ref(0)
  const activeTimelineKey = ref('')
  const transcriptAutoFollow = ref(true)
  const isAudioPlaying = ref(false)
  const timelineSegmentRefs = new Map()
  let transcriptScrollTimer = null
  let mediaTranscriptResizeStart = null
  let xhsImageTextResizeStart = null
  let contentHeroResizeObserver = null

  function timelineSegmentsForTab(tabId) {
    const content = contentForTab(tabId)
    return mediaTranscriptState({
      isTimedMedia: isTimedMediaTab(tabId),
      contentStatus: content?.status,
      segments: content?.transcript_segments,
      fallbackTranscript: transcriptForTab(tabId),
      taskStatus: resultForTab(tabId)?.status,
      taskStep: resultForTab(tabId)?.step,
    }).timelineSegments
  }

  function hasTranscriptTimeline(tabId) {
    // Documents can expose text for search and reader metadata. That text
    // must not turn a Markdown/report reader into a timed-media workspace.
    return mediaTranscriptState({
      isTimedMedia: isTimedMediaTab(tabId),
      segments: contentForTab(tabId)?.transcript_segments,
      fallbackTranscript: transcriptForTab(tabId),
    }).hasTimeline
  }

  function shouldShowTranscriptGeneration(tabId) {
    const task = resultForTab(tabId) || {}
    return mediaTranscriptState({
      isTimedMedia: isTimedMediaTab(tabId),
      contentStatus: contentForTab(tabId)?.status,
      segments: contentForTab(tabId)?.transcript_segments,
      fallbackTranscript: transcriptForTab(tabId),
      taskStatus: task.status,
      taskStep: task.step,
    }).showGeneration
  }

  function hasMediaTranscriptWorkspace(tabId) {
    return hasTranscriptTimeline(tabId) || shouldShowTranscriptGeneration(tabId)
  }

  function transcriptGenerationLabel(tabId) {
    return mediaTranscriptState({ taskStep: resultForTab(tabId)?.step }).label
  }

  function transcriptGenerationDescription(tabId) {
    return mediaTranscriptState({ taskStep: resultForTab(tabId)?.step }).description
  }

  function verticalContentBounds() {
    return verticalContentSplitBounds(contentHero.value?.clientHeight || 0)
  }

  function clampVerticalContentHeight(value) {
    return clampVerticalContentSplit(value, contentHero.value?.clientHeight || 0)
  }

  function constrainVerticalContentSplits() {
    mediaTranscriptHeight.value = clampVerticalContentHeight(mediaTranscriptHeight.value)
    xhsImageTextHeight.value = clampVerticalContentHeight(xhsImageTextHeight.value)
  }

  function persistVerticalContentSplit(key, value) {
    try {
      localStorage.setItem(key, String(value))
    } catch {
      // The current layout remains usable when storage is unavailable.
    }
  }

  function lockTextSelection() {
    window.getSelection?.()?.removeAllRanges()
    document.body.classList.add('workspace-resizing')
  }

  function unlockTextSelection() {
    document.body.classList.remove('workspace-resizing')
  }

  function startMediaTranscriptResize(event) {
    const container = contentHero.value
    if (!container) return
    const rect = container.getBoundingClientRect()
    if (rect.height <= 0) return
    event.preventDefault()
    stopMediaTranscriptResize()
    lockTextSelection()
    mediaTranscriptResizeStart = {
      top: rect.top,
      height: rect.height,
      pointerId: event.pointerId,
      element: event.currentTarget,
    }
    mediaTranscriptResizing.value = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
    window.addEventListener('pointermove', resizeMediaTranscript)
    window.addEventListener('pointerup', stopMediaTranscriptResize)
    window.addEventListener('pointercancel', stopMediaTranscriptResize)
  }

  function resizeMediaTranscript(event) {
    if (!mediaTranscriptResizeStart || event.pointerId !== mediaTranscriptResizeStart.pointerId) return
    event.preventDefault()
    const offset = event.clientY - mediaTranscriptResizeStart.top
    const next = Math.round((offset / mediaTranscriptResizeStart.height) * 100)
    mediaTranscriptHeight.value = clampVerticalContentHeight(next)
  }

  function stopMediaTranscriptResize(event, shouldPersist = event?.type === 'pointerup') {
    if (event?.pointerId !== undefined && mediaTranscriptResizeStart && event.pointerId !== mediaTranscriptResizeStart.pointerId) return
    window.removeEventListener('pointermove', resizeMediaTranscript)
    window.removeEventListener('pointerup', stopMediaTranscriptResize)
    window.removeEventListener('pointercancel', stopMediaTranscriptResize)
    const resizeStart = mediaTranscriptResizeStart
    mediaTranscriptResizeStart = null
    if (resizeStart?.element?.hasPointerCapture?.(resizeStart.pointerId)) {
      resizeStart.element.releasePointerCapture?.(resizeStart.pointerId)
    }
    const wasResizing = mediaTranscriptResizing.value
    mediaTranscriptResizing.value = false
    unlockTextSelection()
    if (shouldPersist && wasResizing) {
      persistVerticalContentSplit(MEDIA_TRANSCRIPT_HEIGHT_KEY, mediaTranscriptHeight.value)
    }
  }

  function handleMediaTranscriptKeydown(event) {
    const bounds = verticalContentBounds()
    let next = mediaTranscriptHeight.value
    if (event.key === 'ArrowUp') next -= 5
    else if (event.key === 'ArrowDown') next += 5
    else if (event.key === 'Home') next = bounds.min
    else if (event.key === 'End') next = bounds.max
    else return
    event.preventDefault()
    mediaTranscriptHeight.value = clampVerticalContentHeight(next)
    persistVerticalContentSplit(MEDIA_TRANSCRIPT_HEIGHT_KEY, mediaTranscriptHeight.value)
  }

  function startXhsImageTextResize(event) {
    const container = contentHero.value
    if (!container) return
    const rect = container.getBoundingClientRect()
    if (rect.height <= 0) return
    event.preventDefault()
    stopXhsImageTextResize()
    lockTextSelection()
    xhsImageTextResizeStart = {
      top: rect.top,
      height: rect.height,
      pointerId: event.pointerId,
      element: event.currentTarget,
    }
    xhsImageTextResizing.value = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
    window.addEventListener('pointermove', resizeXhsImageText)
    window.addEventListener('pointerup', stopXhsImageTextResize)
    window.addEventListener('pointercancel', stopXhsImageTextResize)
  }

  function resizeXhsImageText(event) {
    if (!xhsImageTextResizeStart || event.pointerId !== xhsImageTextResizeStart.pointerId) return
    event.preventDefault()
    const offset = event.clientY - xhsImageTextResizeStart.top
    const next = Math.round((offset / xhsImageTextResizeStart.height) * 100)
    xhsImageTextHeight.value = clampVerticalContentHeight(next)
  }

  function stopXhsImageTextResize(event, shouldPersist = event?.type === 'pointerup') {
    if (event?.pointerId !== undefined && xhsImageTextResizeStart && event.pointerId !== xhsImageTextResizeStart.pointerId) return
    window.removeEventListener('pointermove', resizeXhsImageText)
    window.removeEventListener('pointerup', stopXhsImageTextResize)
    window.removeEventListener('pointercancel', stopXhsImageTextResize)
    const resizeStart = xhsImageTextResizeStart
    xhsImageTextResizeStart = null
    if (resizeStart?.element?.hasPointerCapture?.(resizeStart.pointerId)) {
      resizeStart.element.releasePointerCapture?.(resizeStart.pointerId)
    }
    const wasResizing = xhsImageTextResizing.value
    xhsImageTextResizing.value = false
    unlockTextSelection()
    if (shouldPersist && wasResizing) {
      persistVerticalContentSplit(XHS_IMAGE_TEXT_HEIGHT_KEY, xhsImageTextHeight.value)
    }
  }

  function handleXhsImageTextKeydown(event) {
    const bounds = verticalContentBounds()
    let next = xhsImageTextHeight.value
    if (event.key === 'ArrowUp') next -= 5
    else if (event.key === 'ArrowDown') next += 5
    else if (event.key === 'Home') next = bounds.min
    else if (event.key === 'End') next = bounds.max
    else return
    event.preventDefault()
    xhsImageTextHeight.value = clampVerticalContentHeight(next)
    persistVerticalContentSplit(XHS_IMAGE_TEXT_HEIGHT_KEY, xhsImageTextHeight.value)
  }

  function handlePlayerTimeUpdate(seconds) {
    const value = Number(seconds)
    currentPlaybackTime.value = Number.isFinite(value) ? value : 0
  }

  function handleAudioPlaybackChange(playing) {
    isAudioPlaying.value = Boolean(playing)
  }

  function toggleActiveAudioPlayback() {
    if (!isAudioTab(activeContentTab.value?.id)) return
    void activePlayer.value?.togglePlayback?.()
  }

  function isTimelineSegmentActive(tabId, segment) {
    return timelineSegmentKey(tabId, segment) === activeTimelineKey.value
  }

  function findActiveTimelineKey(tabId) {
    if (!tabId || tabId !== activeContentTab.value?.id) return ''
    return activeTimelineSegmentKey({
      tabId,
      activeTabId: activeContentTab.value?.id,
      segments: timelineSegmentsForTab(tabId),
      playbackTime: currentPlaybackTime.value,
    })
  }

  function setTimelineSegmentRef(tabId, segment, element) {
    const key = timelineSegmentKey(tabId, segment)
    if (element) timelineSegmentRefs.set(key, element)
    else timelineSegmentRefs.delete(key)
  }

  function scheduleActiveTranscriptScroll() {
    if (!transcriptAutoFollow.value || !activeTimelineKey.value) return
    if (transcriptScrollTimer) clearTimeout(transcriptScrollTimer)
    transcriptScrollTimer = setTimeout(async () => {
      transcriptScrollTimer = null
      await nextTick()
      if (!transcriptAutoFollow.value) return
      timelineSegmentRefs.get(activeTimelineKey.value)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }, 90)
  }

  function pauseTranscriptAutoFollow() {
    transcriptAutoFollow.value = false
  }

  function resumeTranscriptAutoFollow() {
    transcriptAutoFollow.value = true
    scheduleActiveTranscriptScroll()
  }

  function seekMedia(tabId, seconds) {
    const value = Number(seconds)
    if (!Number.isFinite(value)) return
    if (tabId !== activeContentTab.value?.id) return
    activePlayer.value?.seek(value)
  }

  function handleTimelineSegmentClick(tabId, seconds) {
    const value = Number(seconds)
    if (Number.isFinite(value)) {
      currentPlaybackTime.value = value
      activeTimelineKey.value = findActiveTimelineKey(tabId)
    }
    transcriptAutoFollow.value = true
    scheduleActiveTranscriptScroll()
    seekMedia(tabId, seconds)
  }

  function seekToTimestamp(seconds) {
    const tab = activeContentTab.value
    if (!tab || isArticleTab(tab.id) || !activePlayer.value) return false
    const value = Number(seconds)
    if (!Number.isFinite(value) || value < 0) return false
    handleTimelineSegmentClick(tab.id, value)
    return true
  }

  function resetActiveMediaState() {
    currentPlaybackTime.value = 0
    isAudioPlaying.value = false
    activeTimelineKey.value = ''
    transcriptAutoFollow.value = true
  }

  function mount() {
    constrainVerticalContentSplits()
    if (typeof ResizeObserver === 'function') {
      contentHeroResizeObserver = new ResizeObserver(() => constrainVerticalContentSplits())
      if (contentHero.value) contentHeroResizeObserver.observe(contentHero.value)
    }
  }

  function dispose() {
    stopMediaTranscriptResize()
    stopXhsImageTextResize()
    contentHeroResizeObserver?.disconnect()
    contentHeroResizeObserver = null
    if (transcriptScrollTimer) {
      clearTimeout(transcriptScrollTimer)
      transcriptScrollTimer = null
    }
    timelineSegmentRefs.clear()
  }

  watch(
    () => [
      activeContentTab.value?.id || '',
      currentPlaybackTime.value,
      timelineSegmentsForTab(activeContentTab.value?.id)
        .map((segment) => `${segment.position}:${segment.start_seconds}`)
        .join('|'),
    ],
    () => {
      activeTimelineKey.value = findActiveTimelineKey(activeContentTab.value?.id)
    },
    { flush: 'post' },
  )

  watch(activeTimelineKey, () => {
    scheduleActiveTranscriptScroll()
  }, { flush: 'post' })

  watch(contentHero, (element, previousElement) => {
    if (previousElement) contentHeroResizeObserver?.unobserve(previousElement)
    if (element) {
      contentHeroResizeObserver?.observe(element)
      constrainVerticalContentSplits()
    }
  }, { flush: 'post' })

  return {
    dispose,
    handleAudioPlaybackChange,
    handleMediaTranscriptKeydown,
    handlePlayerTimeUpdate,
    handleTimelineSegmentClick,
    handleXhsImageTextKeydown,
    hasMediaTranscriptWorkspace,
    hasTranscriptTimeline,
    isAudioPlaying,
    isTimelineSegmentActive,
    mediaTranscriptHeight,
    mediaTranscriptResizing,
    mount,
    pauseTranscriptAutoFollow,
    resetActiveMediaState,
    resumeTranscriptAutoFollow,
    seekToTimestamp,
    setTimelineSegmentRef,
    shouldShowTranscriptGeneration,
    startMediaTranscriptResize,
    startXhsImageTextResize,
    timelineSegmentsForTab,
    transcriptAutoFollow,
    transcriptGenerationDescription,
    transcriptGenerationLabel,
    toggleActiveAudioPlayback,
    verticalContentBounds,
    xhsImageTextHeight,
    xhsImageTextResizing,
  }
}
