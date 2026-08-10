import { computed, nextTick, ref, watch } from 'vue'
import {
  assistantAiModelOptions,
  assistantQuestionPlaceholder,
  assistantSelectedModelLabel,
  customContentActionLabel,
  hasExportableConversation as hasExportableConversationForContent,
  ocrAssistantPresentation,
  qaShortcutButtons as buildQaShortcutButtons,
  shortcutSuggestions as findShortcutSuggestions,
} from './assistantPresentation.js'

export function useAssistantComposerController({
  props,
  emit,
  scheduleNextTick = nextTick,
  scheduleFrame = (callback) => requestAnimationFrame(callback),
  scheduleTimer = (callback, delay) => window.setTimeout(callback, delay),
  cancelTimer = (timer) => clearTimeout(timer),
  readMaxHeight = (input) => Number.parseFloat(window.getComputedStyle(input).maxHeight),
  addPointerDownListener = (handler) => document.addEventListener('pointerdown', handler),
  removePointerDownListener = (handler) => document.removeEventListener('pointerdown', handler),
}) {
  const modelMenuOpen = ref(false)
  const shortcutMenuOpen = ref(false)
  const modelMenuRef = ref(null)
  const shortcutMenuRef = ref(null)
  const shortcutSuggestionsRef = ref(null)
  const questionInputRef = ref(null)
  const sendLaunchActive = ref(false)
  let sendLaunchTimer = null
  let mounted = false

  const aiModelOptions = computed(() => (
    assistantAiModelOptions(props.selectedAiModel, props.availableAiModels)
  ))
  const selectedAiModelLabel = computed(() => (
    assistantSelectedModelLabel(props.selectedAiModel, aiModelOptions.value)
  ))
  const customActionLabel = computed(() => customContentActionLabel(props.contentAnalysisTemplates))
  const customActionLoading = computed(() => props.askingQuestion && !props.generatingAiSummary)
  const qaShortcutButtons = computed(() => buildQaShortcutButtons(props.qaShortcutTemplates))
  const shortcutSuggestions = computed(() => (
    findShortcutSuggestions(props.questionInput, qaShortcutButtons.value)
  ))
  const hasExportableConversation = computed(() => (
    hasExportableConversationForContent(props.currentInsightHtml, props.qaHistory)
  ))
  const ocrPresentation = computed(() => (
    ocrAssistantPresentation(props.articleOcrStatus, props.prioritizingArticleOcr)
  ))
  const showOcrControl = computed(() => ocrPresentation.value.show)
  const canPrioritizeOcr = computed(() => ocrPresentation.value.canPrioritize)
  const ocrControlLabel = computed(() => ocrPresentation.value.label)
  const ocrControlTooltip = computed(() => ocrPresentation.value.tooltip)
  const questionPlaceholder = computed(() => assistantQuestionPlaceholder({
    ocrInputHint: ocrPresentation.value.inputHint,
    selectedTextContext: props.selectedTextContext,
    currentQaHint: props.currentQaHint,
    currentQaEnabled: props.currentQaEnabled,
  }))

  function selectAiModel(model) {
    emit('update:selectedAiModel', model)
    modelMenuOpen.value = false
  }

  function closeAssistantMenus() {
    modelMenuOpen.value = false
    shortcutMenuOpen.value = false
  }

  function toggleModelMenu() {
    const shouldOpen = !modelMenuOpen.value
    closeAssistantMenus()
    modelMenuOpen.value = shouldOpen
  }

  function toggleShortcutMenu() {
    const shouldOpen = !shortcutMenuOpen.value
    closeAssistantMenus()
    shortcutMenuOpen.value = shouldOpen
  }

  function handleMenuFocusOut(menu, event) {
    const container = menu === 'model' ? modelMenuRef.value : shortcutMenuRef.value
    if (container?.contains(event.relatedTarget)) return
    if (menu === 'shortcut' && shortcutSuggestionsRef.value?.contains(event.relatedTarget)) return
    if (menu === 'model') modelMenuOpen.value = false
    else shortcutMenuOpen.value = false
  }

  function handleOutsidePointerDown(event) {
    if (modelMenuOpen.value && !modelMenuRef.value?.contains(event.target)) modelMenuOpen.value = false
    if (
      shortcutMenuOpen.value
      && !shortcutMenuRef.value?.contains(event.target)
      && !shortcutSuggestionsRef.value?.contains(event.target)
    ) shortcutMenuOpen.value = false
  }

  function insertShortcut(name) {
    shortcutMenuOpen.value = false
    emit('insert-shortcut', name)
  }

  function resizeQuestionInput(input = questionInputRef.value) {
    if (!input) return
    input.style.height = 'auto'
    const maxHeight = readMaxHeight(input)
    const nextHeight = Number.isFinite(maxHeight)
      ? Math.min(input.scrollHeight, maxHeight)
      : input.scrollHeight
    input.style.height = `${nextHeight}px`
    input.style.overflowY = Number.isFinite(maxHeight) && input.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }

  function handleQuestionInput(event) {
    emit('update:questionInput', event.target.value)
    resizeQuestionInput(event.target)
  }

  function triggerQuestionSend() {
    if (!props.questionInput.trim() || props.askingQuestion || !props.currentQaEnabled) return
    sendLaunchActive.value = false
    scheduleFrame(() => {
      sendLaunchActive.value = true
    })
    if (sendLaunchTimer !== null) cancelTimer(sendLaunchTimer)
    sendLaunchTimer = scheduleTimer(() => {
      sendLaunchActive.value = false
      sendLaunchTimer = null
    }, 600)
    emit('ask-question')
  }

  function handleAskKeydown(event) {
    if (event.isComposing) return
    triggerQuestionSend()
  }

  function mount() {
    if (mounted) return
    mounted = true
    addPointerDownListener(handleOutsidePointerDown)
    scheduleNextTick(() => resizeQuestionInput())
    if (props.selectedTextContext?.id) {
      scheduleNextTick(() => questionInputRef.value?.focus({ preventScroll: true }))
    }
  }

  function dispose() {
    if (mounted) removePointerDownListener(handleOutsidePointerDown)
    mounted = false
    if (sendLaunchTimer !== null) {
      cancelTimer(sendLaunchTimer)
      sendLaunchTimer = null
    }
  }

  watch(() => props.selectedTextContext?.id || '', async (contextId) => {
    if (!contextId) return
    await scheduleNextTick()
    questionInputRef.value?.focus({ preventScroll: true })
  })

  watch(() => props.questionInput, () => {
    scheduleNextTick(() => resizeQuestionInput())
  })

  return {
    modelMenuOpen,
    shortcutMenuOpen,
    modelMenuRef,
    shortcutMenuRef,
    shortcutSuggestionsRef,
    questionInputRef,
    sendLaunchActive,
    aiModelOptions,
    selectedAiModelLabel,
    customActionLabel,
    customActionLoading,
    qaShortcutButtons,
    shortcutSuggestions,
    hasExportableConversation,
    showOcrControl,
    canPrioritizeOcr,
    ocrControlLabel,
    ocrControlTooltip,
    questionPlaceholder,
    selectAiModel,
    closeAssistantMenus,
    toggleModelMenu,
    toggleShortcutMenu,
    handleMenuFocusOut,
    insertShortcut,
    resizeQuestionInput,
    handleQuestionInput,
    handleAskKeydown,
    triggerQuestionSend,
    mount,
    dispose,
  }
}
