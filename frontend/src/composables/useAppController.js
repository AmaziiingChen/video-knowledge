import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
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
import { useContentSelectionController } from '../features/library/useContentSelectionController.js'
import { useCreatorSyncTaskMonitorController } from '../features/creator/useCreatorSyncTaskMonitorController.js'
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
import { useDesktopBootstrapSettingsController } from '../features/settings/useDesktopBootstrapSettingsController.js'
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
import { useTaskRuntimeProjectionController } from '../features/tasks/useTaskRuntimeProjectionController.js'
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
    generatingSummaryReasoning, generatingSummaryReasoningExpanded, suggestedQuestions,
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
  const useCache = ref(true)
  const {
    availableModels,
    miniprogramForumCaptureEnabled,
    availableAiModels,
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    loadDesktopBootstrapSettings,
  } = useDesktopBootstrapSettingsController({
    selectedAiModel,
    normalizeAiModelValue,
    checkManualUpdate,
  })
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
    viewedContentIds,
    explicitlyUnreadContentIds,
    contentViewedBefore,
    reconcileContentViewState,
    scheduleContentViewed,
    setContentViewedState
  } = useContentReadState({
    isCurrentContent: (contentItemId) => String(selectedContentItem.value?.id || '') === contentItemId
  })
  const { selectContentItem } = useContentSelectionController({
    selectedContentItem,
    currentMarkdownItem,
    getContentItemDetail,
    updatePendingArticlePreviewReadiness,
    loadArticlePreview,
    activateQaSession,
    isQaSessionActive,
    loadContentQaHistory,
    scheduleContentViewed,
    loadCurrentArticleOcrStatus,
    loadContentAiCalls,
    loadMarkdownForItem,
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

  const { monitorCreatorSyncTasks } = useCreatorSyncTaskMonitorController({
    allContentItems,
    batchTaskIds,
    batchTaskNames,
    running,
    terminalStatuses,
    loadContentItems,
    openContentTab,
    mergeBatchTasks,
    resetRunState,
    applyTaskData,
    addLog,
    batchTaskName,
    pollTask,
    pollBatchTasks,
    notify: ElMessage,
  })

  const {
    totalElapsed,
    hasTaskProgress,
    activeBatchCount,
    statusbarProgress,
    modelProfileOptions,
    currentStageLabel,
  } = useTaskRuntimeProjectionController({
    result,
    running,
    currentStep,
    taskStatus,
    parsedUrl,
    batchTasks,
    availableModels,
    preferredModelOrder,
    modelProfiles,
    shouldDisplayTask,
    isActiveTask,
    statusbarStageLabel,
    statusbarTransferDetail,
    statusbarTaskContext,
    roundedProgress,
    stepLabel,
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

    await loadDesktopBootstrapSettings({ hasLocalAiSettings })

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
    miniprogramForumCaptureEnabled,
    selectedAiModel,
    assistantAiModel,
    availableAiModels,
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    searchQuery,
    librarySearchScope,
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
    generatingSummaryReasoning, generatingSummaryReasoningExpanded, suggestedQuestions,
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
    askQuestion,
    copyQaExchange,
    regenerateQaAnswer,
    exportConversationMarkdown,
    generateAiSummary
  }
}
