import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElNotification } from 'element-plus'
import { requestDestructiveConfirmation } from './useDestructiveConfirm'
import {
  contentStatusOptions,
  modelProfiles,
  preferredModelOrder,
  promptTaskOptions,
  ribbonItems,
  stages,
  stepNames,
  terminalStatuses
} from '../config/workbenchOptions'
import {
  documentMarkdownWithoutConversation,
  reportMarkdownForCenter,
  sourceMarkdownForCenter,
} from '../features/assistant/assistantMarkdown'
import { createQaResponseStreamController } from '../features/assistant/createQaResponseStreamController.js'
import {
  mergeUniqueContentItems,
  shouldRefreshContentForTask,
  taskContentSnapshot
} from './contentRefreshState'
import { waitForDesktopBackend } from './backendStartupGate.js'
import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../utils/localApiAuth.js'
import {
  cacheHitLabel,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatSeconds,
  markdownSyncLabel,
  renderMarkdown,
  stripReportMarkdownHeader,
  roundedProgress,
  sanitizeHtml,
  sourceProviderLabel,
  statusLabel,
  statusTagType,
} from '../utils/viewFormatters'
import { sourceProviderFromUrl } from '../utils/taskSource.js'
import { useProcessLogController } from '../features/logs/useProcessLogController.js'
import { useProcessLogProjectionController } from '../features/logs/useProcessLogProjectionController.js'
import { useArticlePreviewController } from '../features/library/useArticlePreviewController.js'
import { useOpenClawController } from '../features/integrations/useOpenClawController.js'
import { useQaSessionController } from '../features/assistant/useQaSessionController.js'
import { useSelectedTextContext } from '../features/assistant/useSelectedTextContext.js'
import { useWorkspaceState } from '../features/workspace/useWorkspaceState.js'
import { useWorkspaceTabController } from '../features/workspace/useWorkspaceTabController.js'
import { useWorkspaceTabProjectionController } from '../features/workspace/useWorkspaceTabProjectionController.js'
import { useClipboardController } from '../features/integrations/useClipboardController.js'
import { useContentReadState } from '../features/library/useContentReadState.js'
import { useContentReadinessController } from '../features/library/useContentReadinessController.js'
import { useLibraryContentController } from '../features/library/useLibraryContentController.js'
import { useLibraryFolderController } from '../features/library/useLibraryFolderController.js'
import { useLibrarySearchController } from '../features/library/useLibrarySearchController.js'
import { useLibraryTrashController } from '../features/library/useLibraryTrashController.js'
import { useLibraryMutationController } from '../features/library/useLibraryMutationController.js'
import { useArticlePreparationController } from '../features/library/useArticlePreparationController.js'
import { useContentRecoveryController } from '../features/library/useContentRecoveryController.js'
import { useLinkIngestController } from '../features/imports/useLinkIngestController.js'
import { useLibraryHistoryController } from '../features/library/useLibraryHistoryController.js'
import { useMarkdownOutputSettingsController } from '../features/library/useMarkdownOutputSettingsController.js'
import { useMarkdownDocumentController } from '../features/library/useMarkdownDocumentController.js'
import {
  isGeneratedReportDocument,
  useMarkdownReaderController,
} from '../features/library/useMarkdownReaderController.js'
import { useCookieStatusController } from '../features/integrations/useCookieStatusController.js'
import { usePlatformCredentialController } from '../features/integrations/usePlatformCredentialController.js'
import { useCompletionNotificationController } from '../features/notifications/useCompletionNotificationController.js'
import { useDesktopActionController } from '../features/desktop/useDesktopActionController.js'
import { useAppSettingsController } from '../features/settings/useAppSettingsController.js'
import { useAiUsageController } from '../features/usage/useAiUsageController.js'
import { useContentAnalysisController } from '../features/assistant/useContentAnalysisController.js'
import { useConversationMarkdownExportController } from '../features/assistant/useConversationMarkdownExportController.js'
import { useAiSummaryGenerationController } from '../features/assistant/useAiSummaryGenerationController.js'
import { useAssistantWorkspaceProjectionController } from '../features/assistant/useAssistantWorkspaceProjectionController.js'
import { useQaRequestController } from '../features/assistant/useQaRequestController.js'
import { usePromptTemplateController } from '../features/prompts/usePromptTemplateController.js'
import { useActiveTaskPollingController } from '../features/tasks/useActiveTaskPollingController.js'
import { useProgressiveTaskHydrationController } from '../features/tasks/useProgressiveTaskHydrationController.js'
import { useActiveTaskStateController } from '../features/tasks/useActiveTaskStateController.js'
import { useActiveTaskEventStreamController } from '../features/tasks/useActiveTaskEventStreamController.js'
import { useTaskQueueController } from '../features/tasks/useTaskQueueController.js'
import { createTaskDisplayPresentation } from '../features/tasks/taskDisplayPresentation.js'

