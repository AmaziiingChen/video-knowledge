import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { requestDestructiveConfirmation } from './useDestructiveConfirm'
import {
  contentStatusOptions,
  modelProfiles,
  preferredModelOrder,
  promptTaskOptions,
  ribbonItems,
  stages,
  stepNames,
  terminalStatuses,
  timingOrder
} from '../config/workbenchOptions'
import { promptTemplateDisplayName, promptTemplatePersistedName } from '../config/promptInterface'
import { appearanceThemes, DESKTOP_ASR_POLICY, normalizeAppearanceTheme } from '../config/desktopPresentation'
import {
  makeContentTab,
  tabIdForContent
} from '../workbench/workspaceModel'
import { qaHistoryForPrompt, savedQaHistoryItems } from '../features/assistant/qaHistory'
import { matchQaShortcut } from '../features/assistant/qaShortcutMatcher'
import {
  assistantSummaryFromMarkdown,
  documentMarkdownWithoutConversation,
  reportMarkdownForCenter,
  sourceMarkdownForCenter
} from '../features/assistant/assistantMarkdown'
import { createQaStreamRenderer } from '../features/assistant/qaStreamRenderer'
import {
  mergeUniqueContentItems,
  progressiveTaskSnapshot,
  shouldHydrateProgressiveTask,
  shouldRefreshContentForTask,
  taskContentSnapshot
} from './contentRefreshState'
import { waitForDesktopBackend } from './backendStartupGate.js'
import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../utils/localApiAuth.js'
import {
  aiCallTypeLabel,
  cacheHitLabel,
  errorCategoryLabel,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatEstimatedCost,
  formatSeconds,
  formatTokenCount,
  markdownSyncLabel,
  renderMarkdown,
  stripReportMarkdownHeader,
  retryScopeLabel,
  roundedProgress,
  sanitizeHtml,
  sourceProviderLabel,
  stripMarkdownMetadata,
  statusLabel,
  statusTagType,
  textSourceKindLabel,
  textSourceProviderLabel
} from '../utils/viewFormatters'
import { sourceProviderFromUrl } from '../utils/taskSource.js'
import { extractReportSourceStats } from '../utils/reportSourceStats.js'
import {
  clearReportLogHistory,
  isPersistableReportLog,
  loadReportLogHistory,
  markInterruptedReportLogs,
  persistReportLogHistory,
} from '../features/logs/processLogHistory.js'
import { useArticlePreviewController } from '../features/library/useArticlePreviewController.js'
import { useOpenClawController } from '../features/integrations/useOpenClawController.js'
import { useQaSessionController } from '../features/assistant/useQaSessionController.js'
import { useSelectedTextContext } from '../features/assistant/useSelectedTextContext.js'
import { useWorkspaceState } from '../features/workspace/useWorkspaceState.js'
import { useClipboardController } from '../features/integrations/useClipboardController.js'
import { useContentReadState } from '../features/library/useContentReadState.js'
import { useContentReadinessController } from '../features/library/useContentReadinessController.js'
import { useLibrarySearchController } from '../features/library/useLibrarySearchController.js'
import { useLibraryTrashController } from '../features/library/useLibraryTrashController.js'
import { useArticlePreparationController } from '../features/library/useArticlePreparationController.js'
import { useContentRecoveryController } from '../features/library/useContentRecoveryController.js'
import { useLibraryHistoryController } from '../features/library/useLibraryHistoryController.js'
import { useCookieStatusController } from '../features/integrations/useCookieStatusController.js'
import { useCompletionNotificationController } from '../features/notifications/useCompletionNotificationController.js'

