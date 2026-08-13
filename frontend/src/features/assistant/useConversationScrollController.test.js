import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, reactive } from 'vue'
import { useConversationScrollController } from './useConversationScrollController.js'

function createProps() {
  return reactive({
    askingQuestion: false,
    conversationKey: 'content:one',
    currentInsightHtml: '',
    generatingAiSummary: false,
    generatingSummaryText: '',
    qaHistory: [],
    qaHistoryHasMore: true,
    qaHistoryLoading: false,
    qaHistoryLoadingMore: false,
  })
}

function createContainer({ height = 1_000, top = 20 } = {}) {
  return {
    clientHeight: 300,
    scrollHeight: height,
    scrollTop: top,
    scrollToCalls: [],
    scrollTo(options) {
      this.scrollToCalls.push(options)
      this.scrollTop = options.top
    },
  }
}

test('loads earlier history once and restores the reader position after it arrives', async () => {
  const props = createProps()
  const events = []
  const scope = effectScope()
  const controller = scope.run(() => useConversationScrollController({
    props,
    emit: (...args) => events.push(args),
    scheduleFrame: () => 1,
    cancelFrame: () => {},
    scheduleNextTick: (callback) => callback(),
    isElement: () => false,
  }))
  const container = createContainer()
  controller.conversationRef.value = container

  controller.handleConversationScroll()
  controller.handleConversationScroll()
  assert.deepEqual(events, [['load-more-qa-history']])

  props.qaHistoryLoadingMore = true
  await nextTick()
  container.scrollHeight = 1_350
  props.qaHistory = [{ answer: '更早的回答' }]
  props.qaHistoryLoadingMore = false
  await nextTick()

  assert.equal(container.scrollTop, 370)
  scope.stop()
})

test('keeps auto-follow opt-in and forwards valid timestamp links to the media reader', async () => {
  const props = createProps()
  const events = []
  const frames = []
  const scope = effectScope()
  const controller = scope.run(() => useConversationScrollController({
    props,
    emit: (...args) => events.push(args),
    scheduleFrame: (callback) => {
      frames.push(callback)
      return frames.length
    },
    cancelFrame: () => {},
    scheduleNextTick: (callback) => callback(),
    isElement: () => true,
  }))
  const container = createContainer({ height: 1_200, top: 900 })
  controller.conversationRef.value = container

  props.askingQuestion = true
  await nextTick()
  frames.at(-1)()
  assert.deepEqual(container.scrollToCalls, [{ top: 1_200, behavior: 'auto' }])

  controller.handleConversationWheel({ deltaY: -1 })
  props.currentInsightHtml = '流式回答'
  await nextTick()
  assert.equal(frames.length, 1)

  let prevented = false
  controller.handleTimestampLinkClick({
    target: { closest: () => ({ href: 'https://local.test/article#video-t=18.5' }) },
    preventDefault: () => { prevented = true },
  })
  assert.equal(prevented, true)
  assert.deepEqual(events, [['seek-video', 18.5]])
  scope.stop()
})