export function useAppController() {
  const {
    selectedAiModel,
    assistantAiModel,
    autoQaShortcutRecognition,
    selectedTheme,
    themeOptions,
    selectedThemeOption,
    asrRequestOptions,
    aiRequestOptions,
    normalizeAiModelValue,
    startSettingsPersistence,
    restoreSettings,
  } = useAppSettingsController()
  const {
    copyText,
    openExternalLink,
    revealLibraryNodeLocation,
    revealLocalPath,
    recordTelemetry,
    checkManualUpdate,
  } = useDesktopActionController({ notify: ElMessage })
  const {
    showMarkdownDialog,
    currentMarkdownItem,
    loadingMarkdown,
    savingMarkdown,
    syncingMarkdown,
    markdownState,
    applyMarkdownState,
    resetMarkdownState,
    loadMarkdownForItem,
    openMarkdownDialog,
    saveMarkdownDraft,
    syncMarkdownDraft,
  } = useMarkdownDocumentController({
    notify: ElMessage,
    setSelectedContentItem: (item) => {
      selectedContentItem.value = item
    },
    isSelectedContentItem: (itemId) => (
      String(selectedContentItem.value?.id || '') === String(itemId || '')
    ),
  })
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
    resetActiveQaSession: resetQaState,
    insertQaShortcut,
    resolveQaQuestion,
    startNewChat,
    loadContentQaHistory,
    loadMoreContentQaHistory,
    retryContentQaHistory,
  } = useQaSessionController({
    getActiveContentId: () => activeWorkspaceContent.value?.id || result.content_item_id || null,
    getQaShortcutTemplates: () => qaShortcutTemplates.value,
    isAutoQaShortcutRecognitionEnabled: () => autoQaShortcutRecognition.value,
  })
  const activeView = ref('library')
  const {
    aiCallsByContentId,
    dailyAiTokenUsage,
    openClawTokenUsage,
    loadContentAiCalls,
    loadAiTokenUsageSummary,
    appendContentAiCall,
    startAiTokenUsagePolling,
    stopAiTokenUsagePolling,
  } = useAiUsageController()
  const { readQaStream } = createQaResponseStreamController({
    appendContentAiCall,
    getSelectedContentItem: () => selectedContentItem.value,
    applyMarkdownState,
    refreshQaSessionHistory,
    refreshFallbackHistory: () => {
      qaHistory.value = [...qaHistory.value]
    },
    setLastQaSaved: (saved) => {
      lastQaSaved.value = saved
    },
  })
  const {
    promptTaskType,
    promptTemplates,
    selectedPromptTemplateId,
    qaShortcutTemplates,
    loadingPrompts,
    savingPromptTemplate,
    activatingPromptTemplate,
    promptEditorName,
    promptEditorText,
    sortPromptTemplates,
    loadPromptTemplates,
    loadQaShortcutTemplates,
    selectPromptTemplate,
    createPromptTemplate,
    savePromptTemplate,
    activatePromptTemplate,
    deletePromptTemplate,
  } = usePromptTemplateController({
    confirmDelete: requestDestructiveConfirmation,
    refreshContentAnalysisTemplates: () => loadContentAnalysisTemplates(),
  })
  const {
    contentAnalysisTemplates,
    loadContentAnalysisTemplates,
    runContentAnalysis,
  } = useContentAnalysisController({
    sortTemplates: sortPromptTemplates,
    askQuestion: (...args) => askQuestion(...args),
  })
  const openSections = ref(['source', 'timings'])
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
  const availableAiModels = ref([
    { value: 'deepseek-v4-flash:enabled', label: 'deepseek-v4-flash' },
    { value: 'deepseek-v4-pro:enabled', label: 'deepseek-v4-pro' }
  ])
  const useCache = ref(true)
  const autoDownloadBilibiliVideo = ref(false)
  const douyinVideoQuality = ref('standard')
  const libraryFolders = ref([])
  const selectedContentItem = ref(null)
  const {
    libraryFolderHistoryStates,
    libraryFolderRevealIds,
    contentItems,
    allContentItems,
    contentPageLoadStatus,
    startupBlocking,
    startupCanRetry,
    startupStatus,
    loadContentItems,
    retryStartupHydration,
    revealContentItems,
    expandLibraryFolders,
    loadLibraryFolderHistory,
    applyContentFilter,
    updateLocalContentItem,
    dispose: disposeLibraryContentController,
  } = useLibraryContentController({
    selectedContentItem,
    mergeContentItems: mergeUniqueContentItems,
    reconcileContentViewState: (...args) => reconcileContentViewState(...args),
    loadLibraryFolders: (...args) => loadLibraryFolders(...args),
    syncActiveWorkspaceTabSelection: (...args) => syncActiveWorkspaceTabSelection(...args),
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
    deleteLibraryFolder,
    renameContentItem,
    deleteContentItem,
    deleteLibraryNodes,
    moveLibraryNode,
    moveLibraryNodes,
    nextSortOrder,
  } = useLibraryMutationController({
    libraryFolders,
    allContentItems,
    workspaceTabs,
    activeWorkspaceTabId,
    selectedContentItem,
    snapshotLibraryState,
    restoreLibraryState,
    recordLibraryHistory,
    discardLibraryHistoryForNodes,
    resetMarkdownState,
    applyContentFilter,
    updateLocalContentItem,
    loadLibraryTrash: (...args) => loadLibraryTrash(...args),
    showTrashUndoMessage: (...args) => showTrashUndoMessage(...args),
  })
  const {
    loadLibraryFolders,
    createLibraryFolder,
    renameLibraryFolder,
    setLibraryFolderPinned,
  } = useLibraryFolderController({
    libraryFolders,
    snapshotLibraryState,
    restoreLibraryState,
    nextSortOrder,
    recordLibraryHistory,
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
    openContentTab,
    activateWorkspaceTab,
    closeWorkspaceTab,
    closeWorkspaceTabs,
    revealWorkspaceTabLocation,
    deleteWorkspaceTabContent,
    syncActiveWorkspaceTabSelection,
    syncCompletedTaskContent,
    syncTaskTabMetadata,
  } = useWorkspaceTabController({
    workspaceTabs,
    activeWorkspaceTabId,
    activeView,
    allContentItems,
    selectedContentItem,
    getContentItemDetail,
    selectContentItem,
    resetMarkdownState,
    detachQaSession,
    revealLibraryNodeLocation,
    deleteContentItem,
    notify: ElMessage,
  })
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
  const batchTasks = ref([])
  const batchTaskIds = ref([])
  const batchTaskNames = ref({})
  const progressiveTaskSnapshots = new Map()
  const {
    logs,
    logContainer,
    backendLogCount,
    logClearedAt,
    addLog,
    addBackendLogs,
    clearBackendLogCounts,
    clearLogs,
  } = useProcessLogController({
    batchTasks,
    batchTaskIds,
    getResult: () => result,
    getTaskStatus: () => taskStatus.value,
    isActiveTask: (task) => isActiveTask(task),
    logTypeFromMessage: (message) => logTypeFromMessage(message),
    resetTaskQueueCursor: (...args) => resetTaskQueueCursor(...args),
  })
  const {
    running,
    cancelling,
    activeStep,
    currentStep,
    taskStatus,
    taskCancelRequested,
    result,
    resetRunState,
    applyTaskData,
  } = useActiveTaskStateController({
    logs,
    backendLogCount,
    openSections,
    stopPolling: () => stopPolling(),
    clearBackendLogCounts,
    resetQaState,
    addBackendLogs: (...args) => addBackendLogs(...args),
    addLog: (...args) => addLog(...args),
  })
  const {
    shareText,
    parsedUrl,
    onInputChange,
    runFullPipeline,
    dispose: disposeLinkIngestController,
  } = useLinkIngestController({
    result,
    activeStep,
    running,
    openSections,
    useCache,
    resetRunState,
    applyTaskData,
    addLog: (...args) => addLog(...args),
    addBackendLogs: (...args) => addBackendLogs(...args),
    recordTelemetry: (...args) => recordTelemetry(...args),
    registerBatchTask: (...args) => registerBatchTask(...args),
    hydrateProgressiveTask: (...args) => hydrateProgressiveTask(...args),
    getProgressiveSnapshot: (taskId) => progressiveTaskSnapshots.get(taskId),
    pollTask: (...args) => pollTask(...args),
    getAsrRequestOptions: asrRequestOptions,
    getAiRequestOptions: aiRequestOptions,
    notify: ElMessage,
  })
  const {
    formatProcessLogTime,
    isActiveTask,
    logTypeFromMessage,
    modelLabel,
    progressStatus,
    promptTaskLabel,
    shouldDisplayTask,
    stageProgress,
    statusbarStageLabel,
    statusbarTaskContext,
    statusbarTransferDetail,
    stepLabel,
  } = createTaskDisplayPresentation({
    getTaskStatus: () => taskStatus.value,
    getCurrentStep: () => currentStep.value,
    getResult: () => result,
    getParsedUrl: () => parsedUrl.value,
    getTaskNames: () => batchTaskNames.value,
    getLogClearedAt: () => logClearedAt.value,
    sourceProviderFromUrl,
    sourceProviderLabel,
    formatBytes,
    roundedProgress,
    stepNames,
    modelProfiles,
    promptTaskOptions,
  })
  const {
    mergeBatchTasks,
    batchTaskName,
    registerBatchTask,
    stopBatchPolling,
    startTaskQueuePolling,
    stopTaskQueuePolling,
    setTaskQueuePollingInterval,
    resetTaskQueueCursor,
    loadTaskQueue,
    pollBatchTasks,
    cancelBatchTask,
    cancelActiveTasks,
    loadBatchTaskDetails,
    retryBatchTask,
  } = useTaskQueueController({
    batchTasks,
    batchTaskIds,
    batchTaskNames,
    progressiveTaskSnapshots,
    terminalStatuses,
    shouldDisplayTask,
    isActiveTask,
    shouldRefreshContentForTask,
    taskContentSnapshot,
    hydrateProgressiveTask: (...args) => hydrateProgressiveTask(...args),
    loadContentItems,
    isActiveContentTask: (task) => activeWorkspaceTab.value?.content_item_id === task.content_item_id,
    shouldContinueBatchPolling: () => activeBatchCount.value > 0,
    getActiveTaskId: () => result.task_id,
    applyTaskData,
    notify: ElMessage,
    initialUpdatedAfter: logClearedAt.value
      ? new Date(logClearedAt.value).toISOString()
      : '',
  })
  const {
    hydrateProgressiveTask,
    revealWechatArticleSnapshot,
    revealVideoSnapshot,
    revealTranscriptSnapshot,
  } = useProgressiveTaskHydrationController({
    progressiveTaskSnapshots,
    getContentItemDetail,
    syncTaskTabMetadata,
    getActiveContentItemId: () => activeWorkspaceTab.value?.content_item_id || null,
    setSelectedContentItem: (content) => {
      selectedContentItem.value = content
    },
    setCurrentMarkdownItem: (content) => {
      currentMarkdownItem.value = content
    },
    updatePendingArticlePreviewReadiness,
    articlePreviews,
    loadArticlePreview,
    mergeBatchTasks,
    addBackendLogs,
    getActiveResultContentItemId: () => result.content_item_id || null,
    applyTaskData,
  })
  const {
    startTaskEventStream,
    stopTaskEventStream,
    syncTaskEventStream,
  } = useActiveTaskEventStreamController({
    apiBase: API,
    eventSourceFactory: typeof EventSource === 'undefined' ? null : (url) => new EventSource(url),
    mergeBatchTasks,
    applyTaskData,
    hydrateProgressiveTask,
    progressiveTaskSnapshots,
    terminalStatuses,
    isActiveTask,
  })
  const {
    stopPolling,
    pollTask,
  } = useActiveTaskPollingController({
    running,
    cancelling,
    openSections,
    progressiveTaskSnapshots,
    terminalStatuses,
    applyTaskData,
    startTaskEventStream,
    stopTaskEventStream,
    hydrateProgressiveTask: (...args) => hydrateProgressiveTask(...args),
    revealWechatArticleSnapshot: (...args) => revealWechatArticleSnapshot(...args),
    revealVideoSnapshot: (...args) => revealVideoSnapshot(...args),
    revealTranscriptSnapshot: (...args) => revealTranscriptSnapshot(...args),
    syncCompletedTaskContent,
    addLog: (...args) => addLog(...args),
    isPipelineSummaryGenerating: () => isPipelineSummaryGenerating.value,
    notify: ElMessage,
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
    registerBatchTask,
    loadContentItems,
    pollTask,
    pollBatchTasks,
    getContentItemDetail,
    notify: ElMessage,
  })
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
  const {
    obsidianVaultPath,
    markdownExportPath,
    obsidianAutoWrite,
    loadObsidianSettings,
    saveObsidianSettingsFromForm,
  } = useMarkdownOutputSettingsController({ notify: ElMessage })
  const showSettings = ref(false)
  const {
    cookieInput,
    savingCookie,
    bilibiliCookieInput,
    savingBilibiliCookie,
    platformAuthConnecting,
    platformAuthAvailable,
    saveCookie,
    saveBilibiliCookie,
    connectPlatformAuth,
    disconnectPlatformAuth,
  } = usePlatformCredentialController({
    showSettings,
    cookieConfigured,
    cookieState,
    loadCookieStatus,
    loadBilibiliCookieStatus,
    notify: ElMessage,
    confirmDisconnect: requestDestructiveConfirmation,
  })
  const {
    selectedMarkdownPreview,
    selectedMarkdownSizeBytes,
    selectedReportSourceStats,
    selectedMarkdownSourceText,
  } = useMarkdownReaderController({
    selectedContentItem,
    markdownState,
    render: renderMarkdown,
    stripReportHeader: stripReportMarkdownHeader,
    documentWithoutConversation: documentMarkdownWithoutConversation,
    reportForCenter: reportMarkdownForCenter,
    sourceForCenter: sourceMarkdownForCenter,
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

  const {
    workspaceTabById,
    contentForTab,
    resultForTab,
    statusForTab,
    mediaUrlForTab,
    originalMediaUrlForTab,
    transcriptForTab,
    articlePreviewForTab,
    activeWorkspaceTab,
    activeWorkspaceContent,
    activeWorkspaceResult,
    activeWorkspaceTranscript,
  } = useWorkspaceTabProjectionController({
    workspaceTabs,
    activeWorkspaceTabId,
    allContentItems,
    selectedContentItem,
    batchTasks,
    result,
    selectedMarkdownSourceText,
    articlePreviews,
    isActiveTask,
    localApiRequestUrl,
    apiBase: API,
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

  const {
    activeContentAiCalls,
    currentInsightHtml,
    currentInsightTitle,
    isPipelineSummaryGenerating,
    pipelineGeneratingSummaryText,
    currentQaEnabled,
    currentQaHint,
    activeRegenerableContent,
    canGenerateAiSummary,
    currentObsidianPath,
    currentSummaryText,
  } = useAssistantWorkspaceProjectionController({
    activeWorkspaceTab,
    activeWorkspaceContent,
    activeWorkspaceResult,
    activeWorkspaceTranscript,
    selectedContentItem,
    markdownState,
    result,
    aiCallsByContentId,
    renderMarkdown,
    isGeneratedReportDocument,
  })

  const { askQuestion, regenerateQaAnswer } = useQaRequestController({
    ensureQaSession,
    syncQaSessionIfActive,
    refreshQaSessionHistory,
    resolveQaQuestion,
    removeSelectedTextContextToken,
    readQaStream,
    getRequestContext: () => ({
      contentItemId: activeWorkspaceContent.value?.id || result.content_item_id || null,
      selectionContext: activeSelectedTextContext.value,
      summary: currentSummaryText.value,
      transcript: activeWorkspaceTranscript.value || result.transcript || '',
      videoTitle: activeWorkspaceContent.value?.title || result.source_title || '',
      sourceUrl: activeWorkspaceContent.value?.source_url || result.url || '',
      obsidianAutoWrite: obsidianAutoWrite.value,
      obsidianPath: currentObsidianPath.value,
      aiModel: assistantAiModel.value,
    }),
    getActiveContentId: () => activeWorkspaceContent.value?.id || null,
    isStartingNewChat: () => startingNewChat.value,
    loadCompletionNotifications,
  })

  const { generateAiSummary } = useAiSummaryGenerationController({
    ensureQaSession,
    syncQaSessionIfActive,
    refreshQaSessionHistory,
    readQaStream,
    addLog,
    getActiveItem: () => activeRegenerableContent.value,
    getCurrentSummary: () => currentSummaryText.value,
    getAiModel: () => assistantAiModel.value,
    getLogs: () => logs.value,
    isStartingNewChat: () => startingNewChat.value,
  })

  const {
    exportingConversationMarkdown,
    exportConversationMarkdown,
  } = useConversationMarkdownExportController({
    getConversation: () => ({
      content: activeWorkspaceContent.value,
      fallbackTitle: result.source_title,
      fallbackSourceUrl: result.url,
      summary: currentSummaryText.value,
      history: qaHistory.value,
    }),
    recordTelemetry,
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

  const { processLogEntries } = useProcessLogProjectionController({
    logs,
    logClearedAt,
    result,
    statusbarProgress,
    batchTasks,
    batchTaskName,
    formatProcessLogTime,
    logTypeFromMessage,
  })

  const modelProfileOptions = computed(() => {
    return preferredModelOrder
      .filter((model) => availableModels.value.includes(model))
      .map((model) => modelProfiles.find((profile) => profile.model === model))
      .filter(Boolean)
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

  function openContentFromSidebar(item) {
    openContentTab(item)
  }

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

  watch(
    () => [
      activeWorkspaceContent.value?.id || '',
      batchTasks.value.map((task) => `${task.task_id}:${task.content_item_id || ''}:${task.status || ''}`).join('|'),
    ],
    () => syncTaskEventStream({
      activeContentItemId: activeWorkspaceContent.value?.id,
      batchTasks: batchTasks.value,
    }),
    { flush: 'post' }
  )
  startSettingsPersistence()
  onMounted(async () => {
    const { hasLocalAiSettings } = restoreSettings()

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
    startAiTokenUsagePolling()
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
    disposeLinkIngestController()
    stopAiTokenUsagePolling()
    cancelDeferredCookieProbe()
    disposeLibraryContentController()
    window.removeEventListener('keydown', handleLibraryHistoryShortcut)
    disposeLibrarySearchController()
  })

  function shortLink(link) {
    return link.replace(/^https?:\/\//, '').replace(/^www\./, '').slice(0, 42)
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
    await loadMarkdownForItem(item)
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
