import assert from 'node:assert/strict'
import test from 'node:test'

import { nextTick, ref } from 'vue'

import { useMediaTranscriptWorkspaceController } from './useMediaTranscriptWorkspaceController.js'

function createController({ activeTabId = 'media:1', task = {} } = {}) {
  const activeContentTab = ref({ id: activeTabId })
  const activePlayer = ref({
    seek: (seconds) => { activePlayer.value.lastSeek = seconds },
    togglePlayback: () => { activePlayer.value.toggleCount = (activePlayer.value.toggleCount || 0) + 1 },
  })
  const content = {
    id: 'media:1',
    status: 'processing',
    transcript_segments: [
      { position: 0, start_seconds: 0, text: '第一段' },
      { position: 1, start_seconds: 10, text: '第二段' },
    ],
  }
  const controller = useMediaTranscriptWorkspaceController({
    contentHero: ref(null),
    activeContentTab,
    activePlayer,
    contentForTab: (tabId) => (tabId === 'media:1' ? content : null),
    isAudioTab: (tabId) => tabId === 'audio:1',
    isArticleTab: (tabId) => tabId.startsWith('article:'),
    isTimedMediaTab: (tabId) => tabId === 'media:1' || tabId === 'audio:1',
    resultForTab: () => task,
    transcriptForTab: () => '',
  })
  return { activeContentTab, activePlayer, controller }
}

test('derives a timed-media transcript workspace from injected content readers', () => {
  const { controller } = createController()

  assert.equal(controller.hasMediaTranscriptWorkspace('media:1'), true)
  assert.equal(controller.hasTranscriptTimeline('media:1'), true)
  assert.deepEqual(
    controller.timelineSegmentsForTab('media:1').map((segment) => segment.text),
    ['第一段', '第二段'],
  )
  assert.equal(controller.hasMediaTranscriptWorkspace('article:1'), false)
})

test('uses the current tab and player boundary when seeking a transcript segment', async () => {
  const { activePlayer, controller } = createController()

  controller.handlePlayerTimeUpdate(12)
  await nextTick()
  assert.equal(controller.isTimelineSegmentActive('media:1', { position: 1 }), true)

  assert.equal(controller.seekToTimestamp(5), true)
  assert.equal(activePlayer.value.lastSeek, 5)
})

test('keeps article tabs outside seeking and limits playback toggles to audio tabs', () => {
  const { activeContentTab, activePlayer, controller } = createController()

  activeContentTab.value = { id: 'article:1' }
  assert.equal(controller.seekToTimestamp(5), false)
  assert.equal(activePlayer.value.lastSeek, undefined)

  controller.toggleActiveAudioPlayback()
  assert.equal(activePlayer.value.toggleCount, undefined)

  activeContentTab.value = { id: 'audio:1' }
  controller.toggleActiveAudioPlayback()
  assert.equal(activePlayer.value.toggleCount, 1)
})
