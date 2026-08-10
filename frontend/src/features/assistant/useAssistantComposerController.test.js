import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, reactive } from 'vue'
import { useAssistantComposerController } from './useAssistantComposerController.js'

function createProps() {
  return reactive({
    articleOcrStatus: { status: 'unavailable', has_images: false, priority: false },
    askingQuestion: false,
    availableAiModels: [{ value: 'deepseek-v4-pro:enabled', label: 'V4 Pro Thinking' }],
    contentAnalysisTemplates: [{ id: 'one', name: '提炼观点', is_active: true }],
    currentInsightHtml: '',
    currentQaEnabled: true,
    currentQaHint: '',
    generatingAiSummary: false,
    prioritizingArticleOcr: false,
    qaHistory: [],
    qaShortcutTemplates: [{ id: 'summary', name: '总结', template: '总结正文' }],
    questionInput: '',
    selectedAiModel: 'deepseek-v4-flash:enabled',
    selectedTextContext: null,
  })
}

function createHarness(overrides = {}) {
  const props = createProps()
  Object.assign(props, overrides)
  const events = []
  const frames = []
  const timers = new Map()
  const cancelledTimers = []
  const listeners = new Set()
  let nextTimer = 1
  const scheduleNextTick = (callback) => {
    callback?.()
    return Promise.resolve()
  }
  const scope = effectScope()
  const controller = scope.run(() => useAssistantComposerController({
    props,
    emit: (...args) => events.push(args),
    scheduleNextTick,
    scheduleFrame: (callback) => frames.push(callback),
    scheduleTimer: (callback, delay) => {
      const id = nextTimer++
      timers.set(id, { callback, delay })
      return id
    },
    cancelTimer: (id) => {
      cancelledTimers.push(id)
      timers.delete(id)
    },
    readMaxHeight: () => 121,
    addPointerDownListener: (handler) => listeners.add(handler),
    removePointerDownListener: (handler) => listeners.delete(handler),
  }))
  return { props, events, frames, timers, cancelledTimers, listeners, scope, controller }
}

test('coordinates model and shortcut menus without leaking outside clicks', () => {
  const harness = createHarness()
  const { controller, events, listeners } = harness
  const insideModel = {}
  const insideShortcut = {}
  controller.modelMenuRef.value = { contains: (target) => target === insideModel }
  controller.shortcutMenuRef.value = { contains: (target) => target === insideShortcut }
  controller.shortcutSuggestionsRef.value = { contains: (target) => target === insideShortcut }
  controller.mount()

  controller.toggleModelMenu()
  assert.equal(controller.modelMenuOpen.value, true)
  controller.toggleShortcutMenu()
  assert.equal(controller.modelMenuOpen.value, false)
  assert.equal(controller.shortcutMenuOpen.value, true)
  controller.handleMenuFocusOut('shortcut', { relatedTarget: insideShortcut })
  assert.equal(controller.shortcutMenuOpen.value, true)
  listeners.values().next().value({ target: insideModel })
  assert.equal(controller.shortcutMenuOpen.value, false)

  controller.toggleModelMenu()
  controller.selectAiModel('deepseek-v4-pro:enabled')
  controller.toggleShortcutMenu()
  controller.insertShortcut('总结')
  assert.deepEqual(events, [
    ['update:selectedAiModel', 'deepseek-v4-pro:enabled'],
    ['insert-shortcut', '总结'],
  ])
  assert.equal(controller.modelMenuOpen.value, false)
  assert.equal(controller.shortcutMenuOpen.value, false)
  controller.dispose()
  assert.equal(listeners.size, 0)
  harness.scope.stop()
})

test('projects composer choices, shortcuts, OCR hints and action availability', async () => {
  const { controller, props, scope } = createHarness()
  assert.deepEqual(controller.aiModelOptions.value.map((item) => item.value), [
    'deepseek-v4-flash:enabled',
    'deepseek-v4-pro:enabled',
  ])
  assert.equal(controller.selectedAiModelLabel.value, 'V4 Flash Thinking')
  assert.equal(controller.customActionLabel.value, '提炼观点')
  assert.equal(controller.qaShortcutButtons.value[0].name, '总结')
  props.questionInput = '请 @总'
  await nextTick()
  assert.deepEqual(controller.shortcutSuggestions.value.map((item) => item.name), ['总结'])

  props.articleOcrStatus = { status: 'queued', priority: false }
  await nextTick()
  assert.equal(controller.showOcrControl.value, true)
  assert.equal(controller.canPrioritizeOcr.value, true)
  assert.equal(controller.questionPlaceholder.value, '图片文字仍在解析；现在生成仅包含正文。')
  props.currentInsightHtml = '<p>摘要</p>'
  await nextTick()
  assert.equal(controller.hasExportableConversation.value, true)
  scope.stop()
})

test('resizes, sends and releases the composer lifecycle exactly once', async () => {
  const harness = createHarness()
  const { controller, props, events, frames, timers, cancelledTimers, listeners, scope } = harness
  const input = {
    value: '问题',
    scrollHeight: 180,
    style: {},
    focus: () => {},
  }
  controller.questionInputRef.value = input
  controller.mount()
  controller.mount()
  assert.equal(listeners.size, 1)
  assert.deepEqual(input.style, { height: '121px', overflowY: 'auto' })

  controller.handleQuestionInput({ target: input })
  assert.deepEqual(events, [['update:questionInput', '问题']])
  controller.handleAskKeydown({ isComposing: true })
  assert.equal(frames.length, 0)
  props.questionInput = '问题'
  await nextTick()
  controller.handleAskKeydown({ isComposing: false })
  assert.equal(frames.length, 1)
  assert.deepEqual(events.at(-1), ['ask-question'])
  frames[0]()
  assert.equal(controller.sendLaunchActive.value, true)
  const [firstTimerId, firstTimer] = timers.entries().next().value
  assert.equal(firstTimer.delay, 600)
  controller.triggerQuestionSend()
  assert.deepEqual(cancelledTimers, [firstTimerId])
  const [secondTimerId, secondTimer] = [...timers.entries()].at(-1)
  assert.notEqual(secondTimerId, firstTimerId)
  secondTimer.callback()
  assert.equal(controller.sendLaunchActive.value, false)

  controller.triggerQuestionSend()
  controller.dispose()
  assert.equal(listeners.size, 0)
  assert.equal(cancelledTimers.includes(secondTimerId), false)
  assert.equal(cancelledTimers.length, 2)
  scope.stop()
})

test('focuses an existing or newly selected text context without reacting to clear or same-id updates', async () => {
  const harness = createHarness({ selectedTextContext: { id: 'selection:one' } })
  const { controller, props, scope } = harness
  const focusCalls = []
  controller.questionInputRef.value = {
    scrollHeight: 21,
    style: {},
    focus: (options) => focusCalls.push(options),
  }
  controller.mount()
  assert.deepEqual(focusCalls, [{ preventScroll: true }])

  props.selectedTextContext = { id: 'selection:one', text: '更新内容' }
  await nextTick()
  props.selectedTextContext = null
  await nextTick()
  assert.equal(focusCalls.length, 1)
  props.selectedTextContext = { id: 'selection:two' }
  await nextTick()
  assert.deepEqual(focusCalls, [
    { preventScroll: true },
    { preventScroll: true },
  ])
  controller.dispose()
  scope.stop()
})