export function useAppController() {
  const PROCESS_LOG_CLEARED_AT_KEY = 'knowledgehub.process-log-cleared-at.v1'
  const ASR_SETTINGS_KEY = 'video-knowledge.asr-settings.v1'
  const AI_SETTINGS_KEY = 'video-knowledge.ai-settings.v1'
  const ASSISTANT_SETTINGS_KEY = 'video-knowledge.assistant-settings.v1'
  const APPEARANCE_SETTINGS_KEY = 'video-knowledge.appearance-settings.v1'
  const themeOptions = appearanceThemes
  const {
    workspaceTabs,
    activeWorkspaceTabId,
    workspaceLayout,
    restoreWorkspaceState,
    handleWorkspaceResize
  } = useWorkspaceState()
  const {
    openclawRunning,
    openclawScanning,
    openclawConnectionItems,
    openclawStatusTone,
    openclawStatusText,
    startOpenClawStatusPolling,
    stopOpenClawStatusPolling,
    loadOpenClawStatus,
    startOpenClawGateway
  } = useOpenClawController()
  const {
    questionInput,
    qaHistory,
    qaHistoryLoading,
    qaHistoryLoadingMore,
    qaHistoryHasMore,
    qaHistoryError,
    askingQuestion,
    generatingAiSummary,
    generatingSummaryText,
    startingNewChat,
    lastQaSaved,
    ensureQaSession,
    isQaSessionActive,
    activateQaSession,
    detachQaSession,
    syncQaSessionIfActive,
    refreshQaSessionHistory,
    clearQaSession,
    resetActiveQaSession
  } = useQaSessionController()

  const activeView = ref('library')
  const aiCallsByContentId = reactive({})
  const dailyAiTokenUsage = ref({
    period_start: '',
    call_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 0,
    estimated_cost: 0,
    unreported_count: 0,
    by_type: [],
    by_model: [],
    image_call_count: 0,
    image_count: 0,
    image_estimated_cost: 0,
    by_image_model: []
  })
  const openClawTokenUsage = ref({
    available: false,
    reason: '',
    session_count: 0,
    model_response_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    total_tokens: 0,
    estimated_cost_usd: 0,
    sessions: []
  })
  let aiTokenSummaryTimer = null
  let aiTokenSummaryLoading = false
  const contentAnalysisTemplates = ref([])
  let inputParseTimer = null
  let inputParseRequestId = 0
  const openSections = ref(['source', 'timings'])
  const shareText = ref('')
  const parsedUrl = ref(null)
  const running = ref(false)
  const cancelling = ref(false)
  const activeStep = ref(0)
  const currentStep = ref(null)
  const restoredReportLogs = loadReportLogHistory()
  const reconciledReportLogs = markInterruptedReportLogs(restoredReportLogs)
  if (reconciledReportLogs.length !== restoredReportLogs.length) {
    persistReportLogHistory(reconciledReportLogs)
  }
  const logs = ref(reconciledReportLogs)
  const logContainer = ref(null)
  const backendLogCount = ref(0)
  const logClearedAt = ref(Number(localStorage.getItem(PROCESS_LOG_CLEARED_AT_KEY) || 0))
  const pollTimer = ref(null)
  let taskEventSource = null
  let taskEventSourceTaskId = ''
  const taskStatus = ref('idle')
  const taskCancelRequested = ref(false)
  const selectedModel = ref('small')
  const availableModels = ref(['tiny', 'base', 'small'])
  const selectedAsrBackend = ref('auto')
  const availableAsrBackends = ref(['auto'])
  const miniprogramForumCaptureEnabled = ref(false)
  const asrModelStrategy = ref('manual')
  const asrShortVideoModel = ref('base')
  const asrLongVideoModel = ref('small')
  const asrBeamSize = ref(1)
  const asrVadFilter = ref(true)
  const asrFallbackEnabled = ref(false)
  // The global selection is used for ingestion and all background work.
  // The reading-side assistant starts from it but may be changed temporarily
  // without unexpectedly making later batch jobs use a more expensive model.
  const selectedAiModel = ref('deepseek-v4-flash:enabled')
  const assistantAiModel = ref(selectedAiModel.value)
  const availableAiModels = ref([
    { value: 'deepseek-v4-flash:enabled', label: 'deepseek-v4-flash' },
    { value: 'deepseek-v4-pro:enabled', label: 'deepseek-v4-pro' }
  ])
  const useCache = ref(true)
  const autoDownloadBilibiliVideo = ref(false)
  const douyinVideoQuality = ref('standard')
  const libraryFolders = ref([])
  // Archive rows are intentionally opt-in. They are merged into the current
  // tree only after a user expands a folder or completes a history sync.
  const libraryFolderHistoryStates = ref({})
  const libraryFolderRevealIds = ref([])
  const contentItems = ref([])
  const allContentItems = ref([])
  // The global startup gate only needs the folder tree and first page.  Keep
  // the slower historical pagination observable inside the sidebar instead.
  const contentPagesLoading = ref(false)
  const contentPageLoadStatus = reactive({
    state: 'idle',
    loaded: 0,
    total: 0,
  })
  let contentPageLoadVersion = 0
  let contentPageApiAvailable = null
  let contentRecentAfter = null
  let contentStartupRetryTimer = null
  let contentStartupRetryCount = 0
  // The workbench may render before Electron has finished starting Python.
  // Keep one explicit gate for the first usable library page so status-bound
  // controls cannot race their startup hydration.
  const startupPhase = ref('connecting')
  const startupBlocking = computed(() => startupPhase.value !== 'ready')
  const startupCanRetry = computed(() => startupPhase.value === 'retrying')
  const startupStatus = computed(() => {
    if (startupPhase.value === 'library') {
      return {
        title: '正在读取资料库',
        detail: '正在整理文件树，完成后即可开始操作。'
      }
    }
    if (startupPhase.value === 'workspace') {
      return {
        title: '正在恢复工作台',
        detail: '正在打开上次查看的资料。'
      }
    }
    if (startupPhase.value === 'retrying') {
      return {
        title: '资料库暂未响应',
        detail: '正在自动重新连接；也可以立即再试一次。'
      }
    }
    return {
      title: '正在连接本机服务',
      detail: '资料库与后台任务正在准备中。'
    }
  })
  const selectedContentItem = ref(null)
  const {
    loadCompletionNotifications,
    openCompletionNotification,
    startCompletionNotificationPolling,
    stopCompletionNotificationPolling,
  } = useCompletionNotificationController({
    allContentItems,
    getContentItemDetail,
    openContentTab,
    activeView,
    ribbonItems,
  })
  const {
    cookieConfigured,
    cookieState,
    cookieStatusText,
    cookieStatusDetail,
    cookieChecking,
    bilibiliCookieConfigured,
    bilibiliCookieState,
    bilibiliCookieStatusText,
    loadCookieStatus,
    loadBilibiliCookieStatus,
    scheduleDeferredCookieProbe,
    cancelDeferredCookieProbe,
    startCookieStatusPolling,
    stopCookieStatusPolling,
  } = useCookieStatusController({ notify: ElNotification })
  const {
    snapshotLibraryState,
    restoreLibraryState,
    resetLibraryHistory,
    recordLibraryHistory,
    discardLibraryHistoryForNodes,
    handleLibraryHistoryShortcut,
  } = useLibraryHistoryController({
    libraryFolders,
    allContentItems,
    contentItems,
    selectedContentItem,
    workspaceTabs,
    activeWorkspaceTabId,
    updateLocalContentItem,
    loadContentItems,
    notify: ElMessage,
  })

  const {
    libraryTrashEntries,
    loadingLibraryTrash,
    loadLibraryTrash,
    restoreLibraryTrashEntry,
    permanentlyDeleteLibraryTrashEntry,
    emptyLibraryTrash,
    showTrashUndoMessage,
  } = useLibraryTrashController({
    loadContentItems,
    loadLibraryFolders,
    revealContentItems,
    expandLibraryFolders,
    resetLibraryHistory,
  })
  const {
    articlePreviews,
    disposeArticlePreviews,
    loadArticlePreview,
    resetArticlePreview,
    updatePendingArticlePreviewReadiness,
  } = useArticlePreviewController({
    refreshContentTextReadiness: (contentItemId) => refreshContentTextReadiness(contentItemId),
  })
  const {
    articlePreparationStatus,
    currentArticleOcrStatus,
    prioritizingArticleOcr,
    loadCurrentArticleOcrStatus,
    prioritizeCurrentArticleOcr,
    startArticlePreparationStatusPolling,
    stopArticlePreparationStatusPolling,
  } = useArticlePreparationController({
    currentContent: () => activeWorkspaceContent.value || selectedContentItem.value,
    notifyError: (message) => ElMessage.error(typeof message === 'string' ? message : 'OCR 优先解析失败'),
  })
  const {
    getContentItemDetail,
    mergeContentTextReadiness,
    refreshContentTextReadiness,
  } = useContentReadinessController({
    allContentItems,
    selectedContentItem,
    applyContentFilter,
  })
  const {
    retryingContentId,
    retryContentSourceText,
    retryContentProcessing,
    reprocessLocalSource,
    retranscribeContentVideo,
    fetchExternalSubtitleForContent,
    refreshContentSourceContext,
    saveVideoDownloadSettings,
    redownloadContentVideo,
  } = useContentRecoveryController({
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    mergeContentTextReadiness,
    resetArticlePreview,
    loadArticlePreview,
    refreshContentTextReadiness,
    applyTaskData,
    registerBatchTask: registerContentRecoveryBatchTask,
    loadContentItems,
    pollTask,
    pollBatchTasks,
    getContentItemDetail,
    notify: ElMessage,
  })
  const loadingContent = ref(false)
  const updatingContentId = ref(null)
  const showMarkdownDialog = ref(false)
  const currentMarkdownItem = ref(null)
  const loadingMarkdown = ref(false)
  const savingMarkdown = ref(false)
  const syncingMarkdown = ref(false)
  const exportingConversationMarkdown = ref(false)
  const promptTaskType = ref('summary')
  const promptTemplates = ref([])
  const selectedPromptTemplateId = ref('')
  const qaShortcutTemplates = ref([])
  const loadingPrompts = ref(false)
  const savingPromptTemplate = ref(false)
  const activatingPromptTemplate = ref(false)
  const creatingPromptTemplate = ref(false)
  const creatingPromptFolderId = ref(null)
  const promptEditorName = ref('')
  const promptEditorText = ref('')
  const inboxItems = ref([])
  const loadingInbox = ref(false)
  const processingInboxIds = ref(new Set())
  const batchTasks = ref([])
  const batchTaskIds = ref([])
  const batchTaskNames = ref({})
  const batchPollTimer = ref(null)
  const taskQueueTimer = ref(null)
  const taskQueuePollingIntervalMs = ref(2000)
  const taskPollFailureCount = ref(0)
  let taskQueueSyncing = false
  const taskQueueSnapshots = new Map()
  const progressiveTaskSnapshots = new Map()
  const progressiveTaskHydratingIds = new Set()
  const backendLogCountsByTaskId = new Map()
  let taskQueueInitialized = false
  let taskQueueUpdatedAfter = logClearedAt.value
    ? new Date(logClearedAt.value).toISOString()
    : ''
  const loadingBatchTaskDetailIds = new Set()
  const articleSnapshotPreviewedTaskIds = new Set()
  const mediaSnapshotPreviewedTaskIds = new Set()
  const transcriptSnapshotPreviewedTaskIds = new Set()
  const autoQaShortcutRecognition = ref(true)
  const {
    viewedContentIds,
    explicitlyUnreadContentIds,
    contentViewedBefore,
    reconcileContentViewState,
    scheduleContentViewed,
    setContentViewedState
  } = useContentReadState({
    isCurrentContent: (contentItemId) => String(selectedContentItem.value?.id || '') === contentItemId
  })
  const obsidianVaultPath = ref('')
  const markdownExportPath = ref('')
  const obsidianAutoWrite = ref(false)
  const cookieInput = ref('')
  const savingCookie = ref(false)
  const bilibiliCookieInput = ref('')
  const savingBilibiliCookie = ref(false)
  const platformAuthConnecting = ref('')
  const platformAuthAvailable = Boolean(window.knowledgeHubDesktop?.connectPlatformAuth)
  const showSettings = ref(false)
  const selectedTheme = ref('paper')
  const markdownState = reactive({
    content_item_id: null,
    markdown_draft_path: null,
    obsidian_path: null,
    markdown: '',
    markdown_size_bytes: 0,
    sync_status: 'unknown',
    conflict: false,
    last_synced_at: null
  })

  const result = reactive({
    task_id: null,
    content_item_id: null,
    url: null,
    platform: null,
    video_path: null,
    transcript: null,
    summary: null,
    display_title: null,
    source_title: null,
    obsidian_path: null,
    markdown_draft_path: null,
    whisper_model: null,
    asr_backend: null,
    text_source: null,
    ai_calls: [],
    error: null,
    error_info: null,
    persistence_error: null,
    cache_hits: [],
    logs: [],
    timings: {},
    progress: {},
    overall_progress: 0,
    download_transfer: null
  })

  const renderedSummary = computed(() => {
    return renderMarkdown(result.summary)
  })

  const selectedThemeOption = computed(() => {
    return themeOptions.find((item) => item.value === selectedTheme.value) || themeOptions[0]
  })

  const selectedMarkdownPreview = computed(() => {
    if (!selectedContentItem.value || !markdownState.markdown) return ''
    const isReport = isGeneratedReportDocument(selectedContentItem.value)
    const isForumCapture = isForumCaptureDocument(selectedContentItem.value)
    const isExternalMarkdown = isExternalMarkdownDocument(selectedContentItem.value)
    // A report body is a center document.  Ordinary source documents strip
    // assistant sections; both document kinds always strip Q&A from the
    // center reader.
    const markdown = isReport
      ? reportMarkdownForCenter(markdownState.markdown)
      : isExternalMarkdown
        ? sourceMarkdownForCenter(markdownState.markdown)
        : stripAssistantMarkdown(markdownState.markdown)
    return renderMarkdown(
      isReport
        ? stripReportMarkdownHeader(markdown)
        : isForumCapture
          ? stripForumCaptureMarkdownHeader(markdown)
          : markdown
    )
  })

  const selectedMarkdownSizeBytes = computed(() => {
    const persistedSize = Number(markdownState.markdown_size_bytes || 0)
    if (persistedSize > 0) return persistedSize
    const markdown = String(markdownState.markdown || '')
    return markdown ? new TextEncoder().encode(markdown).length : 0
  })

  const selectedReportSourceStats = computed(() => {
    if (!selectedContentItem.value || !markdownState.markdown) return { analyzed: 0, referenced: 0 }
    const isReport = isGeneratedReportDocument(selectedContentItem.value)
    return isReport
      ? extractReportSourceStats(markdownState.markdown)
      : { analyzed: 0, referenced: 0 }
  })

  const selectedMarkdownSourceText = computed(() => {
    if (!selectedContentItem.value || !markdownState.markdown) return ''
    if (isForumCaptureDocument(selectedContentItem.value)) {
      return stripAssistantMarkdown(markdownState.markdown)
    }
    if (isExternalMarkdownDocument(selectedContentItem.value)) {
      return sourceMarkdownForCenter(markdownState.markdown)
    }
    return extractSourceTextFromMarkdown(markdownState.markdown)
  })

  const mediaPreviewUrl = computed(() => {
    if (!result.video_path) return ''
    return localApiRequestUrl(`${API}/media?path=${encodeURIComponent(result.video_path)}`)
  })

  const sidebarContentItems = computed(() => {
    return contentItems.value
  })

  const {
    searchQuery,
    librarySearchScope,
    searchResults,
    searchResultContentItems,
    searchContent,
    disposeLibrarySearchController,
  } = useLibrarySearchController({ recordTelemetry })

  const sidebarTreeItems = computed(() => {
    return searchQuery.value.trim() ? searchResultContentItems.value : sidebarContentItems.value
  })

  const activeWorkspaceTab = computed(() => {
    return workspaceTabs.value.find((tab) => tab.id === activeWorkspaceTabId.value) || null
  })

  const activeWorkspaceContent = computed(() => {
    const tab = activeWorkspaceTab.value
    if (!tab?.content_item_id) return null
    const listed = allContentItems.value.find((item) => item.id === tab.content_item_id)
    const selected = selectedContentItem.value?.id === tab.content_item_id ? selectedContentItem.value : null
    // A paginated library row deliberately carries a lightweight pending
    // readiness placeholder. Keep the already-hydrated open item authoritative
    // until a later full detail response replaces it.
    if (selected?.text_readiness?.status !== 'pending' && listed?.text_readiness?.status === 'pending') {
      return selected
    }
    return listed || selected
  })

  const activeWorkspaceResult = computed(() => {
    const tab = activeWorkspaceTab.value
    return tab?.content_item_id ? resultForTab(tab.id) : null
  })

  const activeContentAiCalls = computed(() => {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id
    if (contentItemId && Array.isArray(aiCallsByContentId[contentItemId])) {
      return aiCallsByContentId[contentItemId]
    }
    return activeWorkspaceResult.value?.ai_calls || result.ai_calls || []
  })

  const activeWorkspaceStatus = computed(() => {
    return activeWorkspaceContent.value?.status || activeWorkspaceResult.value?.status || activeWorkspaceTab.value?.status || 'inbox'
  })

  const activeWorkspaceMediaUrl = computed(() => {
    const videoPath = activeWorkspaceResult.value?.video_path || activeWorkspaceContent.value?.video_path
    if (!videoPath) return ''
    return localApiRequestUrl(`${API}/media?path=${encodeURIComponent(videoPath)}`)
  })

  const activeWorkspaceTranscript = computed(() => {
    if (activeWorkspaceResult.value?.transcript) return activeWorkspaceResult.value.transcript
    if (['article', 'forum_post', 'forum_capture'].includes(activeWorkspaceContent.value?.content_type) && selectedContentItem.value?.id === activeWorkspaceContent.value.id) {
      return selectedMarkdownSourceText.value
    }
    if (!activeWorkspaceContent.value && ['article', 'forum_post', 'forum_capture'].includes(selectedContentItem.value?.content_type)) {
      return selectedMarkdownSourceText.value
    }
    return ''
  })

  const {
    activeSelectedTextContext,
    clearSelectedTextContext,
    removeSelectedTextContextToken,
    setSelectedTextContext,
  } = useSelectedTextContext({
    questionInput,
    getActiveContent: () => activeWorkspaceContent.value,
    getFallbackContentItemId: () => result.content_item_id,
    getFallbackContentTitle: () => result.source_title,
  })

  function workspaceTabById(tabId) {
    return workspaceTabs.value.find((tab) => tab.id === tabId) || null
  }

  function contentForTab(tabId) {
    const tab = workspaceTabById(tabId)
    const contentItemId = tab?.content_item_id || (String(tabId || '').startsWith('content:') ? String(tabId).slice('content:'.length) : '')
    if (!contentItemId) return null
    // The library list intentionally omits runtime-only fields such as the
    // retained original path. For the open item, always prefer its hydrated
    // detail so PDF/image originals can render immediately.
    if (selectedContentItem.value?.id === contentItemId) return selectedContentItem.value
    return allContentItems.value.find((item) => item.id === contentItemId) || null
  }

  function resultForTab(tabId) {
    const tab = workspaceTabById(tabId)
    const contentItemId = tab?.content_item_id || (String(tabId || '').startsWith('content:') ? String(tabId).slice('content:'.length) : '')
    if (!contentItemId) return null
    const matchingTasks = batchTasks.value.filter((candidate) => candidate.content_item_id === contentItemId)
    // The process dock can hold an older completed snapshot and a newer live
    // retry/reprocessing task for the same item. The old global result used to
    // win here, leaving the right assistant idle while the status bar (which
    // reads the task queue) correctly showed “AI 总结”. The live task is the
    // only authoritative source while it exists.
    const activeTask = matchingTasks.find((candidate) => isActiveTask(candidate))
    if (activeTask) return activeTask
    if (result.content_item_id === contentItemId) return result
    return matchingTasks[0] || null
  }

  function statusForTab(tabId) {
    return contentForTab(tabId)?.status || resultForTab(tabId)?.status || workspaceTabById(tabId)?.status || 'inbox'
  }

  function mediaUrlForTab(tabId) {
    const tabResult = resultForTab(tabId)
    const tabContent = contentForTab(tabId)
    const videoPath = tabResult?.video_path || tabContent?.video_path
    if (!videoPath) return ''
    return localApiRequestUrl(`${API}/media?path=${encodeURIComponent(videoPath)}`)
  }

  function originalMediaUrlForTab(tabId) {
    const content = contentForTab(tabId)
    const originalPath = content?.original_file_path
    if (!originalPath) return ''
    return localApiRequestUrl(`${API}/media?path=${encodeURIComponent(originalPath)}`)
  }

  function transcriptForTab(tabId) {
    const tabResult = resultForTab(tabId)
    if (tabResult?.transcript) return tabResult.transcript
    const tabContent = contentForTab(tabId)
    if (tabContent?.id && selectedContentItem.value?.id === tabContent.id) {
      return selectedMarkdownSourceText.value
    }
    return ''
  }

  function articlePreviewForTab(tabId) {
    const content = contentForTab(tabId)
    return content?.id ? articlePreviews[content.id] || null : null
  }

  const currentInsightHtml = computed(() => {
    // Pipeline text is rendered in the same flowing bubble as a manual
    // summary while it is still arriving. Avoid showing a second, static
    // copy above it before the pipeline finishes.
    if (isPipelineSummaryGenerating.value) return ''
    if (activeWorkspaceTab.value) {
      const summary = currentSummaryText.value
      return summary ? renderMarkdown(summary) : ''
    }
    if (result.summary) return renderedSummary.value
    return ''
  })

  const currentInsightTitle = computed(() => String(
    activeWorkspaceResult.value?.display_title
      || result.display_title
      || activeWorkspaceContent.value?.title
      || activeWorkspaceTab.value?.title
      || selectedContentItem.value?.title
      || result.source_title
      || ''
  ).replace(/\s+/gu, ' ').trim())

  // A background pipeline owns its own AI request.  Mirror that real task
  // state into the assistant instead of pretending the sidebar is idle until
  // the final summary is written.  This is intentionally separate from the
  // manual “generate summary” action, which still streams through its own
  // per-content QA session.
  const isPipelineSummaryGenerating = computed(() => {
    const task = activeWorkspaceResult.value
    if (!task || !['queued', 'running'].includes(task.status)) return false
    const progress = task.progress || {}
    const summaryProgress = Number(progress.summarize || 0)
    if (summaryProgress >= 100) return false
    return task.step === 'summarize' || summaryProgress > 0
  })

  const pipelineGeneratingSummaryText = computed(() => (
    isPipelineSummaryGenerating.value
      ? String(activeWorkspaceResult.value?.summary || '')
      : ''
  ))

  const currentQaEnabled = computed(() => {
    const hasExistingContext = Boolean(
      activeWorkspaceTranscript.value
      || activeWorkspaceResult.value?.transcript
      || result.transcript
      || currentSummaryText.value
    )
    const readiness = activeWorkspaceContent.value?.text_readiness
    if (readiness && readiness.can_ask_ai === false) {
      return hasExistingContext
    }
    return Boolean(
      activeWorkspaceContent.value?.id
      || result.content_item_id
      || hasExistingContext
    )
  })

  const currentQaHint = computed(() => {
    const readiness = activeWorkspaceContent.value?.text_readiness
    if (activeWorkspaceContent.value && readiness?.can_ask_ai === false) {
      return readiness.detail || readiness.label || '当前内容暂时没有可供追问的文本'
    }
    return currentQaEnabled.value ? '追问当前内容…' : '选择内容后追问'
  })

  const activeRegenerableContent = computed(() => {
    const item = activeWorkspaceContent.value || selectedContentItem.value
    return item?.id ? item : null
  })

  const canGenerateAiSummary = computed(() => {
    return Boolean(
      activeRegenerableContent.value?.id
      && currentQaEnabled.value
      && !isGeneratedReportDocument(activeRegenerableContent.value)
      && !String(currentSummaryText.value || '').trim()
    )
  })

  const currentObsidianPath = computed(() => {
    if (activeWorkspaceTab.value) return markdownState.obsidian_path || result.obsidian_path || ''
    return result.obsidian_path || markdownState.obsidian_path || ''
  })

  const currentSummaryText = computed(() => {
    if (activeWorkspaceTab.value) {
      if (isGeneratedReportDocument(activeWorkspaceContent.value)) return ''
      return assistantSummaryFromMarkdown(markdownState.markdown) || activeWorkspaceResult.value?.summary || ''
    }
    if (isGeneratedReportDocument(selectedContentItem.value)) return ''
    return result.summary || assistantSummaryFromMarkdown(markdownState.markdown)
  })

  const contentStatusCounts = computed(() => {
    const counts = { all: allContentItems.value.length }
    for (const item of allContentItems.value) {
      counts[item.status] = (counts[item.status] || 0) + 1
    }
    return counts
  })

  const timingRows = computed(() => {
    const timings = result.timings || {}
    return timingOrder
      .filter((key) => typeof timings[key] === 'number')
      .map((key) => ({
        name: stepLabel(key),
        duration: formatSeconds(timings[key])
      }))
  })

  const textSourceRows = computed(() => {
    const source = result.text_source
    if (!source) return []
    const rows = [
      { label: '类型', value: textSourceKindLabel(source.kind) },
      { label: '来源', value: textSourceProviderLabel(source.source) }
    ]
    if (source.cached) rows.push({ label: '缓存', value: '已复用' })
    if (source.detail) rows.push({ label: '细节', value: source.detail })
    if (source.fallback_reason) rows.push({ label: '回退原因', value: source.fallback_reason })
    return rows
  })

  const aiCallRows = computed(() => {
    return (result.ai_calls || []).map((call) => ({
      type: aiCallTypeLabel(call.call_type),
      tokens: formatTokenCount(call.total_tokens),
      duration: formatSeconds(call.elapsed_seconds),
      cost: formatEstimatedCost(call.estimated_cost)
    }))
  })

  const errorInfoRows = computed(() => {
    const info = result.error_info
    if (!info) return []
    return [
      { label: '分类', value: errorCategoryLabel(info.category) },
      { label: '阶段', value: stepLabel(info.stage) },
      { label: '建议', value: info.retryable ? retryScopeLabel(info.retry_scope) : '不建议直接重试' },
      { label: '原因', value: info.message || result.error || '未知错误' }
    ]
  })

  const totalElapsed = computed(() => {
    const value = result.timings?.total
    return typeof value === 'number' ? value : null
  })

  const hasTaskProgress = computed(() => {
    return ['queued', 'running', 'paused'].includes(taskStatus.value)
  })

  const visibleBatchTasks = computed(() => {
    return batchTasks.value.filter((task) => shouldDisplayTask(task))
  })

  const activeBatchCount = computed(() => {
    return visibleBatchTasks.value.filter((task) => ['queued', 'running'].includes(task.status)).length
  })

  const statusbarProgress = computed(() => {
    const activeTasks = batchTasks.value.filter((task) => isActiveTask(task))
    const activeTask = activeTasks.find((task) => task.status === 'running') || activeTasks[0]
    if (activeTask) {
      const transfer = activeTask.step === 'download' ? activeTask.download_transfer : null
      return {
        visible: true,
        label: statusbarStageLabel(activeTask),
        detail: statusbarTransferDetail(transfer, statusbarTaskContext(activeTask)),
        // A percentage is shown only when the provider supplied a real media
        // denominator (or yt-dlp reported an actual stream percentage).
        percent: transfer?.percent === null || transfer?.percent === undefined
          ? null
          : roundedProgress(transfer.percent),
        transfer,
      }
    }

    const transfer = currentStep.value === 'download' ? result.download_transfer : null
    return {
      // A single-task poll can finish before its final log reaches the dock.
      // Tie this fallback to the live runner as well, so a terminal log never
      // leaves a stale download/transcription progress bar in the status bar.
      visible: running.value && hasTaskProgress.value,
      label: statusbarStageLabel(),
      detail: statusbarTransferDetail(transfer, statusbarTaskContext()),
      percent: transfer?.percent === null || transfer?.percent === undefined
        ? null
        : roundedProgress(transfer.percent),
      transfer,
    }
  })

  const processLogEntries = computed(() => {
    const entries = []
    const clearedAt = logClearedAt.value

    for (const item of logs.value) {
      const timestamp = item.timestamp || 0
      if (timestamp >= clearedAt) {
        entries.push({
          ...item,
          timestamp,
          task_id: item.task_id || result.task_id || '',
          task_name: item.task_name || statusbarProgress.value.detail || result.url || ''
        })
      }
    }

    for (const task of batchTasks.value) {
      const taskName = batchTaskName(task)
      const taskLogs = Array.isArray(task.logs) ? task.logs : []
      const aiCalls = Array.isArray(task.ai_calls) ? task.ai_calls : []
      const reportedCalls = aiCalls.filter((call) => (
        call?.prompt_tokens !== null
        && call?.prompt_tokens !== undefined
        && call?.completion_tokens !== null
        && call?.completion_tokens !== undefined
        && Number.isFinite(Number(call.prompt_tokens))
        && Number.isFinite(Number(call.completion_tokens))
      ))
      const promptTokens = reportedCalls.reduce((sum, call) => sum + Number(call.prompt_tokens), 0)
      const completionTokens = reportedCalls.reduce((sum, call) => sum + Number(call.completion_tokens), 0)
      for (const [index, item] of taskLogs.entries()) {
        const timestamp = Date.parse(item.created_at || '') || Date.parse(task.updated_at || task.created_at || '') || 0
        if (clearedAt && timestamp <= clearedAt) continue
        const isLatestLog = index === taskLogs.length - 1
        entries.push({
          time: item.time || formatProcessLogTime(item.created_at || task.updated_at || task.created_at),
          msg: item.message || String(item),
          type: item.level || logTypeFromMessage(item.message || String(item)),
          step: item.step || task.step || null,
          elapsed_seconds: item.elapsed_seconds ?? null,
          timestamp,
          task_id: task.task_id,
          task_name: taskName,
          task_status: task.status,
          task_progress: task.overall_progress,
          prompt_tokens: isLatestLog && reportedCalls.length ? promptTokens : null,
          completion_tokens: isLatestLog && reportedCalls.length ? completionTokens : null,
          total_tokens: isLatestLog && reportedCalls.length ? promptTokens + completionTokens : null,
        })
      }
      if (task.persistence_error) {
        const timestamp = Date.parse(task.updated_at || task.created_at || '') || Date.now()
        if (!clearedAt || timestamp > clearedAt) {
          entries.push({
            time: formatProcessLogTime(task.updated_at || task.created_at),
            msg: `本地保存失败：${task.persistence_error}`,
            type: 'error',
            step: task.step || null,
            timestamp,
            task_id: task.task_id,
            task_name: taskName,
            task_status: task.status,
            task_progress: task.overall_progress,
          })
        }
      }
    }

    const deduplicated = new Map()
    for (const item of entries.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))) {
      const key = `${item.task_id}|${item.timestamp || 0}|${item.step || ''}|${item.msg}|${item.elapsed_seconds ?? ''}`
      deduplicated.set(key, item)
    }
    return [...deduplicated.values()].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))
  })

  const modelProfileOptions = computed(() => {
    return preferredModelOrder
      .filter((model) => availableModels.value.includes(model))
      .map((model) => modelProfiles.find((profile) => profile.model === model))
      .filter(Boolean)
  })

  const selectedModelProfile = computed(() => {
    return modelProfiles.find((profile) => profile.model === selectedModel.value) || modelProfiles[2]
  })

  const activePromptTemplate = computed(() => {
    return promptTemplates.value.find((template) => template.id === selectedPromptTemplateId.value)
      || promptTemplates.value.find((template) => template.is_active)
      || promptTemplates.value[0]
      || null
  })

  const currentStageLabel = computed(() => {
    if (taskStatus.value === 'idle') {
      return parsedUrl.value ? '准备处理' : '等待链接'
    }
    if (taskStatus.value === 'queued') return '排队中'
    if (taskStatus.value === 'paused') return '已暂停'
    if (taskStatus.value === 'succeeded') return '处理完成'
    if (taskStatus.value === 'failed') return '处理失败'
    if (taskStatus.value === 'cancelled') return '任务已取消'
    return currentStep.value ? `${stepLabel(currentStep.value)}中` : '处理中'
  })

  function addLog(msg, type = 'info', step = null, elapsed_seconds = null, context = {}) {
    const contextTimestamp = Number(context.timestamp)
    const timestamp = Number.isFinite(contextTimestamp) ? contextTimestamp : Date.now()
    const entry = {
      ...context,
      time: context.time || new Date(timestamp).toLocaleTimeString(),
      msg,
      type,
      step,
      elapsed_seconds,
      timestamp
    }
    logs.value.push(entry)
    if (isPersistableReportLog(entry)) persistReportLogHistory(logs.value)
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }

  function clearLogs() {
    logs.value = []
    backendLogCountsByTaskId.clear()
    clearReportLogHistory()
    logClearedAt.value = Date.now()
    localStorage.setItem(PROCESS_LOG_CLEARED_AT_KEY, String(logClearedAt.value))
    taskQueueUpdatedAfter = new Date(logClearedAt.value).toISOString()
    batchTasks.value = batchTasks.value.filter((task) => isActiveTask(task))
    batchTaskIds.value = batchTasks.value.map((task) => task.task_id)
    backendLogCount.value = 0
  }

  function isActiveTask(task) {
    return ['queued', 'running', 'paused'].includes(task?.status)
  }

  function statusbarStageLabel(task = null) {
    const status = task?.status || taskStatus.value
    if (status === 'queued') return '等待中'
    if (status === 'paused') return '已暂停'

    const step = task?.step || currentStep.value
    const platform = task
      ? (task.platform || task.source_provider || sourceProviderFromUrl(task.source_url || task.url))
      : (result.platform || parsedUrl.value?.platform)
    if (step === 'info' && platform === 'wechat') return '读取文章'
    const labels = {
      parse: '解析链接',
      info: '读取信息',
      download: '下载视频',
      extract_audio: '提取音频',
      transcribe: '转写音频',
      summarize: 'AI 总结',
      save: '保存内容'
    }
    return labels[step] || '处理中'
  }

  function statusbarTaskContext(task = null) {
    const title = task
      ? (batchTaskNames.value[task.task_id] || task.display_title || task.source_title)
      : result.source_title
    if (title && !/^https?:\/\//i.test(title)) return title

    const platform = task
      ? (task.platform || task.source_provider || sourceProviderFromUrl(task.source_url || task.url))
      : (result.platform || parsedUrl.value?.platform)
    if (platform) return `${sourceProviderLabel(platform)}内容`
    if (task?.local_video_path || result.video_path) return '本地视频'
    if (task?.local_subtitle_path) return '字幕文件'
    return '当前内容'
  }

  function statusbarTransferDetail(transfer, fallback) {
    if (!transfer) return fallback
    const parts = [transfer.detail].filter(Boolean)
    const received = Number(transfer.received_bytes)
    const total = Number(transfer.total_bytes)
    const speed = Number(transfer.bytes_per_second)
    if (Number.isFinite(received) && received >= 0) {
      parts.push(Number.isFinite(total) && total > 0
        ? `${formatBytes(received)} / ${formatBytes(total)}`
        : `${formatBytes(received)} 已接收`)
    }
    if (Number.isFinite(speed) && speed > 0) parts.push(`${formatBytes(speed)}/s`)
    return parts.join(' · ') || fallback
  }

  function shouldDisplayTask(task) {
    if (isActiveTask(task)) return true
    const clearedAt = logClearedAt.value
    if (!clearedAt) return true
    const createdAt = Date.parse(task?.created_at || '')
    return Number.isFinite(createdAt) && createdAt > clearedAt
  }

  function logTypeFromMessage(message) {
    return String(message || '').includes('失败') || String(message || '').includes('错误') || String(message || '').includes('ERROR') ? 'error'
      : String(message || '').includes('完成') || String(message || '').includes('成功') ? 'success'
      : String(message || '').includes('WARNING') || String(message || '').includes('警告') ? 'warn'
      : 'info'
  }

  function formatProcessLogTime(value) {
    const timestamp = Date.parse(value || '')
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleTimeString() : '—'
  }

  function addBackendLogs(logList, task = {}) {
    if (!Array.isArray(logList)) return
    const taskId = String(task.task_id || result.task_id || '__current__')
    const previousCount = backendLogCountsByTaskId.get(taskId) || 0
    const newItems = logList.slice(previousCount)
    backendLogCountsByTaskId.set(taskId, logList.length)
    if (taskId === String(result.task_id || '__current__')) {
      backendLogCount.value = logList.length
    }
    for (const item of newItems) {
      const itemTimestamp = typeof item === 'object' ? Date.parse(item.created_at || '') : NaN
      if (logClearedAt.value && Number.isFinite(itemTimestamp) && itemTimestamp <= logClearedAt.value) continue
      if (typeof item === 'string') {
        addLog(item, logTypeFromMessage(item))
        continue
      }

      addLog(item.message, item.level || 'info', item.step || null, item.elapsed_seconds ?? null, {
        timestamp: Date.parse(item.created_at || '') || undefined,
        task_id: task.task_id || result.task_id || '',
        task_name: task.display_title || task.source_title || '',
        task_status: task.status || taskStatus.value,
        task_progress: task.overall_progress ?? result.overall_progress ?? 0,
      })
    }
  }

  function progressStatus(status, stageKey = null, task = null) {
    if (status === 'succeeded') return 'success'
    if (status === 'failed') return 'exception'
    if (status === 'cancelled') return 'warning'
    if (status === 'paused') return 'warning'
    if (stageKey && task && stageProgress(stageKey, task) >= 100) return 'success'
    if (stageKey && !task && stageProgress(stageKey) >= 100) return 'success'
    return undefined
  }

  function stageProgress(stageKey, task = null) {
    const source = task?.progress || result.progress || {}
    return roundedProgress(source[stageKey])
  }

  function stepLabel(step) {
    return stepNames[step] || step
  }

  function modelLabel(model) {
    if (!model) return '默认'
    const profile = modelProfiles.find((item) => item.model === model)
    return profile ? profile.label : model
  }

  function promptTaskLabel(taskType) {
    const option = promptTaskOptions.find((item) => item.value === taskType)
    return option ? option.label : taskType
  }

  function contentStatusCount(status) {
    return contentStatusCounts.value[status] || 0
  }

  function openContentFromSidebar(item) {
    openContentTab(item)
  }

  function openSearchResult(item) {
    const content = allContentItems.value.find((current) => current.id === item.content_key)
    if (content) {
      openContentTab(content)
    }
  }

  async function openContentTab(item) {
    if (!item?.id) return
    const tabId = tabIdForContent(item.id)
    const existing = workspaceTabs.value.find((tab) => tab.id === tabId)
    if (existing) {
      existing.title = item.title || existing.title
      existing.source_provider = item.source_provider || existing.source_provider
      existing.status = item.status || existing.status
    } else {
      workspaceTabs.value.push(makeContentTab(item))
    }
    await activateWorkspaceTab(tabId)
  }

  async function activateWorkspaceTab(tabId) {
    activeWorkspaceTabId.value = tabId
    activeView.value = 'library'
    const tab = workspaceTabs.value.find((item) => item.id === tabId)
    let content = tab?.content_item_id
      ? allContentItems.value.find((item) => item.id === tab.content_item_id)
      : null
    if (!content && tab?.content_item_id) {
      content = await getContentItemDetail(tab.content_item_id)
    }
    if (content) {
      await selectContentItem(content)
    } else {
      selectedContentItem.value = null
      resetMarkdownState()
      detachQaSession()
    }
  }

  function removeWorkspaceTabState(tabId) {
    closeWorkspaceTabs([tabId])
  }

  function closeWorkspaceTabs(tabIds) {
    const closingIds = new Set(Array.isArray(tabIds) ? tabIds.filter(Boolean) : [])
    if (!closingIds.size) return
    const activeIndex = workspaceTabs.value.findIndex((tab) => tab.id === activeWorkspaceTabId.value)
    const activeTabClosed = closingIds.has(activeWorkspaceTabId.value)
    const remainingTabs = workspaceTabs.value.filter((tab) => !closingIds.has(tab.id))
    if (remainingTabs.length === workspaceTabs.value.length) return
    workspaceTabs.value = remainingTabs
    if (!activeTabClosed) return

    const nextTab = remainingTabs[Math.min(Math.max(activeIndex, 0), remainingTabs.length - 1)] || null
    if (nextTab) {
      activateWorkspaceTab(nextTab.id)
    } else {
      activeWorkspaceTabId.value = ''
      selectedContentItem.value = null
      resetMarkdownState()
      detachQaSession()
    }
  }

  function closeWorkspaceTab(tabId) {
    removeWorkspaceTabState(tabId)
  }

  async function revealWorkspaceTabLocation(tab) {
    const contentItemId = String(tab?.content_item_id || '').trim()
    if (!contentItemId) return
    await revealLibraryNodeLocation({ type: 'content', id: contentItemId })
  }

  async function deleteWorkspaceTabContent(tab) {
    const contentItemId = String(tab?.content_item_id || '').trim()
    if (!contentItemId) return
    const content = allContentItems.value.find((item) => String(item.id) === contentItemId)
      || await getContentItemDetail(contentItemId)
    if (!content) {
      ElMessage.error('找不到该文件，无法移入回收站')
      return
    }
    await deleteContentItem(content)
  }

  async function syncActiveWorkspaceTabSelection({ awaitPrimaryPreview = false } = {}) {
    const tab = activeWorkspaceTab.value
    if (!tab?.content_item_id) return
    let content = allContentItems.value.find((item) => item.id === tab.content_item_id)
    if (!content) content = await getContentItemDetail(tab.content_item_id)
    if (content) {
      tab.title = content.title || tab.title
      tab.source_provider = content.source_provider || tab.source_provider
      tab.status = content.status || tab.status
      await selectContentItem(content, { awaitPrimaryPreview })
    }
  }

  async function syncCompletedTaskContent(contentItemId) {
    if (!contentItemId) return
    // Replacing the whole recent library while a media task settles resets
    // the progressively disclosed tree and makes it look as though folders
    // are repeatedly collapsing.  The detail endpoint also updates the one
    // reactive entry used by the tree.
    const content = await getContentItemDetail(contentItemId)
    if (!content) return

    const tabId = tabIdForContent(content.id)
    const existing = workspaceTabs.value.find((tab) => tab.id === tabId)
    if (existing) {
      existing.title = content.title || existing.title
      existing.source_provider = content.source_provider || existing.source_provider
      existing.status = content.status || existing.status
    } else {
      workspaceTabs.value.push(makeContentTab(content))
    }
    await activateWorkspaceTab(tabId)
  }

  function syncTaskTabMetadata(content) {
    if (!content?.id) return
    const tabId = tabIdForContent(content.id)
    const tab = workspaceTabs.value.find((candidate) => candidate.id === tabId)
    if (!tab) return
    tab.title = content.title || tab.title
    tab.source_provider = content.source_provider || tab.source_provider
    tab.status = content.status || tab.status
  }

  async function syncVisibleProgressiveContent(task) {
    if (!task?.content_item_id) return null
    const content = await getContentItemDetail(task.content_item_id)
    if (!content) return null
    syncTaskTabMetadata(content)

    // Do not steal focus or open a new tab whenever a background task makes
    // progress. If the reader intentionally opened this item, however, keep
    // its hydrated record current and retry a previously unavailable article
    // preview as soon as the cache becomes readable.
    if (activeWorkspaceTab.value?.content_item_id === content.id) {
      selectedContentItem.value = content
      currentMarkdownItem.value = content
      updatePendingArticlePreviewReadiness(content)
      const preview = articlePreviews[content.id]
      const isReadableArticle = ['article', 'forum_post'].includes(content.content_type)
        && ['wechat', 'campus', 'rss', 'wechat_miniprogram', 'xiaohongshu'].includes(content.source_provider)
      if (isReadableArticle && (!preview || preview.error)) {
        void loadArticlePreview(content, { force: Boolean(preview?.error) })
      }
    }
    return content
  }

  async function hydrateProgressiveTask(task, previousSnapshot) {
    if (!shouldHydrateProgressiveTask(task, previousSnapshot)) return
    const taskId = String(task.task_id || '')
    if (!taskId || progressiveTaskHydratingIds.has(taskId)) return
    progressiveTaskHydratingIds.add(taskId)
    try {
      const previousParts = String(previousSnapshot || '').split('|')
      const transcriptBecameReady = !previousParts.includes('transcript-ready')
        && Number(task?.progress?.transcribe || 0) >= 100
      const contentChanged = !previousSnapshot || previousParts[0] !== String(task.content_item_id || '')
      // Summary growth does not alter the content row. Fetching it repeatedly
      // caused a full detail read to contend with media rendering and made the
      // active view feel frozen. Only hydrate the tree/source at durable
      // content and subtitle milestones; task detail is still refreshed below.
      const shouldSyncContent = contentChanged || transcriptBecameReady
      const [detailResult, hydratedContent] = await Promise.all([
        task.details_included === false
          ? axios.get(`${API}/tasks/${taskId}`, { timeout: 10000 }).then((response) => response.data).catch(() => null)
          : Promise.resolve(task),
        shouldSyncContent ? syncVisibleProgressiveContent(task) : Promise.resolve(true),
      ])
      // Do not acknowledge the milestone before the item enters the local
      // tree cache. A short backend/database race used to mark this as done
      // after a failed detail request, leaving a newly queued video absent
      // from “未读” until a later download milestone happened to change.
      if (!hydratedContent) return

      const resolvedTask = detailResult || task
      if (detailResult) {
        mergeBatchTasks([detailResult])
        addBackendLogs(detailResult.logs || [], detailResult)
        if (shouldSyncContent) await syncVisibleProgressiveContent(detailResult)
        if (result.content_item_id === detailResult.content_item_id) applyTaskData(detailResult)
      }
      progressiveTaskSnapshots.set(taskId, progressiveTaskSnapshot(resolvedTask))
    } finally {
      progressiveTaskHydratingIds.delete(taskId)
    }
  }

  async function revealWechatArticleSnapshot(task) {
    if (
      task?.platform !== 'wechat'
      || task?.text_source?.kind !== 'article'
      || !task?.transcript?.trim()
      || !task?.content_item_id
      || articleSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    // The article cache is persisted before the DeepSeek summary begins.
    // Hydrate only that entry so an active tree keeps its expansion state.
    await syncVisibleProgressiveContent(task)

    if (articleSnapshotPreviewedTaskIds.size >= 200) {
      articleSnapshotPreviewedTaskIds.clear()
    }
    articleSnapshotPreviewedTaskIds.add(task.task_id)
  }

  async function revealVideoSnapshot(task) {
    if (
      !task?.video_path
      || !task?.content_item_id
      || mediaSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    // The backend creates this item at the video-ready milestone. Hydrate
    // only it; a whole-library refresh here made the left tree rebuild while
    // FFmpeg was preparing the preview.
    const content = await syncVisibleProgressiveContent(task)
    if (!content) return

    if (mediaSnapshotPreviewedTaskIds.size >= 200) {
      mediaSnapshotPreviewedTaskIds.clear()
    }
    mediaSnapshotPreviewedTaskIds.add(task.task_id)
  }

  async function revealTranscriptSnapshot(task) {
    if (
      !task?.transcript?.trim()
      || !task?.content_item_id
      || transcriptSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    // Segment timings are written beside the transcript before this task
    // update is published. Hydrate only this item (rather than reload the
    // library) so the open video gains its timed subtitle panel immediately.
    const detail = await syncVisibleProgressiveContent(task)
    if (!detail) return
    if (transcriptSnapshotPreviewedTaskIds.size >= 200) {
      transcriptSnapshotPreviewedTaskIds.clear()
    }
    transcriptSnapshotPreviewedTaskIds.add(task.task_id)
  }

  // Audio and video share one predictable desktop baseline.  The runtime
  // resolves `auto` to the host-native implementation; no user preference or
  // stale localStorage value can change a new task's ASR configuration.
  const asrRequestOptions = () => ({ ...DESKTOP_ASR_POLICY })

  const aiRequestOptions = () => ({
    ai_model: selectedAiModel.value
  })

  const {
    clipboardWatching,
    clipboardScanning,
    clipboardStatus,
    clipboardStatusText,
    stopClipboardStatusPolling,
    toggleClipboardWatching,
    loadClipboardStatus
  } = useClipboardController({
    activeView,
    aiRequestOptions,
    asrRequestOptions,
    batchTaskIds,
    batchTaskNames,
    pollBatchTasks,
    recordTelemetry,
    useCache
  })

  const appearanceRequestOptions = () => ({ theme: selectedTheme.value })

  const persistAiSettings = () => {
    try {
      localStorage.setItem(AI_SETTINGS_KEY, JSON.stringify(aiRequestOptions()))
    } catch {
      // 本地存储失败不影响处理流程。
    }
  }

  const persistAssistantSettings = () => {
    try {
      localStorage.setItem(ASSISTANT_SETTINGS_KEY, JSON.stringify({
        auto_qa_shortcut_recognition: Boolean(autoQaShortcutRecognition.value)
      }))
    } catch {
      // 本地存储失败不影响追问功能。
    }
  }

  const applyTheme = () => {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.theme = selectedThemeOption.value.value
    delete document.documentElement.dataset.readingTheme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', selectedThemeOption.value.background)
  }

  const persistAppearanceSettings = () => {
    applyTheme()
    try {
      localStorage.setItem(APPEARANCE_SETTINGS_KEY, JSON.stringify(appearanceRequestOptions()))
    } catch {
      // 本地存储失败不影响界面切换。
    }
  }

  watch(
    () => [
      activeWorkspaceTab.value?.content_item_id || '',
      batchTasks.value.map((task) => `${task.task_id}:${task.content_item_id || ''}:${task.status || ''}`).join('|'),
    ],
    () => syncTaskEventStreamForActiveContent(),
    { flush: 'post' }
  )
  watch(selectedAiModel, (model) => {
    assistantAiModel.value = model
    persistAiSettings()
  })
  watch(autoQaShortcutRecognition, persistAssistantSettings)
  watch(selectedTheme, persistAppearanceSettings)
  onMounted(async () => {
    restoreAsrSettings()
    const hasLocalAiSettings = restoreAiSettings()
    restoreAssistantSettings()
    restoreAppearanceSettings()

    // Electron has already verified that this is the backend instance it
    // launched. Do not race it with an arbitrary renderer timeout: the
    // backend can still be restoring the local library and its schedulers.
    // The real workbench is already visible behind the startup gate, so
    // waiting here prevents an avoidable first-request timeout and retry.
    await waitForDesktopBackend(window.knowledgeHubDesktop?.waitForBackend)

    restoreWorkspaceState()

    // The file tree is the first useful surface after launch.  Start its
    // first, bounded page immediately; configuration and secondary panels can
    // continue to hydrate alongside it.
    void loadContentItems({ startup: true }).finally(scheduleDeferredCookieProbe)

    // Startup status is intentionally local and cheap.  A browser-backed
    // validation waits until the first library page is visible.
    loadCookieStatus(false, { probe: false })
    startCookieStatusPolling()
    loadBilibiliCookieStatus(true)

    try {
      const res = await axios.get(`${API}/config`)
      miniprogramForumCaptureEnabled.value = Boolean(res.data.miniprogram_forum_capture_enabled)
      if (Array.isArray(res.data.available_whisper_models)) {
        availableModels.value = res.data.available_whisper_models
      }
      if (Array.isArray(res.data.available_asr_backends)) {
        availableAsrBackends.value = res.data.available_asr_backends
        // A prior version allowed selecting the other platform's runtime.
        // Keep the rest of that local preset, but move this stale backend
        // choice back to automatic so the UI and actual runtime agree.
        if (!availableAsrBackends.value.includes(selectedAsrBackend.value)) {
          selectedAsrBackend.value = 'auto'
        }
      }
      if (!hasLocalAiSettings && res.data.deepseek_model_option) {
        selectedAiModel.value = res.data.deepseek_model_option
      } else if (!hasLocalAiSettings && res.data.deepseek_model) {
        selectedAiModel.value = normalizeAiModelValue(res.data.deepseek_model)
      }
      if (Array.isArray(res.data.available_ai_models)) {
        availableAiModels.value = res.data.available_ai_models
      } else if (res.data.deepseek_model) {
        availableAiModels.value = [normalizeAiModelValue(res.data.deepseek_model)]
      }
      void checkManualUpdate()
      const videoSettings = await axios.get(`${API}/video-download-settings`)
      autoDownloadBilibiliVideo.value = Boolean(videoSettings.data?.auto_download_bilibili_video)
      douyinVideoQuality.value = ['low', 'standard', 'high'].includes(videoSettings.data?.douyin_video_quality)
        ? videoSettings.data.douyin_video_quality
        : 'standard'
    } catch {
      // 配置读取失败不影响手动处理，保留前端默认值。
    }

    await loadObsidianSettings()

    startArticlePreparationStatusPolling()
    loadLibraryTrash()
    loadPromptTemplates()
    loadQaShortcutTemplates()
    loadContentAnalysisTemplates()
    loadAiTokenUsageSummary()
    aiTokenSummaryTimer = window.setInterval(loadAiTokenUsageSummary, 15000)
    await loadTaskQueue()
    startTaskQueuePolling()
    await loadCompletionNotifications()
    startCompletionNotificationPolling()
    const removeTrayListener = window.knowledgeHubDesktop?.onOpenPendingNotification?.((item) => {
      void openCompletionNotification(item)
    })
    window.__knowledgeHubRemoveTrayNotificationListener = removeTrayListener
    loadClipboardStatus()
    loadOpenClawStatus()
    startOpenClawStatusPolling()
    window.addEventListener('keydown', handleLibraryHistoryShortcut)
  })

  onBeforeUnmount(() => {
    stopPolling()
    stopBatchPolling()
    stopTaskQueuePolling()
    stopClipboardStatusPolling()
    stopOpenClawStatusPolling()
    stopCookieStatusPolling()
    stopArticlePreparationStatusPolling()
    stopCompletionNotificationPolling()
    window.__knowledgeHubRemoveTrayNotificationListener?.()
    delete window.__knowledgeHubRemoveTrayNotificationListener
    disposeArticlePreviews()
    if (aiTokenSummaryTimer) {
      window.clearInterval(aiTokenSummaryTimer)
      aiTokenSummaryTimer = null
    }
    cancelDeferredCookieProbe()
    if (contentStartupRetryTimer) {
      window.clearTimeout(contentStartupRetryTimer)
      contentStartupRetryTimer = null
    }
    window.removeEventListener('keydown', handleLibraryHistoryShortcut)
    disposeLibrarySearchController()
  })

  function stopPolling() {
    if (pollTimer.value) {
      clearTimeout(pollTimer.value)
      pollTimer.value = null
    }
    stopTaskEventStream()
    taskPollFailureCount.value = 0
  }

  function stopTaskEventStream() {
    if (taskEventSource) taskEventSource.close()
    taskEventSource = null
    taskEventSourceTaskId = ''
  }

  function startTaskEventStream(taskId) {
    const normalizedTaskId = String(taskId || '')
    if (!normalizedTaskId || typeof EventSource === 'undefined') return
    if (taskEventSource && taskEventSourceTaskId === normalizedTaskId) return
    stopTaskEventStream()

    const source = new EventSource(`${API}/tasks/${encodeURIComponent(normalizedTaskId)}/events`)
    taskEventSource = source
    taskEventSourceTaskId = normalizedTaskId
    source.addEventListener('task', (event) => {
      let data
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (String(data?.task_id || '') !== normalizedTaskId) return
      // Normal queue polling remains the durable source for history, while
      // the local stream makes every progressive milestone visible at once:
      // playable media, transcript readiness and the growing AI summary.
      mergeBatchTasks([data])
      applyTaskData(data)
      const previousSnapshot = progressiveTaskSnapshots.get(normalizedTaskId)
      void hydrateProgressiveTask(data, previousSnapshot)
      if (terminalStatuses.has(data.status) && taskEventSourceTaskId === normalizedTaskId) {
        stopTaskEventStream()
      }
    })
    source.addEventListener('error', () => {
      // EventSource reconnects itself. The regular task poll stays active as
      // the durable fallback if a local backend restart closes this channel.
    })
  }

  function syncTaskEventStreamForActiveContent() {
    const contentItemId = String(activeWorkspaceContent.value?.id || '')
    const activeTask = contentItemId
      ? batchTasks.value.find((task) => (
        String(task?.content_item_id || '') === contentItemId && isActiveTask(task)
      ))
      : null
    if (activeTask?.task_id) {
      startTaskEventStream(activeTask.task_id)
      return
    }
    // A stream belongs to one open detail pane. Do not leave a hidden tab
    // subscribed after the reader moves to a completed or unrelated item.
    if (taskEventSourceTaskId) stopTaskEventStream()
  }

  function stopBatchPolling() {
    if (batchPollTimer.value) {
      clearTimeout(batchPollTimer.value)
      batchPollTimer.value = null
    }
  }

  function startTaskQueuePolling() {
    if (taskQueueTimer.value) return
    taskQueueTimer.value = setInterval(() => {
      loadTaskQueue()
    }, taskQueuePollingIntervalMs.value)
  }

  function stopTaskQueuePolling() {
    if (taskQueueTimer.value) {
      clearInterval(taskQueueTimer.value)
      taskQueueTimer.value = null
    }
  }

  function setTaskQueuePollingInterval(intervalMs) {
    const nextInterval = Math.max(2000, Number(intervalMs) || 2000)
    if (taskQueuePollingIntervalMs.value === nextInterval) return
    taskQueuePollingIntervalMs.value = nextInterval
    if (!taskQueueTimer.value) return
    stopTaskQueuePolling()
    startTaskQueuePolling()
  }

  function shortLink(link) {
    return link.replace(/^https?:\/\//, '').replace(/^www\./, '').slice(0, 42)
  }

  function normalizeAiModelValue(model) {
    if (model === 'deepseek-chat') return 'deepseek-v4-flash:enabled'
    if (model === 'deepseek-reasoner') return 'deepseek-v4-flash:enabled'
    if (model === 'deepseek-v4-flash' || model === 'deepseek-v4-pro') {
      return `${model}:enabled`
    }
    return model || 'deepseek-v4-flash:enabled'
  }

  function stripAssistantMarkdown(markdown) {
    return documentMarkdownWithoutConversation(markdown)
      .replace(/\n## AI 摘要[\s\S]*$/u, '')
      .replace(/\n<details>[\s\S]*?<\/details>\s*$/iu, '')
      .trim()
  }

  function isGeneratedReportDocument(item) {
    return Boolean(item && !isForumCaptureDocument(item) && (
      item.content_type === 'report' || item.source_provider === 'wechat_report'
    ))
  }

  function isForumCaptureDocument(item) {
    return Boolean(item && item.source_provider === 'wechat_miniprogram' && (
      item.content_type === 'forum_capture' || item.content_type === 'report'
    ))
  }

  function isExternalMarkdownDocument(item) {
    if (!item) return false
    if (item.source_provider === 'local_markdown') return item.content_type === 'document'
    // Every retained local import writes its source into the canonical
    // Markdown document.  Image OCR and audio/video transcripts must use the
    // same durable source when a finished task is no longer in memory.
    return item.source_provider === 'local_file'
      && ['document', 'image', 'audio', 'video'].includes(item.content_type)
  }

  function stripForumCaptureMarkdownHeader(markdown) {
    return String(markdown || '').replace(/^\s*#\s+[^\n]+\r?\n+/u, '')
  }

  function extractSourceTextFromMarkdown(markdown) {
    const text = stripMarkdownMetadata(markdown || '')
    const detailsMatch = text.match(/<details>\s*<summary>(?:原文正文|原始转写文本)<\/summary>\s*([\s\S]*?)\s*<\/details>/iu)
    if (detailsMatch) return detailsMatch[1].trim()
    return ''
  }

  function restoreAsrSettings() {
    try {
      // v1 exposed ASR tuning.  New tasks are fixed to the desktop policy, so
      // discard that local preset instead of silently carrying it forward.
      localStorage.removeItem(ASR_SETTINGS_KEY)
    } catch {
      // Storage availability does not affect the fixed ASR policy.
    }
  }

  function restoreAiSettings() {
    try {
      const raw = localStorage.getItem(AI_SETTINGS_KEY)
      if (!raw) return false
      const data = JSON.parse(raw)
      selectedAiModel.value = normalizeAiModelValue(data.ai_model)
      return true
    } catch {
      return false
    }
  }

  function restoreAssistantSettings() {
    try {
      const raw = localStorage.getItem(ASSISTANT_SETTINGS_KEY)
      if (!raw) return false
      const data = JSON.parse(raw)
      autoQaShortcutRecognition.value = Boolean(data.auto_qa_shortcut_recognition ?? true)
      return true
    } catch {
      return false
    }
  }

  function restoreAppearanceSettings() {
    try {
      const raw = localStorage.getItem(APPEARANCE_SETTINGS_KEY)
      if (!raw) {
        applyTheme()
        return false
      }
      const data = JSON.parse(raw)
      selectedTheme.value = normalizeAppearanceTheme(data.theme)
      applyTheme()
      return true
    } catch {
      applyTheme()
      return false
    }
  }

  function appendAsrFormData(formData) {
    Object.entries(asrRequestOptions()).forEach(([key, value]) => {
      formData.append(key, String(value))
    })
  }

  function appendAiFormData(formData) {
    Object.entries(aiRequestOptions()).forEach(([key, value]) => {
      formData.append(key, String(value))
    })
  }

  function resetQaState() {
    resetActiveQaSession()
  }

  async function loadContentQaHistory(contentItemId, session = ensureQaSession(contentItemId)) {
    if (!contentItemId) return
    if (session.historyLoaded || session.historyLoading) return
    const requestId = ++session.historyRequestId
    const initialHistoryLength = session.history.length
    session.historyLoading = true
    session.historyError = ''
    syncQaSessionIfActive(contentItemId, session)
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const res = await axios.get(`${API}/content/${contentItemId}/qa-history`, {
          params: { limit: 12 },
          timeout: 10000
        })
        if (requestId !== session.historyRequestId) return
        const savedItems = savedQaHistoryItems(res.data?.items)
        // The user may send a question before the supplementary history request
        // returns. Merge that locally-created pending turn instead of replacing
        // it with the older persisted history.
        session.history = session.history.length === initialHistoryLength
          ? savedItems
          : [...savedItems, ...session.history]
        session.historyLoaded = true
        session.historyHasMore = Boolean(res.data?.has_more)
        session.historyNextBefore = String(res.data?.next_before || '')
        return
      } catch (error) {
        if (attempt < 2) {
          await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)))
          continue
        }
        session.historyError = error.response?.data?.detail || '历史对话加载失败，可重试'
      } finally {
        if (attempt === 2 || session.historyLoaded || requestId !== session.historyRequestId) {
          session.historyLoading = false
          syncQaSessionIfActive(contentItemId, session)
        }
      }
    }
  }

  async function loadMoreContentQaHistory() {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id || null
    if (!contentItemId) return
    const session = ensureQaSession(contentItemId)
    if (!session.historyLoaded || !session.historyHasMore || !session.historyNextBefore || session.historyLoadingMore) return
    const requestId = session.historyRequestId
    session.historyLoadingMore = true
    session.historyError = ''
    syncQaSessionIfActive(contentItemId, session)
    try {
      const res = await axios.get(`${API}/content/${contentItemId}/qa-history`, {
        params: { limit: 12, before: session.historyNextBefore },
        timeout: 10000
      })
      if (requestId !== session.historyRequestId) return
      session.history = [...savedQaHistoryItems(res.data?.items), ...session.history]
      session.historyHasMore = Boolean(res.data?.has_more)
      session.historyNextBefore = String(res.data?.next_before || '')
    } catch (error) {
      session.historyError = error.response?.data?.detail || '加载更早对话失败，可重试'
    } finally {
      session.historyLoadingMore = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  async function retryContentQaHistory() {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id || null
    if (!contentItemId) return
    const session = ensureQaSession(contentItemId)
    if (session.historyHasMore && session.historyNextBefore) {
      await loadMoreContentQaHistory()
      return
    }
    session.historyLoaded = false
    await loadContentQaHistory(contentItemId, session)
  }

  async function loadContentAnalysisTemplates() {
    try {
      const res = await axios.get(`${API}/prompts`, {
        params: { task_type: 'content_analysis' },
        timeout: 10000
      })
      contentAnalysisTemplates.value = sortPromptTemplates(res.data || [])
        .filter((template) => template.is_active && template.template?.trim())
    } catch {
      contentAnalysisTemplates.value = []
    }
  }

  function runContentAnalysis() {
    const customTemplate = contentAnalysisTemplates.value[0]
    if (!customTemplate?.template?.trim()) {
      ElMessage.error('未找到可用的自定义按钮提示词')
      return
    }
    return askQuestion('', { customTemplate })
  }

  function resetRunState() {
    stopPolling()
    running.value = false
    cancelling.value = false
    logs.value = []
    backendLogCount.value = 0
    backendLogCountsByTaskId.clear()
    activeStep.value = 0
    currentStep.value = null
    taskStatus.value = 'idle'
    taskCancelRequested.value = false
    openSections.value = ['source', 'timings']
    result.task_id = null
    result.content_item_id = null
    result.url = null
    result.platform = null
    result.video_path = null
    result.transcript = null
    result.summary = null
    result.display_title = null
    result.source_title = null
    result.obsidian_path = null
    result.markdown_draft_path = null
    result.whisper_model = null
    result.asr_backend = null
    result.text_source = null
    result.ai_calls = []
    result.error = null
    result.error_info = null
    result.persistence_error = null
    result.cache_hits = []
    result.logs = []
    result.timings = {}
    result.progress = {}
    result.overall_progress = 0
    result.download_transfer = null
    resetQaState()
  }

  function applyTaskData(data) {
    if (data.task_id && result.task_id && data.task_id !== result.task_id) {
      resetQaState()
    }
    const previousPersistenceError = result.persistence_error
    if (data.logs) {
      result.logs = data.logs
      addBackendLogs(data.logs, data)
    }
    result.task_id = data.task_id || null
    result.content_item_id = data.content_item_id || null
    result.timings = data.timings || {}
    result.url = data.url
    result.platform = data.platform
    result.video_path = data.video_path
    result.transcript = data.transcript
    result.summary = data.summary
    result.display_title = data.display_title || null
    result.source_title = data.source_title || null
    result.obsidian_path = data.obsidian_path
    result.markdown_draft_path = data.markdown_draft_path || null
    result.whisper_model = data.whisper_model || null
    result.asr_backend = data.asr_backend || null
    result.text_source = data.text_source || null
    result.ai_calls = data.ai_calls || []
    result.error = data.error || null
    result.error_info = data.error_info || null
    result.persistence_error = data.persistence_error || null
    result.cache_hits = data.cache_hits || []
    result.progress = data.progress || {}
    result.overall_progress = Number(data.overall_progress || 0)
    result.download_transfer = data.download_transfer || null
    taskStatus.value = data.status || (data.success ? 'succeeded' : data.error ? 'failed' : taskStatus.value)
    taskCancelRequested.value = Boolean(data.cancel_requested)
    currentStep.value = data.step || null
    if (data.persistence_error && data.persistence_error !== previousPersistenceError) {
      addLog(`本地保存失败：${data.persistence_error}`, 'error', data.step || null, null, {
        task_id: data.task_id || result.task_id || '',
        task_name: data.display_title || data.source_title || '',
        task_status: data.status || taskStatus.value,
        task_progress: data.overall_progress ?? result.overall_progress ?? 0,
      })
    }

    const stepMap = { parse: 1, info: 1, download: 2, extract_audio: 3, transcribe: 4, summarize: 5, save: 6, total: 6, cancelled: activeStep.value }
    if (taskStatus.value === 'succeeded') {
      activeStep.value = 6
    } else if (data.step && stepMap[data.step] !== undefined) {
      activeStep.value = stepMap[data.step]
    }
  }

  async function pollTask(taskId) {
    try {
      const res = await axios.get(`${API}/tasks/${taskId}`, { timeout: 10000 })
      taskPollFailureCount.value = 0
      const data = res.data
      applyTaskData(data)
      if (!terminalStatuses.has(data.status)) startTaskEventStream(taskId)
      const previousSnapshot = progressiveTaskSnapshots.get(data.task_id)
      await hydrateProgressiveTask(data, previousSnapshot)
      await revealWechatArticleSnapshot(data)
      await revealVideoSnapshot(data)
      await revealTranscriptSnapshot(data)

      if (terminalStatuses.has(data.status)) {
        running.value = false
        cancelling.value = false
        stopPolling()
        if (data.status === 'succeeded' && data.persistence_error) {
          addLog('处理结果已生成，但任务状态未能保存；重启后任务记录可能不完整', 'error')
          openSections.value = ['logs']
          await syncCompletedTaskContent(data.content_item_id)
          ElMessage.error('处理已完成，但任务状态未保存')
        } else if (data.status === 'succeeded') {
          addLog('全流程完成！', 'success')
          await syncCompletedTaskContent(data.content_item_id)
          ElMessage.success('处理完成')
        } else if (data.status === 'cancelled') {
          addLog('任务已取消', 'warn')
          openSections.value = ['logs']
          ElMessage.warning('任务已取消')
        } else {
          addLog(`失败: ${data.error || '任务失败'}`, 'error')
          openSections.value = ['logs']
          ElMessage.error(data.error || '任务失败')
        }
        return
      }

      pollTimer.value = setTimeout(() => pollTask(taskId), isPipelineSummaryGenerating.value ? 220 : 1500)
    } catch (e) {
      taskPollFailureCount.value += 1
      const msg = e.message || '查询任务状态失败'
      const retryDelay = Math.min(10000, 1500 * taskPollFailureCount.value)
      if (taskPollFailureCount.value === 1 || taskPollFailureCount.value % 5 === 0) {
        addLog(`任务状态暂时不可达：${msg}；${Math.round(retryDelay / 1000)} 秒后重试`, 'warn')
        openSections.value = ['logs']
      }
      pollTimer.value = setTimeout(() => pollTask(taskId), retryDelay)
    }
  }

  async function saveCookie({ closeAfterSave = true, notify = true } = {}) {
    if (!cookieInput.value.trim()) {
      if (cookieConfigured.value) {
        showSettings.value = false
        return
      }
      ElMessage.warning('请粘贴 Cookie')
      return
    }
    savingCookie.value = true
    try {
      const res = await axios.post(`${API}/cookie`, { cookie: cookieInput.value.trim() })
      if (res.data.success) {
        await loadCookieStatus(true)
        if (closeAfterSave) {
          showSettings.value = false
        }
        if (notify) {
          ElMessage.success(cookieState.value === 'valid' ? 'Cookie 已保存并验证可用' : 'Cookie 已保存，正在等待抖音验证')
        }
        return true
      } else {
        ElMessage.error(res.data.message)
      }
    } catch (e) {
      ElMessage.error('保存失败')
    } finally {
      savingCookie.value = false
    }
    return false
  }

  async function saveBilibiliCookie({ notify = true } = {}) {
    if (!bilibiliCookieInput.value.trim()) return true
    savingBilibiliCookie.value = true
    try {
      const res = await axios.post(
        `${API}/bilibili-cookie`,
        { cookie: bilibiliCookieInput.value.trim() },
        { timeout: 10000 }
      )
      if (!res.data.success) {
        ElMessage.error(res.data.message)
        return false
      }
      bilibiliCookieInput.value = ''
      await loadBilibiliCookieStatus()
      if (notify) ElMessage.success('B站 Cookie 已保存')
      return true
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message || 'B站 Cookie 保存失败')
      return false
    } finally {
      savingBilibiliCookie.value = false
    }
  }

  async function connectPlatformAuth(platform) {
    const connect = window.knowledgeHubDesktop?.connectPlatformAuth
    if (!connect) {
      ElMessage.warning('请使用桌面版在应用内登录；浏览器版仍可手动粘贴 Cookie。')
      return false
    }
    platformAuthConnecting.value = platform
    try {
      const status = await connect(platform)
      if (platform === 'bilibili') {
        await loadBilibiliCookieStatus(true)
      } else {
        await loadCookieStatus(true)
      }
      if (status?.state === 'valid') {
        ElMessage.success(`${platform === 'bilibili' ? 'B站' : '抖音'}登录态已连接并验证可用`)
        return true
      }
      if (status?.configured) {
        ElMessage.info(`${platform === 'bilibili' ? 'B站' : '抖音'}登录态已保存，正在等待平台验证`)
        return true
      }
      ElMessage.info('登录窗口已关闭；尚未检测到可用登录态。')
      return false
    } catch (error) {
      ElMessage.error(error?.message || '登录状态保存失败')
      return false
    } finally {
      platformAuthConnecting.value = ''
    }
  }

  async function disconnectPlatformAuth(platform) {
    const disconnect = window.knowledgeHubDesktop?.disconnectPlatformAuth
    if (!disconnect) return
    const label = platform === 'bilibili' ? 'B站' : '抖音'
    const confirmed = await requestDestructiveConfirmation({
      title: `断开${label}登录态`,
      message: `这会清除本应用保存的${label}登录会话和下载凭据；之后需要重新登录才能使用受限功能。`,
      confirmLabel: '断开登录态',
    })
    if (!confirmed) return
    platformAuthConnecting.value = platform
    try {
      await disconnect(platform)
      if (platform === 'bilibili') {
        await loadBilibiliCookieStatus(true)
      } else {
        await loadCookieStatus(true)
      }
      ElMessage.success(`${label}登录态已断开`)
    } catch (error) {
      ElMessage.error(error?.message || '断开登录态失败')
    } finally {
      platformAuthConnecting.value = ''
    }
  }

  async function loadObsidianSettings() {
    try {
      const res = await axios.get(`${API}/obsidian/settings`, { timeout: 10000 })
      obsidianVaultPath.value = res.data.vault_path || ''
      markdownExportPath.value = res.data.export_path || res.data.vault_path || ''
      obsidianAutoWrite.value = Boolean(res.data.auto_write)
    } catch {
      // Markdown 输出设置读取失败不影响其他功能。
    }
  }

  async function saveObsidianSettings() {
    const vaultPath = obsidianVaultPath.value.trim()
    const exportPath = markdownExportPath.value.trim()
    if (!vaultPath || !exportPath) {
      ElMessage.warning('请填写 Markdown 写入目录和默认导出目录')
      return false
    }
    try {
      const res = await axios.post(`${API}/obsidian/settings`, {
        vault_path: vaultPath,
        export_path: exportPath,
        auto_write: obsidianAutoWrite.value
      }, { timeout: 10000 })
      obsidianVaultPath.value = res.data.vault_path || vaultPath
      markdownExportPath.value = res.data.export_path || exportPath
      obsidianAutoWrite.value = Boolean(res.data.auto_write)
      return true
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '保存 Markdown 输出目录失败'
      ElMessage.error(typeof msg === 'string' ? msg : '保存 Markdown 输出目录失败')
      return false
    }
  }

  async function saveObsidianSettingsFromForm() {
    await saveObsidianSettings()
  }

  function scheduleContentStartupRetry() {
    startupPhase.value = 'retrying'
    if (contentStartupRetryTimer || contentStartupRetryCount >= 3) return
    contentStartupRetryCount += 1
    const delay = 600 * contentStartupRetryCount
    contentStartupRetryTimer = window.setTimeout(() => {
      contentStartupRetryTimer = null
      void loadContentItems({ startup: true })
    }, delay)
  }

  async function loadContentItems({ startup = false } = {}) {
    if (startup) startupPhase.value = 'library'
    loadingContent.value = true
    const loadVersion = ++contentPageLoadVersion
    contentPagesLoading.value = false
    Object.assign(contentPageLoadStatus, {
      state: 'idle',
      loaded: allContentItems.value.length,
      total: allContentItems.value.length,
    })
    try {
      // The source tree is the startup contract.  Article rows deliberately
      // stay out of this request path: a large library can have thousands of
      // entries, but the user only needs one small folder page at a time.
      await loadLibraryFolders({ throwOnError: startup })
      if (loadVersion !== contentPageLoadVersion) return
      contentStartupRetryCount = 0
      if (startup) {
        startupPhase.value = 'workspace'
        // A restored tab resolves only its own content item. It must not make
        // the complete library a startup dependency.
        void syncActiveWorkspaceTabSelection()
        startupPhase.value = 'ready'
      } else {
        void syncActiveWorkspaceTabSelection()
      }
    } catch (e) {
      const timedOut = e?.code === 'ECONNABORTED' || /timeout/i.test(String(e?.message || ''))
      if (startup && timedOut) {
        scheduleContentStartupRetry()
        ElMessage.warning('资料库暂未响应，正在重新连接')
      } else {
        if (startup) startupPhase.value = 'retrying'
        const msg = e.response?.data?.detail || e.message || '读取内容库失败'
        ElMessage.error(typeof msg === 'string' ? msg : '读取内容库失败')
      }
    } finally {
      loadingContent.value = false
    }
  }

  function retryStartupHydration() {
    if (startupPhase.value !== 'retrying') return
    if (contentStartupRetryTimer) {
      window.clearTimeout(contentStartupRetryTimer)
      contentStartupRetryTimer = null
    }
    contentStartupRetryCount = 0
    void loadContentItems({ startup: true })
  }

  function publishContentItems(items, { initialWindowComplete = false } = {}) {
    const recentItems = Array.isArray(items) ? items : []
    const retainedHistory = allContentItems.value.filter(isLoadedHistoryContent)
    const mergedItems = mergeUniqueContentItems(recentItems, retainedHistory)
    allContentItems.value = mergedItems
    reconcileContentViewState(mergedItems, { initialWindowComplete })
    applyContentFilter()
  }

  function isLoadedHistoryContent(item) {
    if (!contentRecentAfter || !item) return false
    const timestamp = Date.parse(item.published_at || item.created_at || '')
    const cutoff = Date.parse(contentRecentAfter)
    return Number.isFinite(timestamp) && Number.isFinite(cutoff) && timestamp < cutoff
  }

  function mergeExplicitHistoryItems(items) {
    const historyItems = Array.isArray(items) ? items.filter(Boolean) : []
    if (!historyItems.length) return
    allContentItems.value = mergeUniqueContentItems(allContentItems.value, historyItems)
    reconcileContentViewState(allContentItems.value)
    applyContentFilter()
  }

  function expandLibraryFolders(folderIds) {
    const ids = [...new Set((folderIds || []).map(String).filter(Boolean))]
    if (ids.length) libraryFolderRevealIds.value = ids
  }

  async function revealContentItems(contentItemIds) {
    const ids = [...new Set((contentItemIds || []).map(String).filter(Boolean))].slice(0, 300)
    if (!ids.length) return []
    try {
      const response = await axios.post(`${API}/content/items/resolve`, {
        content_item_ids: ids,
      }, { timeout: 15000 })
      const items = Array.isArray(response.data) ? response.data : []
      mergeExplicitHistoryItems(items)
      expandLibraryFolders(items.map((item) => item.library_folder_id))
      return items
    } catch (error) {
      // The normal refresh already succeeded. Do not turn a tree enhancement
      // into a failed source sync when this optional bounded request is lost.
      ElMessage.warning('历史资料已保存；展开左侧对应文件夹可重新加载')
      return []
    }
  }

  async function loadLibraryFolderHistory({ folderId, append = false } = {}) {
    const id = String(folderId || '')
    if (!id) return
    const previous = libraryFolderHistoryStates.value[id] || {
      offset: 0,
      hasMore: true,
      loaded: false,
    }
    if (previous.loading || (append && !previous.hasMore)) return
    const offset = append ? Number(previous.offset || 0) : 0
    libraryFolderHistoryStates.value = {
      ...libraryFolderHistoryStates.value,
      [id]: { ...previous, loading: true },
    }
    try {
      const response = await axios.get(`${API}/content/folders/${encodeURIComponent(id)}/items`, {
        params: {
          limit: 80,
          offset,
        },
        timeout: 15000,
      })
      const page = response.data || {}
      const items = Array.isArray(page.items) ? page.items : []
      mergeExplicitHistoryItems(items)
      libraryFolderHistoryStates.value = {
        ...libraryFolderHistoryStates.value,
        [id]: {
          offset: offset + items.length,
          hasMore: Boolean(page.has_more),
          loaded: true,
          loading: false,
        },
      }
    } catch (error) {
      libraryFolderHistoryStates.value = {
        ...libraryFolderHistoryStates.value,
        [id]: { ...previous, loading: false },
      }
      const detail = error?.response?.data?.detail || error?.message || '加载文件夹资料失败'
      ElMessage.error(typeof detail === 'string' ? detail : '加载文件夹资料失败')
    }
  }

  async function loadRemainingContentPages(
    initialItems,
    offset,
    loadVersion,
    recentAfter,
    totalItems = 0,
    { publishProgress = true } = {},
  ) {
    let collectedItems = [...initialItems]
    let nextOffset = offset
    let hasMore = true
    while (loadVersion === contentPageLoadVersion && hasMore) {
      const page = await fetchContentPage(nextOffset, recentAfter)
      const items = Array.isArray(page.items) ? page.items : []
      if (!items.length) throw new Error('内容分页提前结束')
      collectedItems = mergeUniqueContentItems(collectedItems, items)
      nextOffset += items.length
      hasMore = Boolean(page.has_more)
      // Startup keeps the gate in place until this recent window is complete;
      // publishing once avoids repeated tree layout work behind the overlay.
      if (loadVersion === contentPageLoadVersion && publishProgress) {
        publishContentItems(collectedItems, { initialWindowComplete: !hasMore })
        contentPageLoadStatus.loaded = collectedItems.length
        contentPageLoadStatus.total = Math.max(
          collectedItems.length,
          Number(page.total || totalItems || 0),
        )
        if (!hasMore) contentPageLoadStatus.state = 'idle'
      }
    }
    return collectedItems
  }

  async function fetchContentPage(offset, recentAfter = contentRecentAfter, limit = 200, { timeout = 10000 } = {}) {
    if (contentPageApiAvailable !== false) {
      try {
        const params = { limit, offset }
        if (recentAfter) params.recent_after = recentAfter
        const res = await axios.get(`${API}/content/page`, { params, timeout })
        contentPageApiAvailable = true
        const page = res.data || {}
        if (!contentRecentAfter && typeof page.recent_after === 'string') contentRecentAfter = page.recent_after
        return page
      } catch (error) {
        const status = error.response?.status
        if (status !== 404 && status !== 405) throw error
        contentPageApiAvailable = false
      }
    }

    const legacy = await axios.get(`${API}/content`, { params: { limit: 500 }, timeout })
    const items = Array.isArray(legacy.data) ? legacy.data : []
    return { items, total: items.length, offset: 0, has_more: false }
  }

  async function loadLibraryFolders({ throwOnError = false } = {}) {
    try {
      const res = await axios.get(`${API}/content/folders`, { timeout: 10000 })
      libraryFolders.value = res.data || []
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '读取文件夹失败'
      ElMessage.error(typeof msg === 'string' ? msg : '读取文件夹失败')
      if (throwOnError) throw e
    }
  }

  function applyContentFilter() {
    contentItems.value = allContentItems.value
  }

  async function updateContentStatus(item, status) {
    if (!item?.id || updatingContentId.value) return
    updatingContentId.value = item.id
    try {
      const res = await axios.patch(`${API}/content/${item.id}/status`, { status }, { timeout: 10000 })
      const updated = res.data
      allContentItems.value = allContentItems.value.map((current) => current.id === updated.id ? updated : current)
      applyContentFilter()
      ElMessage.success('状态已更新')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '更新状态失败'
      ElMessage.error(typeof msg === 'string' ? msg : '更新状态失败')
    } finally {
      updatingContentId.value = null
    }
  }

  function updateLocalContentItem(id, updater) {
    allContentItems.value = allContentItems.value.map((item) => {
      return item.id === id ? updater({ ...item }) : item
    })
    applyContentFilter()
    if (selectedContentItem.value?.id === id) {
      selectedContentItem.value = allContentItems.value.find((item) => item.id === id) || selectedContentItem.value
    }
  }

  async function createLibraryFolder(payload) {
    const snapshot = snapshotLibraryState()
    const tempId = `tmp-${Date.now()}`
    const tempFolder = {
      id: tempId,
      name: payload.name,
      parent_folder_id: payload.parent_folder_id || null,
      sort_order: nextSortOrder(payload.parent_folder_id || null),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    libraryFolders.value = [...libraryFolders.value, tempFolder]
    try {
      const res = await axios.post(`${API}/content/folders`, {
        name: payload.name,
        parent_folder_id: payload.parent_folder_id || null,
        sort_order: tempFolder.sort_order,
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((folder) => folder.id === tempId ? res.data : folder)
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '新建失败')
    }
  }

  async function renameLibraryFolder(payload) {
    const snapshot = snapshotLibraryState()
    const currentFolder = snapshot.folders.find((folder) => folder.id === payload.id)
    if (!currentFolder || currentFolder.name === payload.name) return
    libraryFolders.value = libraryFolders.value.map((folder) => {
      return folder.id === payload.id ? { ...folder, name: payload.name } : folder
    })
    try {
      const res = await axios.patch(`${API}/content/folders/${payload.id}`, {
        name: payload.name,
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((folder) => folder.id === payload.id ? { ...folder, ...res.data } : folder)
      recordLibraryHistory('重命名文件夹', snapshot, snapshotLibraryState(), [{ type: 'folder', id: payload.id }])
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '重命名失败')
    }
  }

  async function setLibraryFolderPinned({ folder, pinned }) {
    if (!folder?.id || Boolean(folder.is_pinned) === Boolean(pinned)) return
    const snapshot = snapshotLibraryState()
    libraryFolders.value = libraryFolders.value.map((current) => (
      current.id === folder.id ? { ...current, is_pinned: Boolean(pinned) } : current
    ))
    try {
      const res = await axios.patch(`${API}/content/folders/${folder.id}`, {
        is_pinned: Boolean(pinned),
      }, { timeout: 10000 })
      libraryFolders.value = libraryFolders.value.map((current) => current.id === folder.id ? { ...current, ...res.data } : current)
      recordLibraryHistory(pinned ? '置顶文件夹' : '取消置顶文件夹', snapshot, snapshotLibraryState(), [{ type: 'folder', id: folder.id }])
      ElMessage.success(pinned ? '文件夹已置顶' : '文件夹已取消置顶')
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '更新文件夹置顶状态失败')
    }
  }

  async function deleteLibraryFolder(folder) {
    const snapshot = snapshotLibraryState()
    const folderIds = descendantFolderIds(folder.id)
    const deletedItemIds = new Set(allContentItems.value
      .filter((item) => folderIds.has(item.library_folder_id))
      .map((item) => item.id))
    libraryFolders.value = libraryFolders.value.filter((item) => !folderIds.has(item.id))
    allContentItems.value = allContentItems.value.filter((item) => !deletedItemIds.has(item.id))
    applyContentFilter()
    closeDeletedTabs(deletedItemIds)
    try {
      await axios.delete(`${API}/content/folders/${folder.id}`, { timeout: 10000 })
      discardLibraryHistoryForNodes([
        ...[...folderIds].map((id) => ({ type: 'folder', id })),
        ...[...deletedItemIds].map((id) => ({ type: 'content', id })),
      ])
      await loadLibraryTrash()
      showTrashUndoMessage([
        { entry_type: 'folder', id: folder.id, name: folder.name },
      ], '已移入回收站')
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
    }
  }

  async function renameContentItem(payload) {
    const snapshot = snapshotLibraryState()
    const currentItem = snapshot.allItems.find((item) => item.id === payload.id)
    if (!currentItem || currentItem.title === payload.title) return
    updateLocalContentItem(payload.id, (item) => ({ ...item, title: payload.title }))
    workspaceTabs.value = workspaceTabs.value.map((tab) => {
      return tab.content_item_id === payload.id ? { ...tab, title: payload.title } : tab
    })
    try {
      const res = await axios.patch(`${API}/content/${payload.id}`, {
        title: payload.title,
      }, { timeout: 10000 })
      updateLocalContentItem(payload.id, () => res.data)
      recordLibraryHistory('重命名内容', snapshot, snapshotLibraryState(), [{ type: 'content', id: payload.id }])
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '重命名失败')
    }
  }

  async function deleteContentItem(item) {
    const snapshot = snapshotLibraryState()
    const deletedIds = new Set([item.id])
    allContentItems.value = allContentItems.value.filter((current) => current.id !== item.id)
    applyContentFilter()
    closeDeletedTabs(deletedIds)
    try {
      await axios.delete(`${API}/content/${item.id}`, { timeout: 10000 })
      discardLibraryHistoryForNodes([{ type: 'content', id: item.id }])
      await loadLibraryTrash()
      showTrashUndoMessage([
        { entry_type: 'content', id: item.id, name: item.title },
      ], '已移入回收站')
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
    }
  }

  async function deleteLibraryNodes(nodes) {
    if (!Array.isArray(nodes) || !nodes.length) return
    const snapshot = snapshotLibraryState()
    const selectedFolders = nodes.filter((node) => node.type === 'folder')
    const selectedContents = nodes.filter((node) => node.type === 'content')
    const folderIds = new Set()
    selectedFolders.forEach((folder) => {
      descendantFolderIds(folder.id).forEach((id) => folderIds.add(id))
    })
    const deletedItemIds = new Set(selectedContents.map((item) => item.id))
    allContentItems.value.forEach((item) => {
      if (folderIds.has(item.library_folder_id)) deletedItemIds.add(item.id)
    })

    libraryFolders.value = libraryFolders.value.filter((folder) => !folderIds.has(folder.id))
    allContentItems.value = allContentItems.value.filter((item) => !deletedItemIds.has(item.id))
    applyContentFilter()
    closeDeletedTabs(deletedItemIds)

    const topFolders = selectedFolders.filter((folder) => {
      let parentId = snapshot.folders.find((candidate) => candidate.id === folder.id)?.parent_folder_id || null
      while (parentId) {
        if (selectedFolders.some((candidate) => candidate.id === parentId)) return false
        parentId = snapshot.folders.find((candidate) => candidate.id === parentId)?.parent_folder_id || null
      }
      return true
    })
    const contentIdsInDeletedFolders = new Set()
    snapshot.allItems.forEach((item) => {
      if (folderIds.has(item.library_folder_id)) contentIdsInDeletedFolders.add(item.id)
    })
    const directlyDeletedContents = selectedContents.filter((item) => !contentIdsInDeletedFolders.has(item.id))

    try {
      for (const folder of topFolders) {
        await axios.delete(`${API}/content/folders/${folder.id}`, { timeout: 10000 })
      }
      for (const item of directlyDeletedContents) {
        await axios.delete(`${API}/content/${item.id}`, { timeout: 10000 })
      }
      await loadLibraryTrash()
      discardLibraryHistoryForNodes([
        ...[...folderIds].map((id) => ({ type: 'folder', id })),
        ...[...deletedItemIds].map((id) => ({ type: 'content', id })),
      ])
      showTrashUndoMessage([
        ...topFolders.map((folder) => ({ entry_type: 'folder', id: folder.id, name: folder.name })),
        ...directlyDeletedContents.map((item) => ({ entry_type: 'content', id: item.id, name: item.title })),
      ], `已将 ${nodes.length} 个项目移入回收站`)
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
    }
  }

  async function moveLibraryNode(payload) {
    if (Array.isArray(payload?.drags) && payload.drags.length > 1) {
      await moveLibraryNodes(payload)
      return
    }
    const drag = payload.drag
    const target = payload.target
    if (!drag || !target || (drag.type === target.type && drag.id === target.id)) return
    if (drag.type === 'folder' && target.type === 'folder' && isDescendantFolder(target.id, drag.id)) {
      ElMessage.warning('不能移动到自身或子文件夹')
      return
    }

    const snapshot = snapshotLibraryState()
    const parentId = Object.prototype.hasOwnProperty.call(payload, 'parentId')
      ? payload.parentId
      : payload.position === 'inside' && target.type === 'folder'
        ? target.id
        : target.parentId || null
    const requestedSortOrder = Number(payload.sortOrder)
    const sortOrder = Number.isFinite(requestedSortOrder)
      ? requestedSortOrder
      : sortOrderForDrop(parentId, target, payload.position)

    if (drag.type === 'folder') {
      libraryFolders.value = libraryFolders.value.map((folder) => {
        return folder.id === drag.id
          ? { ...folder, parent_folder_id: parentId, sort_order: sortOrder }
          : folder
      })
    } else {
      updateLocalContentItem(drag.id, (item) => ({ ...item, library_folder_id: parentId, sort_order: sortOrder }))
    }

    try {
      if (drag.type === 'folder') {
        await axios.patch(`${API}/content/folders/${drag.id}`, {
          parent_folder_id: parentId,
          sort_order: sortOrder,
        }, { timeout: 10000 })
      } else {
        await axios.patch(`${API}/content/${drag.id}`, {
          library_folder_id: parentId,
          sort_order: sortOrder,
        }, { timeout: 10000 })
      }
      recordLibraryHistory('移动项目', snapshot, snapshotLibraryState(), [{ type: drag.type, id: drag.id }])
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '移动失败')
    }
  }

  async function moveLibraryNodes(payload) {
    const drags = Array.isArray(payload?.drags) ? payload.drags : []
    const target = payload?.target
    if (!drags.length || !target) return
    const snapshot = snapshotLibraryState()
    const validDrags = drags.filter((drag) => {
      if (drag.type === target.type && drag.id === target.id) return false
      if (drag.type === 'folder' && target.type === 'folder' && isDescendantFolder(target.id, drag.id)) return false
      return true
    })
    if (!validDrags.length) return

    const parentId = Object.prototype.hasOwnProperty.call(payload, 'parentId')
      ? payload.parentId
      : payload.position === 'inside' && target.type === 'folder'
        ? target.id
        : target.parentId || null
    const requestedSortOrder = Number(payload.sortOrder)
    const baseSortOrder = Number.isFinite(requestedSortOrder)
      ? requestedSortOrder
      : sortOrderForDrop(parentId, target, payload.position)

    validDrags.forEach((drag, index) => {
      const sortOrder = baseSortOrder + index * 0.001
      if (drag.type === 'folder') {
        libraryFolders.value = libraryFolders.value.map((folder) => {
          return folder.id === drag.id
            ? { ...folder, parent_folder_id: parentId, sort_order: sortOrder }
            : folder
        })
      } else {
        updateLocalContentItem(drag.id, (item) => ({ ...item, library_folder_id: parentId, sort_order: sortOrder }))
      }
    })

    try {
      for (const [index, drag] of validDrags.entries()) {
        const sortOrder = baseSortOrder + index * 0.001
        if (drag.type === 'folder') {
          await axios.patch(`${API}/content/folders/${drag.id}`, {
            parent_folder_id: parentId,
            sort_order: sortOrder,
          }, { timeout: 10000 })
        } else {
          await axios.patch(`${API}/content/${drag.id}`, {
            library_folder_id: parentId,
            sort_order: sortOrder,
          }, { timeout: 10000 })
        }
      }
      recordLibraryHistory(`移动 ${validDrags.length} 个项目`, snapshot, snapshotLibraryState(), validDrags.map((drag) => ({ type: drag.type, id: drag.id })))
    } catch (e) {
      restoreLibraryState(snapshot)
      ElMessage.error(e.response?.data?.detail || e.message || '移动失败')
    }
  }

  function closeDeletedTabs(deletedItemIds) {
    workspaceTabs.value = workspaceTabs.value.filter((tab) => !deletedItemIds.has(tab.content_item_id))
    if (selectedContentItem.value && deletedItemIds.has(selectedContentItem.value.id)) {
      selectedContentItem.value = null
      resetMarkdownState()
    }
    if (!workspaceTabs.value.some((tab) => tab.id === activeWorkspaceTabId.value)) {
      activeWorkspaceTabId.value = workspaceTabs.value[0]?.id || ''
    }
  }

  function descendantFolderIds(folderId) {
    const ids = new Set([folderId])
    let changed = true
    while (changed) {
      changed = false
      for (const folder of libraryFolders.value) {
        if (folder.parent_folder_id && ids.has(folder.parent_folder_id) && !ids.has(folder.id)) {
          ids.add(folder.id)
          changed = true
        }
      }
    }
    return ids
  }

  function isDescendantFolder(candidateId, parentId) {
    return descendantFolderIds(parentId).has(candidateId)
  }

  function nextSortOrder(parentId) {
    const orders = siblingNodes(parentId).map((node) => Number(node.sort_order || 0))
    return orders.length ? Math.max(...orders) + 1 : 1
  }

  function sortOrderForDrop(parentId, target, position) {
    if (position === 'inside') return nextSortOrder(parentId)
    const siblings = siblingNodes(parentId)
      .filter((node) => !(node.kind === target.type && node.id === target.id))
      .sort((left, right) => Number(left.sort_order || 0) - Number(right.sort_order || 0))
    const targetOrder = Number(target.sortOrder || 0)
    const before = siblings.filter((node) => Number(node.sort_order || 0) < targetOrder).at(-1)
    const after = siblings.find((node) => Number(node.sort_order || 0) > targetOrder)
    if (position === 'before') {
      return before ? (Number(before.sort_order || 0) + targetOrder) / 2 : targetOrder - 1
    }
    return after ? (targetOrder + Number(after.sort_order || 0)) / 2 : targetOrder + 1
  }

  function siblingNodes(parentId) {
    const normalizedParent = parentId || null
    return [
      ...libraryFolders.value
        .filter((folder) => (folder.parent_folder_id || null) === normalizedParent)
        .map((folder) => ({ ...folder, kind: 'folder' })),
      ...allContentItems.value
        .filter((item) => (item.library_folder_id || null) === normalizedParent)
        .map((item) => ({ ...item, kind: 'content' })),
    ]
  }

  function applyMarkdownState(data) {
    markdownState.content_item_id = data.content_item_id || null
    markdownState.markdown_draft_path = data.markdown_draft_path || null
    markdownState.obsidian_path = data.obsidian_path || null
    markdownState.markdown = data.markdown || ''
    markdownState.markdown_size_bytes = Number(data.markdown_size_bytes || 0)
    markdownState.sync_status = data.sync_status || 'unknown'
    markdownState.conflict = Boolean(data.conflict)
    markdownState.last_synced_at = data.last_synced_at || null
  }

  function resetMarkdownState() {
    markdownState.content_item_id = null
    markdownState.markdown_draft_path = null
    markdownState.obsidian_path = null
    markdownState.markdown = ''
    markdownState.markdown_size_bytes = 0
    markdownState.sync_status = 'unknown'
    markdownState.conflict = false
    markdownState.last_synced_at = null
  }

  async function selectContentItem(item, { awaitPrimaryPreview = false } = {}) {
    const changed = String(selectedContentItem.value?.id || '') !== String(item.id || '')
    selectedContentItem.value = item
    currentMarkdownItem.value = item
    const hydrationPromise = hydrateContentItem(item).then((detail) => {
      if (String(selectedContentItem.value?.id || '') !== String(detail?.id || '')) return
      selectedContentItem.value = detail
      currentMarkdownItem.value = detail
      updatePendingArticlePreviewReadiness(detail)
      if (isLocalHtmlDocument(detail)) void loadArticlePreview(detail)
    })
    void hydrationPromise
    if (changed) {
      const session = activateQaSession(item.id)
      void loadContentQaHistory(item.id, session)
    } else if (!isQaSessionActive(item.id)) {
      activateQaSession(item.id)
    }
    scheduleContentViewed(item.id)
    let primaryPreviewPromise = Promise.resolve()
    if (
      (['article', 'forum_post'].includes(item.content_type) && ['wechat', 'campus', 'rss', 'wechat_miniprogram', 'xiaohongshu'].includes(item.source_provider))
      || isLocalHtmlDocument(item)
    ) {
      // Start restoring the local article snapshot immediately. Markdown state is
      // unrelated and may take longer to resolve on first open.
      primaryPreviewPromise = loadArticlePreview(item)
      void primaryPreviewPromise
    }
    void loadCurrentArticleOcrStatus()
    void loadContentAiCalls(item.id)
    loadingMarkdown.value = true
    try {
      const res = await axios.get(`${API}/markdown/content/${item.id}`, { timeout: 10000 })
      if (String(selectedContentItem.value?.id || '') === String(item.id)) {
        applyMarkdownState(res.data)
      }
    } catch {
      if (String(selectedContentItem.value?.id || '') === String(item.id)) {
        resetMarkdownState()
      }
    } finally {
      if (String(selectedContentItem.value?.id || '') === String(item.id)) {
        loadingMarkdown.value = false
      }
    }
    if (awaitPrimaryPreview) {
      await Promise.all([hydrationPromise, primaryPreviewPromise])
    }
  }

  async function hydrateContentItem(item) {
    if (!item?.id) return item
    return (await getContentItemDetail(item.id)) || item
  }

  function isLocalHtmlDocument(item) {
    if (item?.source_provider !== 'local_file' || item?.content_type !== 'document') return false
    const format = String(item?.source_metadata?.file_format || '').toUpperCase()
    const filename = String(item?.source_metadata?.file_name || '')
    return ['HTML', 'HTM', 'XHTML'].includes(format) || /\.x?html?$/i.test(filename)
  }

  async function loadContentAiCalls(contentItemId) {
    if (!contentItemId) return
    try {
      const res = await axios.get(`${API}/content/${contentItemId}/ai-calls`, { timeout: 10000 })
      aiCallsByContentId[contentItemId] = Array.isArray(res.data) ? res.data : []
    } catch {
      // Token 统计失败不影响内容阅读或追问。
    }
  }

  async function loadAiTokenUsageSummary() {
    if (aiTokenSummaryLoading) return
    aiTokenSummaryLoading = true
    try {
      const [knowledgeResult, openClawResult] = await Promise.allSettled([
        axios.get(`${API}/ai-calls/summary`, { timeout: 10000 }),
        axios.get(`${API}/openclaw/usage`, { timeout: 10000 })
      ])
      if (knowledgeResult.status === 'fulfilled') {
        const data = knowledgeResult.value.data || {}
        dailyAiTokenUsage.value = {
          period_start: String(data.period_start || ''),
          call_count: Number(data.call_count || 0),
          prompt_tokens: Number(data.prompt_tokens || 0),
          completion_tokens: Number(data.completion_tokens || 0),
          total_tokens: Number(data.total_tokens || 0),
          prompt_cache_hit_tokens: Number(data.prompt_cache_hit_tokens || 0),
          prompt_cache_miss_tokens: Number(data.prompt_cache_miss_tokens || 0),
          estimated_cost: Number(data.estimated_cost || 0),
          unreported_count: Number(data.unreported_count || 0),
          by_type: Array.isArray(data.by_type) ? data.by_type : [],
          by_model: Array.isArray(data.by_model) ? data.by_model : [],
          image_call_count: Number(data.image_call_count || 0),
          image_count: Number(data.image_count || 0),
          image_estimated_cost: Number(data.image_estimated_cost || 0),
          by_image_model: Array.isArray(data.by_image_model) ? data.by_image_model : []
        }
      }
      if (openClawResult.status === 'fulfilled') {
        const data = openClawResult.value.data || {}
        openClawTokenUsage.value = {
          available: Boolean(data.available),
          reason: String(data.reason || ''),
          session_count: Number(data.session_count || 0),
          model_response_count: Number(data.model_response_count || 0),
          input_tokens: Number(data.input_tokens || 0),
          output_tokens: Number(data.output_tokens || 0),
          cache_read_tokens: Number(data.cache_read_tokens || 0),
          cache_write_tokens: Number(data.cache_write_tokens || 0),
          total_tokens: Number(data.total_tokens || 0),
          estimated_cost_usd: Number(data.estimated_cost_usd || 0),
          sessions: Array.isArray(data.sessions) ? data.sessions : []
        }
      }
    } catch {
      // 全局 Token 汇总不可用时保留上一份数据，不影响处理流程。
    } finally {
      aiTokenSummaryLoading = false
    }
  }

  function appendContentAiCall(contentItemId, call) {
    if (!contentItemId || !call) return
    const existingCalls = Array.isArray(aiCallsByContentId[contentItemId])
      ? aiCallsByContentId[contentItemId]
      : []
    aiCallsByContentId[contentItemId] = [...existingCalls, call]
    void loadAiTokenUsageSummary()
  }

  async function openMarkdownDialog(item) {
    currentMarkdownItem.value = item
    selectedContentItem.value = item
    showMarkdownDialog.value = true
    loadingMarkdown.value = true
    try {
      const res = await axios.get(`${API}/markdown/content/${item.id}`, { timeout: 10000 })
      applyMarkdownState(res.data)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '读取 Markdown 草稿失败'
      ElMessage.error(typeof msg === 'string' ? msg : '读取 Markdown 草稿失败')
      showMarkdownDialog.value = false
    } finally {
      loadingMarkdown.value = false
    }
  }

  async function saveMarkdownDraft() {
    if (!currentMarkdownItem.value?.id) return
    savingMarkdown.value = true
    try {
      const res = await axios.put(`${API}/markdown/content/${currentMarkdownItem.value.id}`, {
        markdown: markdownState.markdown
      }, { timeout: 10000 })
      applyMarkdownState(res.data)
      selectedContentItem.value = currentMarkdownItem.value
      ElMessage.success('草稿已保存')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '保存 Markdown 失败'
      ElMessage.error(typeof msg === 'string' ? msg : '保存 Markdown 失败')
    } finally {
      savingMarkdown.value = false
    }
  }

  async function syncMarkdownDraft() {
    if (!currentMarkdownItem.value?.id) return
    syncingMarkdown.value = true
    try {
      const res = await axios.post(`${API}/markdown/content/${currentMarkdownItem.value.id}/sync`, {}, { timeout: 10000 })
      applyMarkdownState(res.data)
      selectedContentItem.value = currentMarkdownItem.value
      ElMessage.success('已写入指定 Markdown 目录')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '写入 Markdown 失败'
      ElMessage.error(typeof msg === 'string' ? msg : '写入 Markdown 失败')
    } finally {
      syncingMarkdown.value = false
    }
  }

  async function loadPromptTemplates() {
    const taskType = promptTaskType.value
    loadingPrompts.value = true
    try {
      const res = await axios.get(`${API}/prompts`, {
        params: { task_type: taskType },
        timeout: 10000
      })
      if (taskType !== promptTaskType.value) return
      promptTemplates.value = sortPromptTemplates(res.data || [])
      if (!creatingPromptTemplate.value && !promptTemplates.value.some((template) => template.id === selectedPromptTemplateId.value)) {
        selectedPromptTemplateId.value = activePromptTemplate.value?.id || ''
      }
      if (!creatingPromptTemplate.value) {
        promptEditorName.value = promptTemplateDisplayName(activePromptTemplate.value)
        promptEditorText.value = activePromptTemplate.value?.template || ''
      }
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '读取 Prompt 失败'
      ElMessage.error(typeof msg === 'string' ? msg : '读取 Prompt 失败')
    } finally {
      loadingPrompts.value = false
    }
  }

  async function loadQaShortcutTemplates() {
    try {
      const res = await axios.get(`${API}/prompts`, {
        params: { task_type: 'qa_shortcut' },
        timeout: 10000
      })
      qaShortcutTemplates.value = sortPromptTemplates(res.data || []).filter((template) => template.template?.trim())
    } catch {
      qaShortcutTemplates.value = []
    }
  }

  function selectPromptTemplate(templateId) {
    creatingPromptTemplate.value = false
    creatingPromptFolderId.value = null
    selectedPromptTemplateId.value = templateId
    promptEditorName.value = promptTemplateDisplayName(activePromptTemplate.value)
    promptEditorText.value = activePromptTemplate.value?.template || ''
  }

  function createPromptTemplate({ taskType = promptTaskType.value, name = '', folderId = null } = {}) {
    promptTaskType.value = taskType
    creatingPromptTemplate.value = true
    creatingPromptFolderId.value = folderId
    selectedPromptTemplateId.value = ''
    promptEditorName.value = name
    promptEditorText.value = ''
  }

  function sortPromptTemplates(templates) {
    return [...templates].sort((a, b) => promptTemplateOrder(a) - promptTemplateOrder(b))
  }

  function promptTemplateOrder(template) {
    try {
      const schema = typeof template.variables_schema === 'string'
        ? JSON.parse(template.variables_schema)
        : template.variables_schema
      const order = Number(schema?.order)
      return Number.isFinite(order) ? order : 999
    } catch {
      return 999
    }
  }

  async function savePromptTemplate() {
    const editorName = promptEditorName.value.trim()
    const template = promptEditorText.value.trim()
    if (!editorName || !template) {
      ElMessage.warning('请填写提示词名称和内容')
      return
    }

    savingPromptTemplate.value = true
    const taskType = promptTaskType.value
    const baseTemplate = creatingPromptTemplate.value ? null : activePromptTemplate.value
    const name = promptTemplatePersistedName(baseTemplate, editorName)
    try {
      if (baseTemplate?.id) {
        await axios.patch(`${API}/prompts/${baseTemplate.id}`, {
          name,
          template,
          variables_schema: baseTemplate.variables_schema
        }, { timeout: 10000 })
      } else {
        const created = await axios.post(`${API}/prompts`, {
          name,
          task_type: taskType,
          version: `v${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}-${Date.now().toString().slice(-4)}`,
          template,
          folder_id: creatingPromptFolderId.value,
          is_active: taskType === 'qa_shortcut'
        }, { timeout: 10000 })
        selectedPromptTemplateId.value = created.data?.id || ''
      }
      creatingPromptTemplate.value = false
      creatingPromptFolderId.value = null
      await loadPromptTemplates()
      if (taskType === 'qa_shortcut') {
        await loadQaShortcutTemplates()
      }
      if (taskType === 'content_analysis') {
        await loadContentAnalysisTemplates()
      }
      ElMessage.success(
        baseTemplate
          ? '提示词已保存'
          : taskType === 'qa_shortcut'
            ? '快捷追问已保存并启用'
            : '提示词已保存，请设为当前使用'
      )
      return selectedPromptTemplateId.value
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '保存 Prompt 失败'
      ElMessage.error(typeof msg === 'string' ? msg : '保存 Prompt 失败')
      return ''
    } finally {
      savingPromptTemplate.value = false
    }
  }

  async function activatePromptTemplate(templateId) {
    const template = promptTemplates.value.find((item) => item.id === templateId)
    if (!template || template.is_active) return
    activatingPromptTemplate.value = true
    try {
      await axios.post(`${API}/prompts/${templateId}/activate`, {}, { timeout: 10000 })
      await loadPromptTemplates()
      selectedPromptTemplateId.value = templateId
      promptEditorName.value = promptTemplateDisplayName(promptTemplates.value.find((item) => item.id === templateId))
      promptEditorText.value = promptTemplates.value.find((item) => item.id === templateId)?.template || ''
      ElMessage.success(template.task_type === 'qa_shortcut' ? '快捷追问已启用' : '已设为当前使用')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '启用 Prompt 失败'
      ElMessage.error(typeof msg === 'string' ? msg : '启用 Prompt 失败')
    } finally {
      activatingPromptTemplate.value = false
    }
  }

  async function deletePromptTemplate(templateId) {
    const template = promptTemplates.value.find((item) => item.id === templateId)
    if (!template) return
    const confirmed = await requestDestructiveConfirmation({
      title: '移入回收站',
      message: `将“${template.name}”移入提示词回收站？`,
      confirmLabel: '移入回收站',
    })
    if (!confirmed) return

    try {
      await axios.delete(`${API}/prompts/${templateId}`, { timeout: 10000 })
      creatingPromptTemplate.value = false
      selectedPromptTemplateId.value = ''
      promptEditorName.value = ''
      promptEditorText.value = ''
      await loadPromptTemplates()
      if (template.task_type === 'qa_shortcut') {
        await loadQaShortcutTemplates()
      }
      if (template.task_type === 'content_analysis') {
        await loadContentAnalysisTemplates()
      }
      ElMessage.success('提示词已移入回收站')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '删除提示词失败'
      ElMessage.error(typeof msg === 'string' ? msg : '删除提示词失败')
    }
  }

  async function loadInboxItems() {
    loadingInbox.value = true
    try {
      const res = await axios.get(`${API}/inbox`, { timeout: 10000 })
      inboxItems.value = res.data || []
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '读取收件箱失败'
      ElMessage.error(typeof msg === 'string' ? msg : '读取收件箱失败')
    } finally {
      loadingInbox.value = false
    }
  }

  async function loadTaskQueue() {
    if (taskQueueSyncing) return
    taskQueueSyncing = true
    try {
      const requestStartedAt = new Date().toISOString()
      const params = taskQueueUpdatedAfter
        ? { updated_after: taskQueueUpdatedAfter }
        : undefined
      const res = await axios.get(`${API}/tasks`, { params, timeout: 10000 })
      taskQueueUpdatedAfter = requestStartedAt
      const tasks = res.data || []
      const visibleTasks = tasks.filter((task) => shouldDisplayTask(task))
      const taskIds = visibleTasks.map((task) => task.task_id).filter(Boolean)
      let shouldRefreshContent = false
      const progressiveUpdates = []
      for (const task of visibleTasks) {
        const previousSnapshot = taskQueueSnapshots.get(task.task_id)
        const previousProgressiveSnapshot = progressiveTaskSnapshots.get(task.task_id)
        shouldRefreshContent = shouldRefreshContent || shouldRefreshContentForTask(
          task,
          previousSnapshot,
          taskQueueInitialized,
          terminalStatuses
        )
        const snapshot = taskContentSnapshot(task)
        taskQueueSnapshots.set(task.task_id, snapshot)
        // The first queue read also contains historical task records. Do not
        // turn startup into hundreds of content/detail requests; only live
        // work (or the item the reader already has open) needs progressive
        // hydration at that point. Later queue deltas are handled normally.
        if (
          taskQueueInitialized
          || isActiveTask(task)
          || activeWorkspaceTab.value?.content_item_id === task.content_item_id
        ) {
          progressiveUpdates.push(hydrateProgressiveTask(task, previousProgressiveSnapshot))
        }
      }

      if (!tasks.length) {
        taskQueueInitialized = true
        return
      }
      batchTaskIds.value = [...new Set([...batchTaskIds.value, ...taskIds])]
      mergeBatchTasks(visibleTasks)
      taskQueueInitialized = true
      await Promise.allSettled(progressiveUpdates)
      if (shouldRefreshContent) {
        await loadContentItems()
      }
      if (activeBatchCount.value) {
        pollBatchTasks()
      }
    } catch {
      // 队列加载失败不影响单条处理。
    } finally {
      taskQueueSyncing = false
    }
  }

  async function processInboxItem(item) {
    if (!item?.id || processingInboxIds.value.has(item.id)) return
    processingInboxIds.value = new Set([...processingInboxIds.value, item.id])
    try {
      const res = await axios.post(`${API}/inbox/${item.id}/process`, {
        ...asrRequestOptions(),
        ...aiRequestOptions(),
        use_cache: useCache.value
      }, { timeout: 10000 })
      const taskId = res.data.task_id
      const taskSummary = {
        ...res.data,
        content_item_id: res.data.item?.id || item.id,
        status: res.data.task_status || 'queued',
      }
      if (taskId) {
        batchTaskNames.value[taskId] = item.title || item.source_url || `任务 ${taskId}`
        batchTaskIds.value = [...new Set([...batchTaskIds.value, taskId])]
        mergeBatchTasks([taskSummary])
        await hydrateProgressiveTask(taskSummary, progressiveTaskSnapshots.get(taskId))
        await pollBatchTasks()
      }
      await loadInboxItems()
      await syncVisibleProgressiveContent(taskSummary)
      clipboardStatus.value = '已创建处理任务'
      ElMessage.success('已加入处理队列')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '创建处理任务失败'
      ElMessage.error(typeof msg === 'string' ? msg : '创建处理任务失败')
    } finally {
      const next = new Set(processingInboxIds.value)
      next.delete(item.id)
      processingInboxIds.value = next
    }
  }

  function mergeBatchTasks(tasks) {
    const byId = new Map(batchTasks.value.map((task) => [task.task_id, task]))
    for (const task of tasks) {
      const existing = byId.get(task.task_id)
      if (task.details_included === false && existing) {
        const merged = { ...existing, ...task }
        const detailFields = [
          'text_source',
          'ai_calls',
          'cache_hits',
          'logs',
          'timings',
          'error_info',
          'transcript',
          'summary',
        ]
        detailFields.forEach((field) => {
          if (existing[field] !== undefined) merged[field] = existing[field]
        })
        merged.details_included = Boolean(
          existing.detail_updated_at
          && existing.detail_updated_at === task.updated_at
        )
        merged.detail_updated_at = existing.detail_updated_at || ''
        byId.set(task.task_id, merged)
        continue
      }
      byId.set(task.task_id, {
        ...existing,
        ...task,
        detail_updated_at: task.updated_at || existing?.detail_updated_at || '',
      })
    }
    batchTasks.value = batchTaskIds.value
      .map((id) => byId.get(id))
      .filter(Boolean)
  }

  function batchTaskName(task) {
    return batchTaskNames.value[task.task_id]
      || task.display_title
      || task.source_title
      || task.local_video_path?.split('/').pop()
      || task.local_subtitle_path?.split('/').pop()
      || task.video_path?.split('/').pop()
      || task.url
      || `任务 ${task.task_id}`
  }

  function batchTaskMeta(task) {
    const parts = [stepLabel(task.step || 'queued'), `模型 ${modelLabel(task.whisper_model)}`]
    if (task.execution_mode === 'background') {
      parts.push('后台')
    }
    if (Number(task.priority || 100) <= 10) {
      parts.push('优先')
    }
    return parts.join(' · ')
  }

  function registerContentRecoveryBatchTask(task, item, { merge = true, allowSourceUrlFallback = true } = {}) {
    const taskId = task?.task_id
    if (!taskId) return
    batchTaskNames.value[taskId] = item?.title || (allowSourceUrlFallback ? item?.source_url : '') || `任务 ${taskId}`
    batchTaskIds.value = [...new Set([...batchTaskIds.value, taskId])]
    if (merge) mergeBatchTasks([task])
  }

  async function pollBatchTasks() {
    stopBatchPolling()
    if (!batchTaskIds.value.length) return

    try {
      const knownTasks = new Map(batchTasks.value.map((task) => [task.task_id, task]))
      const taskIds = batchTaskIds.value.filter((taskId) => {
        const task = knownTasks.get(taskId)
        return !task || isActiveTask(task)
      }).slice(0, 200)
      if (!taskIds.length) return
      const res = await axios.get(`${API}/tasks`, {
        params: { task_ids: taskIds.join(',') },
        timeout: 10000,
      })
      const byId = new Map((res.data || []).map((task) => [task.task_id, task]))
      const nextTasks = batchTaskIds.value.map((id) => byId.get(id)).filter(Boolean)
      const previousStatusByTaskId = new Map(batchTasks.value.map((task) => [task.task_id, task.status]))
      const previousProgressiveSnapshots = new Map(
        nextTasks.map((task) => [task.task_id, progressiveTaskSnapshots.get(task.task_id)])
      )
      const newlyCompletedContentTasks = nextTasks.filter((task) => (
        task.content_item_id
        && terminalStatuses.has(task.status)
        && !terminalStatuses.has(previousStatusByTaskId.get(task.task_id))
      ))
      mergeBatchTasks(nextTasks)
      await Promise.allSettled(nextTasks.map((task) => (
        hydrateProgressiveTask(task, previousProgressiveSnapshots.get(task.task_id))
      )))
      // Do not wait for every task in a batch to finish before refreshing the
      // tree. A content item receives its provider folder during processing,
      // so refreshing at each terminal transition keeps (for example) Douyin
      // videos inside their folder immediately.
      if (newlyCompletedContentTasks.length) await loadContentItems()
      if (activeBatchCount.value) {
        const hasStreamingSummary = nextTasks.some((task) => (
          task.status === 'running'
          && Number(task?.progress?.summarize || 0) > 0
          && Number(task?.progress?.summarize || 0) < 100
        ))
        batchPollTimer.value = setTimeout(() => pollBatchTasks(), hasStreamingSummary ? 320 : 1500)
      } else {
        await loadContentItems()
      }
    } catch (e) {
      batchPollTimer.value = setTimeout(() => pollBatchTasks(), 3000)
    }
  }

  async function monitorCreatorSyncTasks({ taskIds = [], contentItemIds = [] } = {}) {
    const ids = [...new Set(taskIds.filter(Boolean))]
    const itemIds = new Set(contentItemIds.filter(Boolean))

    // Creator sync creates normal pipeline tasks on the server. Bring those
    // tasks into the same process dock as a manually submitted video, and
    // open the first item so its processing state is visible immediately.
    await loadContentItems()
    const firstItem = allContentItems.value.find((item) => itemIds.has(item.id))
    if (firstItem) await openContentTab(firstItem)
    if (!ids.length) return

    try {
      const response = await axios.get(`${API}/tasks`, {
        params: { task_ids: ids.slice(0, 200).join(',') },
        timeout: 10000,
      })
      const byId = new Map((response.data || []).map((task) => [task.task_id, task]))
      const tasks = ids.map((id) => byId.get(id)).filter(Boolean)
      tasks.forEach((task) => {
        batchTaskNames.value[task.task_id] = task.display_title || task.source_title || task.url || `任务 ${task.task_id}`
      })
      batchTaskIds.value = [...new Set([...batchTaskIds.value, ...ids])]
      mergeBatchTasks(tasks)

      const firstTask = tasks[0]
      if (firstTask) {
        resetRunState()
        running.value = !terminalStatuses.has(firstTask.status)
        applyTaskData(firstTask)
        addLog(`创作者同步已加入处理队列：${batchTaskName(firstTask)}`, 'info')
        if (!terminalStatuses.has(firstTask.status)) void pollTask(firstTask.task_id)
      }
      await pollBatchTasks()
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '无法读取创作者处理任务'
      ElMessage.error(typeof message === 'string' ? message : '无法读取创作者处理任务')
    }
  }

  async function cancelBatchTask(task) {
    try {
      const res = await axios.post(`${API}/tasks/${task.task_id}/cancel`, {}, { timeout: 10000 })
      mergeBatchTasks([res.data])
      if (res.data.task_id === result.task_id) applyTaskData(res.data)
      ElMessage.warning('已请求取消')
      await pollBatchTasks()
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '取消失败'
      ElMessage.error(msg)
    }
  }

  async function cancelActiveTasks() {
    try {
      const response = await axios.post(`${API}/tasks/cancel-active`, {}, { timeout: 10000 })
      const cancelled = Array.isArray(response.data?.tasks) ? response.data.tasks : []
      if (!cancelled.length) {
        ElMessage.info('当前没有可取消的任务')
        return
      }
      mergeBatchTasks(cancelled)
      const activeResult = cancelled.find((task) => task.task_id === result.task_id)
      if (activeResult) applyTaskData(activeResult)
      ElMessage.warning(`已请求取消 ${response.data.cancelled_count || cancelled.length} 个任务`)
      await pollBatchTasks()
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '批量取消失败'
      ElMessage.error(typeof message === 'string' ? message : '批量取消失败')
    }
  }

  async function loadBatchTaskDetails(task) {
    const taskId = task?.task_id
    if (!taskId || loadingBatchTaskDetailIds.has(taskId)) return
    if (
      task.details_included !== false
      && task.detail_updated_at
      && task.detail_updated_at === task.updated_at
    ) return

    loadingBatchTaskDetailIds.add(taskId)
    try {
      const response = await axios.get(`${API}/tasks/${taskId}`, { timeout: 10000 })
      mergeBatchTasks([response.data])
    } catch {
      // The queue summary remains usable when one historical detail request
      // fails; a later selection or task update retries it.
    } finally {
      loadingBatchTaskDetailIds.delete(taskId)
    }
  }

  async function retryBatchTask(task) {
    try {
      const res = await axios.post(`${API}/tasks/${task.task_id}/retry`, {}, { timeout: 10000 })
      mergeBatchTasks([res.data])
      ElMessage.success('已重新加入队列')
      await pollBatchTasks()
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '重试失败'
      ElMessage.error(msg)
    }
  }

  async function copyText(value, message) {
    if (!value) return
    try {
      const desktopCopy = window.knowledgeHubDesktop?.copyText
      if (desktopCopy) await desktopCopy(value)
      else await navigator.clipboard.writeText(value)
      ElMessage.success(message)
    } catch {
      ElMessage.error('复制失败')
    }
  }

  function openExternalLink(value) {
    if (!value) return
    if (window.knowledgeHubDesktop?.openExternal) {
      window.knowledgeHubDesktop.openExternal(value).catch(() => {
        ElMessage.error('无法使用默认浏览器打开链接')
      })
      return
    }
    window.open(value, '_blank', 'noopener,noreferrer')
  }

  async function revealLibraryNodeLocation(node) {
    const desktopReveal = window.knowledgeHubDesktop?.revealPath
    if (!desktopReveal) {
      ElMessage.warning('请在桌面版中使用“在 Finder 中显示”')
      return
    }
    const isFolder = node?.type === 'folder'
    const nodeId = String(node?.raw?.id || node?.id || '').trim()
    if (!nodeId) return
    try {
      let localPath = ''
      if (isFolder) {
        const response = await axios.get(`${API}/content/folders/${encodeURIComponent(nodeId)}/location`, { timeout: 10000 })
        localPath = String(response.data?.path || '')
      } else {
        const response = await axios.get(`${API}/markdown/content/${encodeURIComponent(nodeId)}`, { timeout: 10000 })
        localPath = String(response.data?.markdown_draft_path || response.data?.obsidian_path || '')
      }
      if (!localPath) throw new Error('本地 Markdown 文件尚未生成')
      await desktopReveal(localPath)
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || '无法打开所在位置'
      ElMessage.error(typeof detail === 'string' ? detail : '无法打开所在位置')
    }
  }

  async function revealLocalPath(localPath) {
    const desktopReveal = window.knowledgeHubDesktop?.revealPath
    if (!desktopReveal) {
      ElMessage.warning('请在桌面版中使用“在 Finder 中显示”')
      return
    }
    if (!String(localPath || '').trim()) return
    try {
      await desktopReveal(localPath)
    } catch (error) {
      ElMessage.error(error?.message || '无法打开所在位置')
    }
  }

  function recordTelemetry(eventName, properties = {}) {
    return axios.post(`${API}/telemetry/events`, { event_name: eventName, properties }, { timeout: 2000 }).catch(() => {})
  }

  async function checkManualUpdate() {
    try {
      const response = await axios.get(`${API}/updates/check`, { timeout: 6000 })
      const update = response.data || {}
      if (update.state !== 'available' || !update.download_page_url) return
      const notes = String(update.release_notes || '').trim()
      await ElMessageBox.confirm(
        notes
          ? `发现 KnowledgeHub ${update.latest_version}。\n\n${notes}`
          : `发现 KnowledgeHub ${update.latest_version}。`,
        '有可用更新',
        {
          confirmButtonText: '打开下载页',
          cancelButtonText: '稍后再说',
          type: 'info',
          closeOnClickModal: true,
        },
      )
      openExternalLink(update.download_page_url)
      void recordTelemetry('update_download_page_opened')
    } catch (error) {
      // The manifest is optional and update checks must not interrupt startup.
      if (error !== 'cancel' && error?.message !== 'cancel') return
    }
  }

  async function startNewChat() {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id || null
    const session = ensureQaSession(contentItemId)
    if (session.asking || session.generatingSummary || startingNewChat.value) return
    if (!contentItemId) {
      clearQaSession(contentItemId, session)
      ElMessage.success('已开启新对话')
      return
    }

    startingNewChat.value = true
    try {
      const response = await axios.post(`${API}/content/${contentItemId}/qa/new-conversation`, {}, { timeout: 10000 })
      clearQaSession(contentItemId, session)
      if (response.data?.archived) {
        ElMessage.success('已开启新对话；上一轮追问已归档到 Markdown')
      } else {
        ElMessage.success('已开启新对话')
      }
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '开启新对话失败'
      ElMessage.error(typeof message === 'string' ? message : '开启新对话失败')
    } finally {
      startingNewChat.value = false
    }
  }

  async function onInputChange() {
    if (inputParseTimer) {
      clearTimeout(inputParseTimer)
    }
    const text = shareText.value.trim()
    if (!text) {
      inputParseRequestId += 1
      parsedUrl.value = null
      return
    }
    inputParseTimer = setTimeout(() => {
      inputParseTimer = null
      parseShareText(text)
    }, 260)
  }

  async function parseShareText(text) {
    const requestId = ++inputParseRequestId
    if (!shareText.value.trim()) {
      parsedUrl.value = null
      return
    }
    try {
      const res = await axios.post(`${API}/parse`, { text })
      if (requestId !== inputParseRequestId || text !== shareText.value.trim()) return
      if (res.data.success) {
        parsedUrl.value = { url: res.data.url, platform: res.data.platform }
        result.url = res.data.url
        result.platform = res.data.platform
        activeStep.value = 1
      } else {
        parsedUrl.value = null
      }
    } catch {
      parsedUrl.value = null
    }
  }

  async function runFullPipeline() {
    const text = shareText.value.trim()
    if (!text) {
      ElMessage.warning('请输入链接')
      return
    }

    resetRunState()
    running.value = true
    void recordTelemetry('import_started', { input_kind: 'link' })

    addLog('提交任务…', 'info')

    try {
      const res = await axios.post(`${API}/ingest/link`, {
        text,
        mode: 'process',
        ...asrRequestOptions(),
        ...aiRequestOptions(),
        use_cache: useCache.value
      }, { timeout: 10000 })
      const data = res.data.task || res.data
      if (!data?.task_id) throw new Error('链接已识别，但未能创建处理任务')
      applyTaskData(data)
      batchTaskNames.value[data.task_id] = res.data.item?.title || data.source_title || text
      batchTaskIds.value = [...new Set([...batchTaskIds.value, data.task_id])]
      mergeBatchTasks([data])
      await hydrateProgressiveTask(data, progressiveTaskSnapshots.get(data.task_id))
      inputParseRequestId += 1
      shareText.value = ''
      parsedUrl.value = null
      addLog(`任务已创建: ${data.task_id}`, 'success')
      void recordTelemetry('import_completed', { result: 'accepted' })
      pollTask(data.task_id)
    } catch (e) {
      const detail = e.response?.data?.detail
      if (detail && typeof detail === 'object') {
        if (detail.logs) addBackendLogs(detail.logs)
        if (detail.timings) result.timings = detail.timings
        addLog(`失败: ${detail.error}`, 'error')
        openSections.value = ['logs']
        ElMessage.error(detail.error)
      } else {
        const msg = typeof detail === 'string' ? detail : (e.message || '请求失败')
        addLog(`失败: ${msg}`, 'error')
        openSections.value = ['logs']
        ElMessage.error(msg)
      }
    } finally {
      if (!result.task_id) {
        running.value = false
      }
    }
  }

  async function cancelCurrentTask() {
    if (!result.task_id) return
    cancelling.value = true
    try {
      const res = await axios.post(`${API}/tasks/${result.task_id}/cancel`, {}, { timeout: 10000 })
      applyTaskData(res.data)
      ElMessage.warning('已请求取消')
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || '取消失败'
      addLog(`取消失败: ${msg}`, 'error')
      openSections.value = ['logs']
      ElMessage.error(msg)
    } finally {
      cancelling.value = false
    }
  }

  async function askQuestion(quickPrompt = '', { customTemplate = null } = {}) {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id || null
    const session = ensureQaSession(contentItemId)
    if (session.asking || session.generatingSummary || startingNewChat.value) return
    const draftQuestion = customTemplate
      ? `自定义按钮：${customTemplate.name || '未命名提示词'}`
      : removeSelectedTextContextToken(String(quickPrompt || session.draft)).trim()
    const resolvedQuestion = customTemplate
      ? {
          prompt: `已选择的追问方式：\n${customTemplate.name || '自定义按钮'}\n${customTemplate.template.trim()}`,
          autoShortcutName: ''
        }
      : resolveQaQuestion(draftQuestion)
    const question = resolvedQuestion.prompt
    if (!question) {
      ElMessage.warning('请输入追问内容')
      return
    }
    const selectionContext = activeSelectedTextContext.value
    const modelQuestion = selectionContext
      ? `【用户选中的原文】\n${selectionContext.text}\n\n【用户的问题】\n${question}`
      : question
    const displayQuestion = selectionContext
      ? `@选中文本\n> ${selectionContext.text.replace(/\n/gu, '\n> ')}\n\n${draftQuestion}`
      : draftQuestion
    session.asking = true
    session.lastSaved = false
    syncQaSessionIfActive(contentItemId, session)
    const historySnapshot = qaHistoryForPrompt(session.history)
    const pendingItem = {
      question: draftQuestion,
      modelQuestion,
      displayQuestion,
      selectedText: selectionContext?.text || '',
      answer: '',
      saved: false,
      autoShortcutName: resolvedQuestion.autoShortcutName,
      pending: true,
      error: false,
      time: new Date().toLocaleTimeString()
    }
    session.history.push(pendingItem)
    refreshQaSessionHistory(contentItemId, session)
    if (!quickPrompt && !customTemplate) {
      session.draft = ''
      syncQaSessionIfActive(contentItemId, session)
    }
    try {
      const shouldAppendToObsidian = obsidianAutoWrite.value && Boolean(currentObsidianPath.value)
      const response = await fetch(localApiRequestUrl(`${API}/qa/stream`), {
        method: 'POST',
        headers: await localApiAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          question: modelQuestion,
          display_question: displayQuestion,
          summary: currentSummaryText.value || '',
          transcript: activeWorkspaceTranscript.value || result.transcript || '',
          video_title: activeWorkspaceContent.value?.title || result.source_title || '',
          source_url: activeWorkspaceContent.value?.source_url || result.url || '',
          content_item_id: contentItemId,
          obsidian_path: shouldAppendToObsidian ? currentObsidianPath.value : null,
          history: historySnapshot,
          append_to_obsidian: shouldAppendToObsidian,
          ai_model: assistantAiModel.value
        })
      })
      if (!response.ok) {
        const errorText = await response.text()
        try {
          const errorData = JSON.parse(errorText)
          throw new Error(errorData.detail || '追问失败')
        } catch (error) {
          if (error instanceof SyntaxError) {
            throw new Error(errorText || '追问失败')
          }
          throw error
        }
      }
      await readQaStream(response, pendingItem, contentItemId, { session })
      // Do not interrupt an answer the user is already reading. If they
      // switched context while it streamed, keep a lightweight local event.
      if (String(activeWorkspaceContent.value?.id || '') !== String(contentItemId || '') || document.visibilityState !== 'visible') {
        const questionPreview = String(draftQuestion || 'AI 追问').replace(/\s+/gu, ' ').slice(0, 80)
        const answerPreview = String(pendingItem.answer || '').replace(/\s+/gu, ' ').slice(0, 240)
        await axios.post(`${API}/completion-notifications`, {
          event_key: `qa:${contentItemId || 'workspace'}:${pendingItem.id || Date.now()}`,
          event_type: 'assistant_response', title: questionPreview, body: answerPreview,
          content_item_id: contentItemId, target_view: 'library',
        }, { timeout: 10000 }).catch(() => {})
        await loadCompletionNotifications()
        if (document.visibilityState === 'visible') {
          ElNotification({
            title: questionPreview,
            message: answerPreview || 'AI 已完成回复，点击顶部待查看按钮可回到这条内容。',
            duration: 6000,
          })
        }
      }
      if (resolvedQuestion.autoShortcutName) {
        ElMessage.info(`已按本地规则附加 @${resolvedQuestion.autoShortcutName} 追问指引`)
      }
      if (session.lastSaved) {
        ElMessage.success('追问已自动写入 Markdown')
      } else if (pendingItem.savedToContent) {
        if (pendingItem.obsidianError) {
          ElMessage.warning('回答已保存到内容记录；Markdown 未自动写入')
        } else {
          ElMessage.success('已保存到内容记录，可在重新打开时继续追问')
        }
      } else {
        ElMessage.success('已基于当前内容生成回答')
      }
    } catch (e) {
      pendingItem.pending = false
      pendingItem.error = true
      pendingItem.answer = pendingItem.answer || '追问失败'
      refreshQaSessionHistory(contentItemId, session)
      const msg = e.response?.data?.detail || e.message || '追问失败'
      ElMessage.error(typeof msg === 'string' ? msg : '追问失败')
    } finally {
      session.asking = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  function copyQaExchange(item) {
    const question = String(item?.displayQuestion || item?.question || '').trim()
    const selectedText = String(item?.selectedText || '').trim()
    const answer = String(item?.answer || '').trim()
    if (!question || !answer) {
      ElMessage.warning('当前问答尚未完成，无法复制')
      return
    }
    const selectedSection = selectedText ? `\n\n> ${selectedText.replace(/\n/gu, '\n> ')}` : ''
    const markdown = `## 我\n\n${question}${selectedSection}\n\n## AI\n\n${answer}`
    copyText(markdown, '已复制本次完整问答')
  }

  async function regenerateQaAnswer(item) {
    const contentItemId = activeWorkspaceContent.value?.id || result.content_item_id || null
    const session = ensureQaSession(contentItemId)
    const itemIndex = session.history.indexOf(item)
    if (!contentItemId || !item?.id || itemIndex !== session.history.length - 1) {
      ElMessage.warning('只能重新生成当前会话最后一条回答')
      return
    }
    if (session.asking || session.generatingSummary || startingNewChat.value || item.pending) return

    const previousAnswer = String(item.answer || '')
    const question = String(item.modelQuestion || resolveQaQuestion(item.question).prompt || '').trim()
    if (!question) {
      ElMessage.warning('找不到原始提问，无法重新生成')
      return
    }
    const historySnapshot = qaHistoryForPrompt(session.history.slice(0, itemIndex))
    session.asking = true
    session.lastSaved = false
    item.answer = ''
    item.pending = true
    item.error = false
    refreshQaSessionHistory(contentItemId, session)
    try {
      const response = await fetch(localApiRequestUrl(`${API}/qa/stream`), {
        method: 'POST',
        headers: await localApiAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          question,
          display_question: String(item.displayQuestion || item.question || '').trim(),
          summary: currentSummaryText.value || '',
          transcript: activeWorkspaceTranscript.value || result.transcript || '',
          video_title: activeWorkspaceContent.value?.title || result.source_title || '',
          source_url: activeWorkspaceContent.value?.source_url || result.url || '',
          content_item_id: contentItemId,
          history: historySnapshot,
          append_to_obsidian: false,
          ai_model: assistantAiModel.value,
          regenerate_assistant_message_id: item.id
        })
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || '重新生成回答失败')
      }
      await readQaStream(response, item, contentItemId, { session })
      ElMessage.success(item.obsidianError ? '回答已重新生成，但 Markdown 更新失败' : '回答已重新生成')
    } catch (error) {
      item.answer = previousAnswer
      item.pending = false
      item.error = false
      refreshQaSessionHistory(contentItemId, session)
      ElMessage.error(error?.message || '重新生成回答失败')
    } finally {
      session.asking = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  async function generateAiSummary() {
    const item = activeRegenerableContent.value
    if (!item?.id) {
      ElMessage.warning('请先打开一篇公众号文章或一个已处理的视频')
      return
    }
    const session = ensureQaSession(item.id)
    if (session.asking || session.generatingSummary || startingNewChat.value) return
    if (String(currentSummaryText.value || '').trim()) {
      ElMessage.info('当前内容已有 AI 摘要')
      return
    }

    session.asking = true
    session.generatingSummary = true
    session.generatingSummaryText = ''
    session.lastSaved = false
    syncQaSessionIfActive(item.id, session)

    const displayQuestion = '生成 AI 摘要'
    const logTaskId = `manual:summary:${item.id}:${Date.now()}`
    const logTaskName = `生成摘要 · ${item.title || '文章'}`
    const writeRegenerationLog = (entry) => {
      addLog(
        entry.message,
        entry.level || 'info',
        entry.step || 'summarize',
        entry.elapsed_seconds ?? null,
        {
          task_id: logTaskId,
          task_name: logTaskName,
          task_status: entry.status || 'running',
          task_progress: entry.progress ?? 0
        }
      )
    }
    writeRegenerationLog({
      message: '开始生成 AI 摘要',
      level: 'info',
      step: 'summarize',
      progress: 5,
      status: 'running'
    })
    let waitingForModelTimer = setTimeout(() => {
      writeRegenerationLog({
        message: 'AI 服务仍在生成，最长等待约 90 秒',
        level: 'info',
        step: 'summarize',
        progress: 35,
        status: 'running'
      })
    }, 15000)
    const pendingItem = {
      question: displayQuestion,
      answer: '',
      saved: false,
      pending: true,
      error: false,
      time: new Date().toLocaleTimeString()
    }

    try {
      const response = await fetch(localApiRequestUrl(`${API}/qa/stream`), {
        method: 'POST',
        headers: await localApiAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          question: '请基于当前内容的完整原文生成 AI 摘要。',
          display_question: displayQuestion,
          summary: '',
          transcript: '',
          video_title: item.title || '',
          source_url: item.source_url || '',
          content_item_id: item.id,
          obsidian_path: null,
          history: [],
          append_to_obsidian: false,
          ai_model: assistantAiModel.value,
          regenerate_summary: true
        })
      })
      if (!response.ok) {
        const errorText = await response.text()
        try {
          const errorData = JSON.parse(errorText)
          throw new Error(errorData.detail || '生成 AI 摘要失败')
        } catch (error) {
          if (error instanceof SyntaxError) throw new Error(errorText || '生成 AI 摘要失败')
          throw error
        }
      }
      await readQaStream(response, pendingItem, item.id, {
        session,
        onLog: writeRegenerationLog,
        onFirstDelta: () => {
          clearTimeout(waitingForModelTimer)
          waitingForModelTimer = null
          writeRegenerationLog({
            message: 'AI 已开始返回总结内容',
            level: 'info',
            step: 'summarize',
            progress: 55,
            status: 'running'
          })
        },
        onCommit: (summary) => {
          session.generatingSummaryText = summary
          syncQaSessionIfActive(item.id, session)
        },
      })
      // Summary generation updates the canonical summary rather than adding a
      // Q&A exchange. The existing conversation remains visible and untouched.
      if (session.lastSaved) {
        ElMessage.success('AI 摘要已生成并自动写入 Markdown')
      } else if (pendingItem.savedToContent) {
        ElMessage.success('AI 摘要已保存到内容记录')
      } else {
        ElMessage.success('AI 摘要已生成')
      }
    } catch (error) {
      pendingItem.pending = false
      pendingItem.error = true
      pendingItem.answer = pendingItem.answer || '生成 AI 摘要失败'
      session.generatingSummaryText = ''
      refreshQaSessionHistory(item.id, session)
      const failureMessage = error?.message || '生成 AI 摘要失败'
      const latestTaskLog = [...logs.value].reverse().find((entry) => entry.task_id === logTaskId)
      if (latestTaskLog?.task_status !== 'failed') {
        writeRegenerationLog({
          message: `生成 AI 摘要失败：${failureMessage}`,
          level: 'error',
          step: 'summarize',
          progress: 100,
          status: 'failed'
        })
      }
      ElMessage.error(failureMessage)
    } finally {
      clearTimeout(waitingForModelTimer)
      session.asking = false
      session.generatingSummary = false
      syncQaSessionIfActive(item.id, session)
    }
  }

  async function exportConversationMarkdown() {
    if (exportingConversationMarkdown.value) return
    const content = activeWorkspaceContent.value
    const title = String(content?.title || result.source_title || 'AI 对话').replace(/\r?\n/g, ' ').trim()
    const sourceUrl = content?.source_url || result.url || ''
    const sections = [`# ${title}`]
    if (sourceUrl) sections.push(`来源：${sourceUrl}`)
    const summary = String(currentSummaryText.value || '').trim()
    if (summary) sections.push(`## AI 总结\n\n${summary}`)
    const exchanges = qaHistory.value
      .filter((item) => String(item.question || '').trim() || String(item.answer || '').trim())
      .map((item) => {
        const question = String(item.question || '').trim()
        const answer = String(item.answer || '').trim() || '（尚未生成回答）'
        return `### 我\n\n${question}\n\n### AI\n\n${answer}`
      })
    if (exchanges.length) sections.push(`## 对话\n\n${exchanges.join('\n\n---\n\n')}`)
    if (!summary && !exchanges.length) {
      ElMessage.warning('当前没有可导出的 AI 总结或对话')
      return
    }

    exportingConversationMarkdown.value = true
    try {
      const exportTitle = `${title}-AI对话`
      const markdown = `${sections.join('\n\n')}\n`
      const desktopExport = window.knowledgeHubDesktop?.exportMarkdown
      const exported = desktopExport
        ? await desktopExport(exportTitle, markdown)
        : (await axios.post(`${API}/markdown/export`, {
            title: exportTitle,
            markdown
          }, { timeout: 15000 })).data
      ElMessage.success(`Markdown 已导出到 ${exported.path}`)
      void recordTelemetry('export_completed', { export_kind: 'markdown', result: 'succeeded' })
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '导出 Markdown 失败'
      ElMessage.error(typeof message === 'string' ? message : '导出 Markdown 失败')
      void recordTelemetry('export_completed', { export_kind: 'markdown', result: 'failed' })
    } finally {
      exportingConversationMarkdown.value = false
    }
  }

  function insertQaShortcut(name) {
    const shortcutName = String(name || '').trim()
    if (!shortcutName) return
    const token = `@${shortcutName}`
    const current = questionInput.value || ''
    questionInput.value = /(?:^|\s)@[^\s@]*$/u.test(current)
      ? current.replace(/@[^\s@]*$/u, `${token} `)
      : `${current}${current && !/\s$/u.test(current) ? ' ' : ''}${token} `
  }

  function resolveQaQuestion(draftQuestion) {
    const byName = new Map(
      qaShortcutTemplates.value
        .filter((template) => template?.name?.trim() && template?.template?.trim())
        .map((template) => [template.name.trim(), template.template.trim()])
    )
    const parts = []
    const shortcutBodies = []
    const remainingText = draftQuestion.replace(/@([^\s@]+)/gu, (token, name) => {
      const template = byName.get(name)
      if (!template) return token
      shortcutBodies.push(`@${name}\n${template}`)
      return ''
    }).replace(/\s{2,}/gu, ' ').trim()

    if (shortcutBodies.length) {
      parts.push(`已选择的追问方式：\n${shortcutBodies.join('\n\n')}`)
    }
    if (remainingText) {
      parts.push(`用户补充：\n${remainingText}`)
    }
    if (shortcutBodies.length) {
      return {
        prompt: parts.join('\n\n'),
        autoShortcutName: ''
      }
    }

    const autoShortcut = autoQaShortcutRecognition.value
      ? matchQaShortcut(draftQuestion, qaShortcutTemplates.value)
      : null
    if (autoShortcut) {
      return {
        prompt: [
          `已选择的追问方式：\n@${autoShortcut.name}\n${autoShortcut.template}`,
          `用户补充：\n${draftQuestion}`
        ].join('\n\n'),
        autoShortcutName: autoShortcut.name
      }
    }
    return {
      prompt: parts.join('\n\n') || draftQuestion,
      autoShortcutName: ''
    }
  }

  async function readQaStream(response, pendingItem, contentItemId, options = {}) {
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式响应')

    const decoder = new TextDecoder()
    let buffer = ''
    const streamState = { receivedDone: false, doneData: null }
    const streamRenderer = createQaStreamRenderer({
      getRenderedLength: () => pendingItem.answer.length,
      onCommit: (text) => {
        pendingItem.answer += text
        if (options.session) {
          refreshQaSessionHistory(contentItemId, options.session)
        } else {
          qaHistory.value = [...qaHistory.value]
        }
        options.onCommit?.(pendingItem.answer)
      }
    })

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          handleQaStreamBlock(block, contentItemId, streamRenderer.enqueue, streamState, options)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleQaStreamBlock(buffer, contentItemId, streamRenderer.enqueue, streamState, options)
      }
      await streamRenderer.drain()
      if (!streamState.receivedDone) throw new Error('AI 流式响应提前结束，请重试')
      finalizeQaStreamDone(streamState.doneData, pendingItem, contentItemId, options.session)
    } catch (error) {
      streamRenderer.flush()
      throw error
    }
  }

  function handleQaStreamBlock(block, contentItemId, queueDelta, streamState, options = {}) {
    const lines = block.split('\n')
    const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const dataLine = lines.find((line) => line.startsWith('data:'))
    if (!dataLine) return
    const data = JSON.parse(dataLine.slice(5).trim())

    if (event === 'delta') {
      if (!options.receivedFirstDelta) {
        options.receivedFirstDelta = true
        options.onFirstDelta?.()
      }
      queueDelta(data.text || '')
      return
    }
    if (event === 'usage') {
      appendContentAiCall(contentItemId, data)
      return
    }
    if (event === 'log') {
      options.onLog?.(data)
      return
    }
    if (event === 'done') {
      streamState.receivedDone = true
      streamState.doneData = data
      return
    }
    if (event === 'error') {
      throw new Error(data.error || '追问失败')
    }
  }

  function finalizeQaStreamDone(data, pendingItem, contentItemId, session = null) {
    // A response belonging to article A can finish after the user has opened
    // article B. Persisting happened server-side already; only update the
    // visible Markdown pane when it still represents A.
    if (
      data.markdown_state
      && (!contentItemId || String(selectedContentItem.value?.id || '') === String(contentItemId))
    ) {
      applyMarkdownState(data.markdown_state)
    }
    if (typeof data.answer === 'string') pendingItem.answer = data.answer
    if (typeof data.assistant_message_id === 'string' && data.assistant_message_id) {
      pendingItem.id = data.assistant_message_id
    }
    pendingItem.pending = false
    pendingItem.saved = Boolean(data.saved_to_markdown || data.saved_to_obsidian)
    pendingItem.savedToContent = Boolean(data.saved_to_content)
    pendingItem.obsidianError = data.obsidian_error || ''
    if (session) {
      session.lastSaved = pendingItem.saved
      refreshQaSessionHistory(contentItemId, session)
      return
    }
    lastQaSaved.value = pendingItem.saved
    qaHistory.value = [...qaHistory.value]
  }

  return {
    activeView,
    workspaceTabs,
    workspaceLayout,
    shareText,
    parsedUrl,
    running,
    logs,
    processLogEntries,
    taskStatus,
    selectedModel,
    selectedAsrBackend,
    availableAsrBackends,
    miniprogramForumCaptureEnabled,
    asrModelStrategy,
    asrShortVideoModel,
    asrLongVideoModel,
    asrBeamSize,
    asrVadFilter,
    asrFallbackEnabled,
    selectedAiModel,
    assistantAiModel,
    availableAiModels,
    useCache,
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    searchQuery,
    librarySearchScope,
    searchResults,
    libraryFolders,
    libraryFolderHistoryStates,
    libraryFolderRevealIds,
    libraryTrashEntries,
    loadingLibraryTrash,
    allContentItems,
    contentPagesLoading,
    contentPageLoadStatus,
    selectedContentItem,
    startupBlocking,
    startupCanRetry,
    startupStatus,
    retryingContentId,
    showMarkdownDialog,
    currentMarkdownItem,
    savingMarkdown,
    syncingMarkdown,
    exportingConversationMarkdown,
    promptTaskType,
    promptTemplates,
    selectedPromptTemplateId,
    qaShortcutTemplates,
    contentAnalysisTemplates,
    loadingPrompts,
    savingPromptTemplate,
    activatingPromptTemplate,
    promptEditorName,
    promptEditorText,
    batchTasks,
    batchTaskIds,
    questionInput,
    activeSelectedTextContext,
    autoQaShortcutRecognition,
    qaHistory,
    qaHistoryLoading,
    qaHistoryLoadingMore,
    qaHistoryHasMore,
    qaHistoryError,
    viewedContentIds,
    explicitlyUnreadContentIds,
    contentViewedBefore,
    askingQuestion,
    generatingAiSummary,
    generatingSummaryText,
    startingNewChat,
    lastQaSaved,
    clipboardWatching,
    clipboardScanning,
    openclawRunning,
    openclawScanning,
    openclawConnectionItems,
    openclawStatusTone,
    obsidianVaultPath,
    markdownExportPath,
    obsidianAutoWrite,
    cookieConfigured,
    cookieState,
    cookieStatusText,
    cookieChecking,
    cookieInput,
    savingCookie,
    bilibiliCookieConfigured,
    bilibiliCookieState,
    bilibiliCookieStatusText,
    bilibiliCookieInput,
    savingBilibiliCookie,
    platformAuthConnecting,
    platformAuthAvailable,
    showSettings,
    selectedTheme,
    themeOptions,
    selectedThemeOption,
    markdownState,
    result,
    promptTaskOptions,
    ribbonItems,
    selectedMarkdownPreview,
    selectedMarkdownSizeBytes,
    selectedReportSourceStats,
    mediaPreviewUrl,
    sidebarTreeItems,
    activeWorkspaceTab,
    activeWorkspaceContent,
    activeContentAiCalls,
    dailyAiTokenUsage,
    openClawTokenUsage,
    currentInsightHtml,
    currentInsightTitle,
    isPipelineSummaryGenerating,
    pipelineGeneratingSummaryText,
    currentQaEnabled,
    currentQaHint,
    canGenerateAiSummary,
    currentObsidianPath,
    totalElapsed,
    hasTaskProgress,
    activeBatchCount,
    statusbarProgress,
    articlePreparationStatus,
    currentArticleOcrStatus,
    prioritizingArticleOcr,
    openclawStatusText,
    modelProfileOptions,
    currentStageLabel,
    workspaceTabById,
    contentForTab,
    resultForTab,
    statusForTab,
    mediaUrlForTab,
    originalMediaUrlForTab,
    transcriptForTab,
    articlePreviewForTab,
    prioritizeCurrentArticleOcr,
    addLog,
    clearLogs,
    statusLabel,
    statusTagType,
    progressStatus,
    roundedProgress,
    stepLabel,
    modelLabel,
    sourceProviderLabel,
    promptTaskLabel,
    openContentFromSidebar,
    activateWorkspaceTab,
    closeWorkspaceTab,
    closeWorkspaceTabs,
    revealWorkspaceTabLocation,
    deleteWorkspaceTabContent,
    handleWorkspaceResize,
    markdownSyncLabel,
    formatSeconds,
    formatBytes,
    formatDuration,
    formatDateTime,
    renderMarkdown,
    setTaskQueuePollingInterval,
    toggleClipboardWatching,
    loadOpenClawStatus,
    startOpenClawGateway,
    saveObsidianSettingsFromForm,
    setContentViewedState,
    saveCookie,
    saveBilibiliCookie,
    connectPlatformAuth,
    disconnectPlatformAuth,
    loadContentItems,
    revealContentItems,
    retryStartupHydration,
    loadLibraryFolders,
    loadLibraryFolderHistory,
    loadLibraryTrash,
    restoreLibraryTrashEntry,
    permanentlyDeleteLibraryTrashEntry,
    emptyLibraryTrash,
    createLibraryFolder,
    renameLibraryFolder,
    setLibraryFolderPinned,
    deleteLibraryFolder,
    renameContentItem,
    deleteContentItem,
    moveLibraryNode,
    moveLibraryNodes,
    deleteLibraryNodes,
    retryContentSourceText,
    retryContentProcessing,
    reprocessLocalSource,
    retranscribeContentVideo,
    fetchExternalSubtitleForContent,
    refreshContentSourceContext,
    saveVideoDownloadSettings,
    redownloadContentVideo,
    loadMoreContentQaHistory,
    retryContentQaHistory,
    loadContentAiCalls,
    loadAiTokenUsageSummary,
    runContentAnalysis,
    openMarkdownDialog,
    saveMarkdownDraft,
    syncMarkdownDraft,
    loadPromptTemplates,
    loadQaShortcutTemplates,
    loadContentAnalysisTemplates,
    selectPromptTemplate,
    createPromptTemplate,
    savePromptTemplate,
    activatePromptTemplate,
    deletePromptTemplate,
    searchContent,
    batchTaskName,
    pollBatchTasks,
    monitorCreatorSyncTasks,
    cancelBatchTask,
    cancelActiveTasks,
    loadBatchTaskDetails,
    retryBatchTask,
    copyText,
    revealLibraryNodeLocation,
    revealLocalPath,
    openExternalLink,
    startNewChat,
    onInputChange,
    runFullPipeline,
    insertQaShortcut,
    setSelectedTextContext,
    clearSelectedTextContext,
    askQuestion,
    copyQaExchange,
    regenerateQaAnswer,
    exportConversationMarkdown,
    generateAiSummary
  }
}
