<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-workspace">跳到主内容</a>
    <header v-if="isSinglePaneWorkspaceView(activeView)" class="topbar is-single-pane-topbar">
      <div class="brand">
        <div class="brand-mark">KH</div>
        <h1>KnowledgeHub</h1>
      </div>

      <div class="topbar-actions">
        <WorkspaceChromeActions
          class="single-pane-chrome-actions"
          v-bind="workspaceChromeActionProps"
          @start-openclaw="startOpenClawGateway"
          @toggle-clipboard="toggleClipboardWatching"
          @toggle-context="contextSidebarOpen = !contextSidebarOpen"
          @toggle-process-log="processLogOpen = !processLogOpen"
        />
      </div>
    </header>

    <main id="main-workspace" class="workspace" tabindex="-1" :aria-busy="startupBlocking">
      <WorkbenchShell
          ref="workbenchShell"
          v-model:active-view="activeView"
          :ribbon-items="ribbonItems"
          :workspace-layout="workspaceLayout"
          :editor-pane-size="editorPaneSize"
          :show-primary-pane="showPrimaryPane"
          :show-context-pane="showContextPane"
          :primary-pane-transitioning="primaryPaneTransitioning"
          :integrated-chrome="!isSinglePaneWorkspaceView(activeView)"
          @open-settings="openSettings"
          @resized="handleWorkspaceResize"
          @snap-collapse="handlePaneSnapCollapse"
          @snap-open="handlePaneSnapOpen"
          @pane-drag-resize="handlePaneDragResize"
          @pane-visibility-transition-end="handlePaneVisibilityTransitionEnd"
        >
          <template #primary-header>
            <div v-if="!primaryPaneTransitioning" class="workspace-primary-controls" aria-label="左侧栏工具">
              <el-tooltip v-if="activeView === 'library'" content="文件管理" placement="bottom">
                <button
                  class="topbar-icon-button topbar-left-mode-button"
                  type="button"
                  :class="{ 'is-on': librarySidebarMode === 'files' }"
                  aria-label="打开文件管理"
                  @click="showLibraryFiles"
                >
                  <SvgMaskIcon :src="folderIcon" :size="17" />
                </button>
              </el-tooltip>
              <el-tooltip v-if="activeView === 'library'" content="搜索资料" placement="bottom">
                <button
                  class="topbar-icon-button topbar-left-mode-button"
                  type="button"
                  :class="{ 'is-on': librarySidebarMode === 'search' }"
                  aria-label="搜索资料"
                  @click="focusLibrarySearch"
                >
                  <SvgMaskIcon :src="magnifyingglassIcon" :size="16" />
                </button>
              </el-tooltip>
              <el-tooltip :content="primarySidebarOpen ? '隐藏左侧栏' : '显示左侧栏'" placement="bottom">
                <button
                  class="topbar-icon-button layout-toggle-button workspace-primary-collapse"
                  type="button"
                  :class="{ 'is-on': primarySidebarOpen, 'is-off': !primarySidebarOpen }"
                  aria-label="展开或折叠左侧栏"
                  :aria-pressed="primarySidebarOpen"
                  @click="setPrimarySidebarOpen(!primarySidebarOpen, $event)"
                >
                  <PanelToggleIcon side="left" :collapsed="!primarySidebarOpen" />
                </button>
              </el-tooltip>
            </div>
          </template>

          <template #editor-header>
            <div
              class="workspace-editor-header-content"
              :class="{
                'is-primary-collapsed': !showPrimaryPane,
                'is-context-collapsed': !showContextPane,
              }"
            >
              <div v-if="!showPrimaryPane && !primaryPaneTransitioning" class="workspace-primary-controls is-collapsed" aria-label="左侧栏工具">
                <el-tooltip content="显示左侧栏" placement="bottom">
                  <button
                    class="topbar-icon-button layout-toggle-button workspace-primary-collapse"
                    type="button"
                    aria-label="显示左侧栏"
                    :aria-pressed="false"
                    @click="setPrimarySidebarOpen(true, $event)"
                  >
                    <PanelToggleIcon side="left" :collapsed="true" />
                  </button>
                </el-tooltip>
              </div>
              <WorkspaceTabs
                v-if="activeView === 'library' && workspaceTabs.length"
                :tabs="workspaceTabs"
                :active-tab-id="activeWorkspaceTab?.id || ''"
                allow-reveal
                allow-delete
                @activate="activateWorkspaceTab"
                @close="closeWorkspaceTab"
                @close-tabs="closeWorkspaceTabs"
                @reveal-tab="revealWorkspaceTabLocation"
                @delete-tab="deleteWorkspaceTabContent"
              />
              <WorkspaceTabs
                v-else-if="activeView === 'prompts' && promptWorkspaceTabs.length"
                :tabs="promptWorkspaceTabs"
                :active-tab-id="activePromptTabId"
                @activate="activatePromptWorkspaceTab"
                @close="closePromptWorkspaceTab"
                @close-tabs="closePromptWorkspaceTabs"
              />
            </div>
          </template>

          <template #global-header-actions>
            <WorkspaceChromeActions
              v-bind="workspaceChromeActionProps"
              @start-openclaw="startOpenClawGateway"
              @toggle-clipboard="toggleClipboardWatching"
              @toggle-context="contextSidebarOpen = !contextSidebarOpen"
              @toggle-process-log="processLogOpen = !processLogOpen"
            />
          </template>

          <template #primary>
          <KnowledgeSidebar
            v-if="activeView === 'knowledge'"
            ref="knowledgeSidebar"
            :active-conversation-id="activeKnowledgeConversationId"
            :selected-sources="knowledgeWorkspace?.selectedSources || []"
            @open-conversation="knowledgeWorkspace?.openConversation($event)"
            @select-scope="knowledgeWorkspace?.setKnowledgeScope($event)"
          />
          <PrimarySidebar
            v-else
            ref="primarySidebar"
            v-memo="[
              activeView,
              librarySidebarMode,
              searchQuery,
              librarySearchScope,
              shareText,
              running,
              result.task_id,
              promptTaskType,
              sidebarTreeItems,
              allContentItems,
              viewedContentIds,
              explicitlyUnreadContentIds,
              contentViewedBefore,
              libraryFolders,
              libraryFolderHistoryStates,
              libraryFolderRevealIds,
              libraryTrashEntries,
              loadingLibraryTrash,
              selectedContentItem?.id,
              promptTaskOptions,
              promptWorkspaceTemplates,
              promptFolders,
              promptWorkspaceTabs,
              activePromptTabId,
              promptTrashEntries,
              loadingPromptTrash,
              wechatReportPrompts,
              systemPromptEntries,
              promptContextEntries,
              contentPageLoadStatus.state,
              contentPageLoadStatus.loaded,
              contentPageLoadStatus.total,
            ]"
            v-model:search-query="searchQuery"
            v-model:share-text="shareText"
            :active-view="activeView"
            :library-mode="librarySidebarMode"
            :search-scope="librarySearchScope"
            :sidebar-tree-items="sidebarTreeItems"
            :library-content-items="allContentItems"
            :library-content-load-status="contentPageLoadStatus"
            :viewed-content-ids="viewedContentIds"
            :explicitly-unread-content-ids="explicitlyUnreadContentIds"
            :content-viewed-before="contentViewedBefore"
            :library-folders="libraryFolders"
            :folder-history-states="libraryFolderHistoryStates"
            :revealed-library-folder-ids="libraryFolderRevealIds"
            :trash-entries="libraryTrashEntries"
            :loading-trash="loadingLibraryTrash"
            :selected-content-item="selectedContentItem"
            :running="running"
            :result="result"
            :prompt-task-options="promptTaskOptions"
            :prompt-templates="promptWorkspaceTemplates"
            :prompt-folders="promptFolders"
            :wechat-report-prompts="wechatReportPrompts"
            :system-prompts="systemPromptEntries"
            :prompt-contexts="promptContextEntries"
            :active-prompt-node-id="activePromptNodeId"
            :prompt-trash-entries="promptTrashEntries"
            :loading-prompt-trash="loadingPromptTrash"
            @search="searchContent"
            @update:search-scope="librarySearchScope = $event"
            @clear-search="searchQuery = ''"
            @input-change="onInputChange"
            @run-full-pipeline="runFullPipeline"
            @open-content="openContentFromSidebar"
            @create-folder="createLibraryFolder"
            @rename-folder="renameLibraryFolder"
            @set-folder-pinned="setLibraryFolderPinned"
            @delete-folder="deleteLibraryFolder"
            @rename-content="renameContentItem"
            @delete-content="deleteContentItem"
            @move-node="moveLibraryNode"
            @move-nodes="moveLibraryNodes"
            @delete-selected="deleteLibraryNodes"
            @set-content-viewed="({ contentItemIds, viewed }) => setContentViewedState(contentItemIds, viewed)"
            @reveal-library-node="revealLibraryNodeLocation"
            @import-markdown="importLocalMarkdown"
            @load-folder-history="loadLibraryFolderHistory"
            @retry-content-pages="loadContentItems"
            @load-trash="loadLibraryTrash"
            @restore-trash="restoreLibraryTrashEntry"
            @permanently-delete-trash="permanentlyDeleteLibraryTrashEntry"
            @empty-trash="emptyLibraryTrash"
            @open-prompt="openPromptWorkspaceFile"
            @open-system-prompt="openSystemPromptWorkspaceFile"
            @open-prompt-context="openPromptContextWorkspaceFile"
            @create-prompt-folder="createPromptWorkspaceFolder"
            @create-prompt-file="createPromptWorkspaceFile"
            @rename-prompt-folder="renamePromptWorkspaceFolder"
            @rename-prompt-file="renamePromptWorkspaceFile"
            @rename-report-prompt-file="renameReportPromptWorkspaceFile"
            @delete-prompt-folder="deletePromptWorkspaceFolder"
            @delete-prompt-file="deletePromptWorkspaceFile"
            @move-prompt-node="movePromptWorkspaceNode"
            @load-prompt-trash="loadPromptTrash"
            @restore-prompt-trash="restorePromptTrashEntry"
            @permanently-delete-prompt-trash="permanentlyDeletePromptTrashEntry"
          />
          </template>

          <template #editor>
          <div class="workspace-editor-stack">
          <div class="workspace-editor-main">
          <KeepAlive>
            <CreatorWorkspace
              v-if="activeView === 'creator'"
              @library-changed="loadContentItems"
              @processing-started="handleCreatorProcessingStarted"
            />
          </KeepAlive>
          <WeChatManager
            v-if="activeView === 'wechat'"
            v-model:selected-account-id="selectedWeChatAccountId"
            v-model:search-query="wechatSearchQuery"
            :loading="loadingWeChatSubscriptions"
            :accounts="wechatAccounts"
            :subscriptions="wechatSubscriptions"
            :search-results="wechatSearchResults"
            :searching="wechatSearching"
            :interval-options="wechatSyncIntervalOptions"
            :subscription-states="wechatSubscriptionStates"
            :syncing-subscription-id="syncingWeChatSubscriptionId"
            :bulk-sync-state="wechatBulkSyncState"
            :refreshing-profile-id="refreshingWeChatProfileId"
            :report-groups="wechatReportGroups"
            :auto-sync-summary="wechatAutoSyncSummary"
            :last-sync-summary="wechatLastSyncSummary"
            @refresh="loadWeChatSubscriptions"
            @search="searchWeChatAccounts"
            @subscribe="subscribeWeChatAccount"
            @update-subscription="updateWeChatSubscription"
            @bulk-add-group="bulkAddWeChatSubscriptionGroup"
            @bulk-update-subscriptions="bulkUpdateWeChatSubscriptions"
            @sync-subscription="syncWeChatSubscription"
            @sync-all="syncAllWeChatSubscriptions"
            @refresh-profile="refreshWeChatSubscriptionProfile"
            @delete-subscription="deleteWeChatSubscription"
            @copy-rss="copyWeChatRss"
            @clear-search-results="clearWeChatSearchResults"
            @library-changed="loadContentItems"
          />
          <CampusManager
            v-else-if="activeView === 'campus'"
            :campus-access="campusAccess"
            :campus-connecting="campusConnecting"
            :campus-syncing="campusSyncing"
            :bulk-syncing="campusBulkSyncing"
            :sources="campusSources"
            :loading-sources="campusSourcesLoading"
            :syncing-source="campusSyncingSource"
            :syncing-sources="campusSyncingSources"
            :report-groups="wechatReportGroups"
            :forum-capture-enabled="miniprogramForumCaptureEnabled"
            @load-access="loadCampusAccessStatus"
            @connect-campus="connectCampusWebVpn"
            @disconnect-campus="disconnectCampusWebVpn"
            @refresh-sources="loadCampusSources"
            @sync-source="syncCampusSource"
            @sync-history="syncCampusHistory"
            @sync-all="syncAllCampusSources"
            @update-source="updateCampusSource"
            @library-changed="loadContentItems"
          />
          <RssWorkspace
            v-else-if="activeView === 'rss'"
            :report-groups="wechatReportGroups"
            @library-changed="refreshLibraryAfterRssChange"
          />
          <ReportsWorkspace
            v-else-if="activeView === 'reports'"
            :report-groups="wechatReportGroups"
            :generating-group-id="wechatGeneratingGroupId"
            :preparing-group-id="wechatPreparingGroupId"
            :deleting-group-id="wechatDeletingGroupId"
            :saving-schedule-group-id="wechatSavingScheduleGroupId"
            @create-report-group="createWeChatReportGroup"
            @delete-report-group="deleteWeChatReportGroup"
            @generate-report="generateWeChatReport"
            @open-report="openGeneratedReport"
            @open-sources="openReportSources"
            @edit-sources="openSourceGroupEditor"
            @save-report-schedule="saveWeChatReportSchedule"
          />
          <KnowledgeWorkspace
            v-else-if="activeView === 'knowledge'"
            ref="knowledgeWorkspace"
            @conversation-activated="activeKnowledgeConversationId = $event"
            @conversation-saved="knowledgeSidebar?.refreshConversations()"
            @conversation-usage-changed="knowledgeConversationUsage = $event"
            @navigation-changed="knowledgeSidebar?.refresh()"
            @open-evidence="openKnowledgeEvidence"
            @export-markdown="exportKnowledgeConversationMarkdown"
          />
          <EditorHost
            v-else
            ref="editorHost"
            :prompt-task-type="promptTaskType"
            v-model:prompt-editor-text="promptEditorText"
            :prompt-editor-name="promptEditorName"
            :active-view="activeView"
            :workspace-tabs="workspaceTabs"
            :active-workspace-tab="activeWorkspaceTab"
            :selected-content-item="selectedContentItem"
            :selected-markdown-preview="selectedMarkdownPreview"
            :selected-markdown-size-bytes="selectedMarkdownSizeBytes"
            :selected-markdown-path="markdownState.markdown_draft_path"
            :selected-report-source-stats="selectedReportSourceStats"
            :prompt-templates="promptTemplates"
            :prompt-workspace-tabs="promptWorkspaceTabs"
            :active-prompt-tab-id="activePromptTabId"
            :selected-prompt-template-id="selectedPromptTemplateId"
            :loading-prompts="loadingPrompts"
            :saving-prompt-template="savingPromptTemplate"
            :activating-prompt-template="activatingPromptTemplate"
            :wechat-report-prompts="wechatReportPrompts"
            :selected-wechat-report-prompt-group-id="selectedWechatReportPromptGroupId"
            :selected-wechat-report-prompt-type="selectedWechatReportPromptType"
            :wechat-report-prompt-text="wechatReportPromptText"
            :loading-wechat-report-prompts="loadingWechatReportPrompts"
            :saving-wechat-report-prompt="savingWechatReportPrompt"
            :workspace-tab-by-id="workspaceTabById"
            :content-for-tab="contentForTab"
            :result-for-tab="resultForTab"
            :media-url-for-tab="mediaUrlForTab"
            :original-media-url-for-tab="originalMediaUrlForTab"
            :transcript-for-tab="transcriptForTab"
            :article-preview-for-tab="articlePreviewForTab"
            :source-provider-label="sourceProviderLabel"
            :format-duration="formatDuration"
            :format-date-time="formatDateTime"
            :format-bytes="formatBytes"
            :retrying-content-id="retryingContentId"
            :wechat-publishing-configured="wechatPublishingSettings.configured"
            :wechat-cover-generating-content-ids="wechatCoverGeneratingContentIds"
            :wechat-cover-switching-content-ids="wechatCoverSwitchingContentIds"
            :wechat-cover-history-for-content="wechatCoverHistoryForContent"
            @save-prompt="savePromptWorkspaceCurrent"
            @reset-prompt="resetPromptWorkspaceCurrent"
            @activate-prompt-template="activatePromptWorkspaceTemplate"
            @update:wechat-report-prompt-text="wechatReportPromptText = $event"
            @save-wechat-report-prompt="savePromptWorkspaceCurrent"
            @copy-text="copyText"
            @open-external-link="openExternalLink"
            @retry-source-text="retryContentSourceText"
            @open-campus-attachment="openCampusAttachment"
            @retry-content-processing="retryContentProcessing"
            @reprocess-local-source="reprocessLocalSource"
            @open-original-file="openOriginalFile"
            @reveal-path="revealLocalPath"
            @retranscribe-video="retranscribeContentVideo"
            @fetch-external-subtitle="fetchExternalSubtitleForContent"
            @refresh-source-context="refreshContentSourceContext"
            @redownload-video="redownloadContentVideo"
            @ask-about-selection="askAboutSelection"
            @generate-wechat-cover="openWechatCoverPlan"
            @regenerate-wechat-cover="regenerateWechatReportCover"
            @replan-wechat-cover="openWechatCoverPlan"
            @select-wechat-cover="selectWechatReportCover"
            @create-wechat-draft="openWechatDraftDialog"
            @delete-content="deleteContentItem"
          />
          </div>
          <ProcessLogDock
            :collapsed="!processLogOpen"
            :height="processLogHeight"
            :logs="processLogEntries"
            :result="result"
            :batch-tasks="batchTasks"
            :active-batch-count="activeBatchCount"
            :statusbar-progress="statusbarProgress"
            :current-stage-label="currentStageLabel"
            :rounded-progress="roundedProgress"
            :status-label="statusLabel"
            :step-label="stepLabel"
            :batch-task-name="batchTaskName"
            :format-seconds="formatSeconds"
            :format-token-count="formatTokenCount"
            @update:height="processLogHeight = $event"
            @clear="clearLogs"
            @copy="copyText($event, '日志已复制')"
            @cancel-task="cancelBatchTask"
            @cancel-active-tasks="cancelActiveTasks"
            @retry-task="retryBatchTask"
            @load-task-details="loadBatchTaskDetails"
            @reconnect-douyin-and-retry="reconnectDouyinAndRetryTask"
            @collapse="processLogOpen = false"
            @expand="processLogOpen = true"
          />
          </div>
          </template>

          <template #context>
          <EvidencePreviewSidebar
            v-if="activeView === 'knowledge' && knowledgeEvidence"
            :evidence="knowledgeEvidence"
            @close="knowledgeEvidence = null"
          />
          <SecondarySidebar
            v-else
            v-model:question-input="questionInput"
            :selected-text-context="activeSelectedTextContext"
            :current-insight-html="currentInsightHtml"
            :current-insight-title="currentInsightTitle"
            :content-context="activeWorkspaceContent || selectedContentItem"
            :conversation-key="activeWorkspaceContent?.id || result.content_item_id || ''"
            :content-analysis-templates="contentAnalysisTemplates"
            :qa-history="qaHistory"
            :qa-history-loading="qaHistoryLoading"
            :qa-history-loading-more="qaHistoryLoadingMore"
            :qa-history-has-more="qaHistoryHasMore"
            :qa-history-error="qaHistoryError"
            :qa-shortcut-templates="qaShortcutTemplates"
            :article-ocr-status="currentArticleOcrStatus"
            :prioritizing-article-ocr="prioritizingArticleOcr"
            :asking-question="askingQuestion"
            :generating-ai-summary="generatingAiSummary || isPipelineSummaryGenerating"
            :generating-summary-text="generatingSummaryText || pipelineGeneratingSummaryText"
            :starting-new-chat="startingNewChat"
            :current-qa-enabled="currentQaEnabled"
            :current-qa-hint="currentQaHint"
            :can-generate-ai-summary="canGenerateAiSummary"
            :exporting-markdown="exportingConversationMarkdown"
            :selected-ai-model="assistantAiModel"
            :available-ai-models="availableAiModels"
            :render-markdown="renderMarkdown"
            @update:selected-ai-model="assistantAiModel = $event"
            @new-chat="startNewChat"
            @generate-ai-summary="generateAiSummary"
            @ask-question="askQuestion"
            @load-more-qa-history="loadMoreContentQaHistory"
            @retry-qa-history="retryContentQaHistory"
            @insert-shortcut="insertQaShortcut"
            @prioritize-ocr="prioritizeCurrentArticleOcr"
            @run-content-analysis="runContentAnalysis"
            @export-markdown="exportConversationMarkdown"
            @copy-qa-exchange="copyQaExchange"
            @regenerate-qa-answer="regenerateQaAnswer"
            @seek-video="seekSummaryTimestamp"
            @return-to-source="returnToExternalSource"
          />
          </template>
      </WorkbenchShell>

      <Transition name="startup-gate">
        <section v-if="startupBlocking" class="startup-gate" aria-live="polite" aria-label="正在准备工作台">
          <div class="startup-gate-content" role="status">
            <p class="startup-gate-status">
              {{ startupStatus.title }}<span v-if="!startupCanRetry" aria-hidden="true">…</span>
            </p>
            <div class="startup-gate-progress" aria-hidden="true"><span></span></div>
            <div v-if="startupCanRetry" class="startup-gate-recovery">
              <span>{{ startupStatus.detail }}</span>
              <el-button class="startup-gate-retry" size="small" @click="retryStartupHydration">重新连接</el-button>
            </div>
          </div>
        </section>
      </Transition>

      <CommandPalette
        v-if="commandPaletteOpen"
        v-model="commandPaletteOpen"
        :items="commandPaletteItems"
        @select="handleCommandPaletteSelect"
      />

      <SettingsDialog
        v-if="showSettings"
        v-model="showSettings"
        @library-changed="loadContentItems"
        @processing-started="handleCreatorProcessingStarted"
        :initial-section="settingsInitialSection"
        v-model:selected-theme="selectedTheme"
        v-model:selected-ai-model="selectedAiModel"
        v-model:deepseek-api-key="deepseekApiKey"
        v-model:deepseek-base-url="deepseekBaseUrl"
        v-model:deepseek-pricing="deepseekPricing"
        v-model:deepseek-peak-pricing-multiplier="deepseekPeakPricingMultiplier"
        v-model:embedding-api-key="embeddingApiKey"
        v-model:embedding-base-url="embeddingBaseUrl"
        v-model:embedding-model="embeddingModel"
        v-model:paddle-ocr-access-token="paddleOcrAccessToken"
        v-model:paddle-ocr-base-url="paddleOcrBaseUrl"
        v-model:paddle-ocr-model="paddleOcrModel"
        v-model:manual-auto-summarize="manualAutoSummarize"
        v-model:auto-download-bilibili-video="autoDownloadBilibiliVideo"
        v-model:douyin-video-quality="douyinVideoQuality"
        v-model:obsidian-vault-path="obsidianVaultPath"
        v-model:markdown-export-path="markdownExportPath"
        v-model:obsidian-auto-write="obsidianAutoWrite"
        v-model:cookie-input="cookieInput"
        v-model:bilibili-cookie-input="bilibiliCookieInput"
        v-model:ffmpeg-path="ffmpegPath"
        v-model:yt-dlp-path="ytDlpPath"
        v-model:wechat-selected-account-id="selectedWeChatAccountId"
        v-model:wechat-account-display-name="wechatAccountDisplayName"
        v-model:wechat-manual-token="wechatManualToken"
        v-model:wechat-manual-cookie="wechatManualCookie"
        v-model:wechat-search-query="wechatSearchQuery"
        v-model:wechat-subscription-interval="wechatSubscriptionInterval"
        v-model:wechat-auto-process="wechatAutoProcess"
        v-model:wechat-publishing-display-name="wechatPublishingDisplayName"
        v-model:wechat-publishing-app-id="wechatPublishingAppId"
        v-model:wechat-publishing-app-secret="wechatPublishingAppSecret"
        v-model:wechat-public-site-base-url="wechatPublicSiteBaseUrl"
        v-model:wechat-qwen-cover-api-key="wechatQwenCoverApiKey"
        v-model:wechat-qwen-cover-endpoint="wechatQwenCoverEndpoint"
        v-model:wechat-qwen-cover-model="wechatQwenCoverModel"
        :theme-options="themeOptions"
        :selected-theme-option="selectedThemeOption"
        :available-ai-models="availableAiModels"
        :clipboard-watching="clipboardWatching"
        :clipboard-scanning="clipboardScanning"
        :folder-import-watching="folderImportWatching"
        :folder-import-scanning="folderImportScanning"
        :folder-import-path="folderImportPath"
        :openclaw-running="openclawRunning"
        :openclaw-scanning="openclawScanning"
        :openclaw-status-text="openclawStatusText"
        :openclaw-connection-items="openclawConnectionItems"
        :openclaw-status-tone="openclawStatusTone"
        :wechat-accounts="wechatAccounts"
        :wechat-subscriptions="wechatSubscriptions"
        :wechat-loading="loadingWeChatSubscriptions"
        :wechat-qr-login="wechatQrLogin"
        :wechat-qr-starting="wechatQrStarting"
        :wechat-manual-connecting="wechatManualConnecting"
        :wechat-search-results="wechatSearchResults"
        :wechat-searching="wechatSearching"
        :wechat-interval-options="wechatSyncIntervalOptions"
        :wechat-subscription-states="wechatSubscriptionStates"
        :wechat-syncing-subscription-id="syncingWeChatSubscriptionId"
        :wechat-content-filters="wechatContentFilters"
        :wechat-report-groups="wechatReportGroups"
        :wechat-generating-group-id="wechatGeneratingGroupId"
        :wechat-deleting-group-id="wechatDeletingGroupId"
        :wechat-filter-saving="savingWeChatFilter"
        :wechat-auto-sync-summary="wechatAutoSyncSummary"
        :wechat-last-sync-summary="wechatLastSyncSummary"
        :wechat-publishing-settings="wechatPublishingSettings"
        :saving-wechat-publishing-settings="savingWechatPublishingSettings"
        :wechat-qwen-cover-settings="wechatQwenCoverSettings"
        :saving-wechat-qwen-cover-settings="savingWechatQwenCoverSettings"
        :testing-wechat-qwen-cover-connection="testingWechatQwenCoverConnection"
        :cookie-configured="cookieConfigured"
        :cookie-state="cookieState"
        :cookie-status-text="cookieStatusText"
        :cookie-checking="cookieChecking"
        :saving-cookie="savingCookie"
        :bilibili-cookie-configured="bilibiliCookieConfigured"
        :bilibili-cookie-status-text="bilibiliCookieStatusText"
        :saving-bilibili-cookie="savingBilibiliCookie"
        :bilibili-cookie-state="bilibiliCookieState"
        :platform-auth-available="platformAuthAvailable"
        :platform-auth-connecting="platformAuthConnecting"
        :media-tools="mediaTools"
        :saving-media-tools="savingMediaTools"
        :runtime-components="runtimeComponents"
        :runtime-components-loading="loadingRuntimeComponents"
        :deepseek-configured="deepseekConfigured"
        :saving-deepseek-settings="savingDeepSeekSettings"
        :testing-deepseek-connection="testingDeepSeekConnection"
        :embedding-configured="embeddingConfigured"
        :saving-embedding-settings="savingEmbeddingSettings"
        :testing-embedding-connection="testingEmbeddingConnection"
        :paddle-ocr-configured="paddleOcrConfigured"
        :saving-paddle-ocr-settings="savingPaddleOcrSettings"
        @save-obsidian="saveObsidianSettingsFromForm"
        @choose-obsidian-folder="chooseObsidianFolder"
        @choose-export-folder="chooseMarkdownExportFolder"
        @toggle-clipboard="toggleClipboardWatching"
        @choose-folder-import="chooseFolderImportDirectory"
        @toggle-folder-import="toggleFolderImportWatching"
        @start-openclaw="startOpenClawGateway"
        @load-wechat="loadWeChatSubscriptions"
        @start-wechat-qr="startWeChatQrLogin"
        @reauthorize-account="startWeChatQrLogin($event)"
        @connect-wechat-manually="connectWeChatManually"
        @delete-wechat-account="deleteWeChatAccount"
        @transfer-account-subscriptions="transferWeChatAccountSubscriptions"
        @search-wechat="searchWeChatAccounts"
        @subscribe-wechat="subscribeWeChatAccount"
        @update-wechat-subscription="updateWeChatSubscription"
        @sync-wechat-subscription="syncWeChatSubscription"
        @delete-wechat-subscription="deleteWeChatSubscription"
        @create-wechat-filter="createWeChatFilter"
        @delete-wechat-filter="deleteWeChatFilter"
        @create-wechat-report-group="createWeChatReportGroup"
        @delete-wechat-report-group="deleteWeChatReportGroup"
        @generate-wechat-report="generateWeChatReport"
        @copy-wechat-rss="copyWeChatRss"
        @export-wechat-subscriptions="exportWeChatSubscriptions"
        @save-wechat-publishing-settings="saveWechatPublishingSettings"
        @save-wechat-qwen-cover-settings="saveWechatQwenCoverSettings"
        @test-wechat-qwen-cover-connection="testWechatQwenCoverConnection"
        @save-cookie="saveCookie({ closeAfterSave: false })"
        @save-bilibili-cookie="saveBilibiliCookie"
        @connect-platform-auth="connectPlatformAuth"
        @disconnect-platform-auth="disconnectPlatformAuth"
        @check-platform-auth="(platform) => platform === 'bilibili' ? loadBilibiliCookieStatus(true) : loadCookieStatus(true)"
        @save-media-tools="saveMediaTools"
        @choose-media-tool="chooseMediaTool"
        @load-runtime-components="loadRuntimeComponents"
        @install-browser="installRuntimeBrowser"
        @download-asr-model="downloadAsrModel"
        @delete-asr-model="deleteAsrModel"
        @save-deepseek-settings="saveDeepSeekSettings"
        @test-deepseek-connection="testDeepSeekConnection"
        @save-embedding-settings="saveEmbeddingSettings"
        @test-embedding-connection="testEmbeddingConnection"
        @save-paddle-ocr-settings="savePaddleOcrSettings"
        @save-manual-collection-settings="saveManualCollectionSettings"
        @save-video-download-settings="saveVideoDownloadSettings"
        @open-wechat-manager="openWeChatManager"
      />

      <SourceGroupEditorDialog
        v-if="showSourceGroupEditor"
        v-model="showSourceGroupEditor"
        :group="sourceGroupEditor"
        :removing-source-key="removingSourceGroupKey"
        @remove-source="removeSourceFromGroup"
        @closed="sourceGroupEditor = null"
      />

      <ReportGenerationDialog
        v-if="reportGenerationDialog.visible"
        :state="reportGenerationDialog"
        @cancel="cancelReportGenerationDialog"
        @confirm="confirmReportGenerationDialog"
      />

      <WechatCoverPlanDialog
        v-if="wechatCoverPlanDialogVisible"
        v-model:visible="wechatCoverPlanDialogVisible"
        :loading="planningWechatCover"
        :submitting="submittingWechatCoverPlan"
        :previewing-prompt="previewingWechatCoverPrompt"
        :plan="wechatCoverPlan"
        :resolved-prompt="wechatCoverResolvedPrompt"
        :style-options="WECHAT_COVER_STYLE_OPTIONS"
        :selected-style="wechatCoverStyle"
        @start-plan="planWechatCover"
        @confirm="confirmWechatCoverPlan"
        @preview-prompt="previewWechatCoverPrompt"
      />

      <WechatDraftDialog
        v-if="wechatDraftDialogVisible"
        v-model:visible="wechatDraftDialogVisible"
        v-model:title="wechatDraftTitle"
        v-model:author="wechatDraftAuthor"
        :digest="wechatDraftDigest"
        :display-name="wechatPublishingSettings.display_name"
        :loading-defaults="loadingWechatDraftDefaults"
        :cover-url="wechatDraftCoverUrl"
        :cover-available="wechatDraftCoverAvailable"
        :ip-preflight="wechatDraftIpPreflight"
        :verifying-ip="verifyingWechatDraftIp"
        :preview-html="wechatDraftPreviewHtml"
        :task="wechatDraftTask"
        :latest-publication="wechatDraftLatestPublication"
        :creating="creatingWechatDraft"
        @update:digest="wechatDraftDigest = truncateWechatDigest($event)"
        @verify-ip="verifyWechatDraftIp"
        @confirm-publication="confirmWechatPublication"
        @submit="createWechatReportDraft"
      />

      <el-dialog v-model="showMarkdownDialog" title="Markdown 草稿" width="860px">
        <div class="markdown-dialog">
          <div class="markdown-dialog-head">
            <div>
              <strong>{{ currentMarkdownItem?.title || '未命名内容' }}</strong>
              <span v-if="markdownState.obsidian_path">{{ markdownState.obsidian_path }}</span>
            </div>
            <el-tag
              :type="markdownState.sync_status === 'synced' ? 'success' : 'warning'"
              effect="plain"
            >
              {{ markdownSyncLabel(markdownState.sync_status) }}
            </el-tag>
          </div>
          <el-input
            v-model="markdownState.markdown"
            type="textarea"
            name="markdown-content"
            autocomplete="off"
            aria-label="Markdown 内容"
            :rows="20"
            resize="vertical"
          />
          <div class="markdown-dialog-actions">
            <el-button round :loading="savingMarkdown" @click="saveMarkdownDraft">保存草稿</el-button>
            <el-button type="primary" round :loading="syncingMarkdown" @click="syncMarkdownDraft">
              写入指定目录
            </el-button>
          </div>
        </div>
      </el-dialog>
    </main>

    <AppleDeleteConfirmDialog />

    <footer class="statusbar">
      <div class="statusbar-context-slot">
        <div v-if="!statusbarProgress.visible" class="statusbar-breadcrumb-slot">
          <StatusBreadcrumb
            :items="statusbarBreadcrumbItems"
            @select="handleStatusBreadcrumbSelect"
          />
        </div>
        <div
          v-else
          class="statusbar-progress"
          :class="{ 'is-indeterminate': statusbarProgress.percent === null }"
          :title="`${statusbarProgress.label} · ${statusbarProgress.detail}`"
          role="status"
          aria-live="polite"
        >
          <span class="statusbar-progress-stage">{{ statusbarProgress.label }}</span>
          <span class="statusbar-progress-detail">{{ statusbarProgress.detail }}</span>
          <div v-if="statusbarProgress.percent !== null" class="statusbar-progress-track" role="progressbar" :aria-valuenow="statusbarProgress.percent" aria-valuemin="0" aria-valuemax="100">
            <div
              class="statusbar-progress-fill"
              :style="{ transform: `scaleX(${Math.max(0, Math.min(100, statusbarProgress.percent || 0)) / 100})` }"
            ></div>
          </div>
          <div v-else class="statusbar-progress-track statusbar-progress-track-indeterminate" aria-label="正在处理"></div>
          <span class="statusbar-progress-metric">{{ statusbarProgress.percent === null ? '进行中' : `${statusbarProgress.percent}%` }}</span>
        </div>
      </div>
      <div class="statusbar-summary">
        <div class="statusbar-static" aria-label="运行状态概览">
          <span
            class="statusbar-preparation"
            :class="{ 'is-active': articlePreparationStatusLabel !== '空闲' }"
            :title="articlePreparationStatusTooltip"
          >
            正文预抓取：{{ articlePreparationStatusLabel }}
          </span>
          <div class="statusbar-cache" aria-label="全局缓存概览">
            <span v-for="item in cacheStatusItems" :key="item.label" class="statusbar-cache-item" :title="`${item.label}：${item.value}`">
              <small>{{ item.label }}</small>
              <span>{{ item.value }}</span>
            </span>
          </div>
        </div>
        <div class="statusbar-right">
          <el-tooltip :content="aiTokenUsage.tooltip" placement="top" popper-class="statusbar-token-tooltip">
            <button
              type="button"
              class="statusbar-token-usage"
              :class="{ 'has-usage': aiTokenUsage.hasUsage, 'has-unreported-usage': aiTokenUsage.hasUnreportedUsage }"
              :aria-label="aiTokenUsage.toggleLabel"
              @click="toggleAiTokenDisplayMode"
            >
              {{ aiTokenUsage.label }}
            </button>
          </el-tooltip>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import SvgMaskIcon from './components/SvgMaskIcon.vue'
import PanelToggleIcon from './components/PanelToggleIcon.vue'
import StatusBreadcrumb from './components/StatusBreadcrumb.vue'
import AppleDeleteConfirmDialog from './components/AppleDeleteConfirmDialog.vue'
const folderIcon = 'folder'
const magnifyingglassIcon = 'magnifyingglass'
import { formatTokenCount } from './utils/viewFormatters'
import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from './utils/localApiAuth.js'
import WorkbenchShell from './workbench/WorkbenchShell.vue'
import WorkspaceTabs from './workbench/WorkspaceTabs.vue'
import WorkspaceChromeActions from './workbench/WorkspaceChromeActions.vue'
import ProcessLogDock from './workbench/ProcessLogDock.vue'
import PrimarySidebar from './workbench/PrimarySidebar.vue'
import { normalizeWorkspacePaneVisibility } from './workbench/paneVisibilityState.js'
import { isSinglePaneWorkspaceView } from './workbench/workspaceViewLoading.js'
import SecondarySidebar from './features/assistant/SecondarySidebar.vue'
import { useAppController } from './composables/useAppController'
import { useCampusAccess } from './composables/useCampusAccess'
import { useRuntimeSettingsController } from './features/settings/useRuntimeSettingsController.js'
import { requestDestructiveConfirmation } from './composables/useDestructiveConfirm'
import { enqueueSourceSyncTask, observeSourceSyncTask } from './utils/sourceSyncTask'
import { promptTaskContracts } from './config/promptInterface'
import { WECHAT_COVER_STYLE_OPTIONS } from './config/wechatCoverStyles'
import { useWechatCoverController } from './features/wechat/useWechatCoverController.js'
import { useWechatDraftController } from './features/wechat/useWechatDraftController.js'
import { useWechatPublishingSettingsController } from './features/wechat/useWechatPublishingSettingsController.js'
import { useWechatReportPromptController } from './features/prompts/useWechatReportPromptController.js'
import { useWechatReportGenerationController } from './features/reports/useWechatReportGenerationController.js'
import { usePromptWorkspaceController } from './features/prompts/usePromptWorkspaceController.js'
import { useWechatAccountController } from './features/wechat/useWechatAccountController.js'
import { useWechatFilterController } from './features/wechat/useWechatFilterController.js'
import { useWechatReportGroupController } from './features/wechat/useWechatReportGroupController.js'
import { useWechatSubscriptionSyncController } from './features/wechat/useWechatSubscriptionSyncController.js'
import { useWechatSubscriptionManagementController } from './features/wechat/useWechatSubscriptionManagementController.js'
import { useWechatFeedExportController } from './features/wechat/useWechatFeedExportController.js'
import { useLibrarySourceGroupController } from './features/library/useLibrarySourceGroupController.js'

const loadWeChatManager = () => import('./features/wechat/WeChatManager.vue')
const loadCampusManager = () => import('./features/campus/CampusManager.vue')
const loadCreatorWorkspace = () => import('./features/creator/CreatorWorkspace.vue')
const loadRssWorkspace = () => import('./features/rss/RssWorkspace.vue')
const loadReportsWorkspace = () => import('./features/reports/ReportsWorkspace.vue')
const loadKnowledgeWorkspace = () => import('./features/knowledge/KnowledgeWorkspace.vue')
const loadKnowledgeSidebar = () => import('./features/knowledge/KnowledgeSidebar.vue')
const loadEvidencePreviewSidebar = () => import('./features/knowledge/EvidencePreviewSidebar.vue')
const WeChatManager = defineAsyncComponent(loadWeChatManager)
const EditorHost = defineAsyncComponent(() => import('./workbench/EditorHost.vue'))
const CampusManager = defineAsyncComponent(loadCampusManager)
const CreatorWorkspace = defineAsyncComponent(loadCreatorWorkspace)
const RssWorkspace = defineAsyncComponent(loadRssWorkspace)
const ReportsWorkspace = defineAsyncComponent(loadReportsWorkspace)
const KnowledgeWorkspace = defineAsyncComponent(loadKnowledgeWorkspace)
const KnowledgeSidebar = defineAsyncComponent(loadKnowledgeSidebar)
const EvidencePreviewSidebar = defineAsyncComponent(loadEvidencePreviewSidebar)
const CommandPalette = defineAsyncComponent(() => import('./components/CommandPalette.vue'))
const SettingsDialog = defineAsyncComponent(() => import('./components/SettingsDialog.vue'))
const ReportGenerationDialog = defineAsyncComponent(() => import('./features/reports/ReportGenerationDialog.vue'))
const SourceGroupEditorDialog = defineAsyncComponent(() => import('./features/reports/SourceGroupEditorDialog.vue'))
const WechatCoverPlanDialog = defineAsyncComponent(() => import('./features/wechat/WechatCoverPlanDialog.vue'))
const WechatDraftDialog = defineAsyncComponent(() => import('./features/wechat/WechatDraftDialog.vue'))
const {
  activeView,
  workspaceTabs,
  workspaceLayout,
  shareText,
  parsedUrl,
  running,
  taskStatus,
  miniprogramForumCaptureEnabled,
  selectedAiModel,
  assistantAiModel,
  availableAiModels,
  autoDownloadBilibiliVideo,
  douyinVideoQuality,
  searchQuery,
  librarySearchScope,
  retryingContentId,
  libraryFolders,
  libraryFolderHistoryStates,
  libraryFolderRevealIds,
  allContentItems,
  contentPageLoadStatus,
  libraryTrashEntries,
  loadingLibraryTrash,
  selectedContentItem,
  startupBlocking,
  startupCanRetry,
  startupStatus,
  showMarkdownDialog,
  currentMarkdownItem,
  savingMarkdown,
  syncingMarkdown,
  exportingConversationMarkdown,
  promptTaskType,
  promptTemplates,
  selectedPromptTemplateId,
  qaShortcutTemplates,
  autoQaShortcutRecognition,
  contentAnalysisTemplates,
  loadingPrompts,
  savingPromptTemplate,
  activatingPromptTemplate,
  promptEditorText,
  promptEditorName,
  questionInput,
  activeSelectedTextContext,
  qaHistory,
  qaHistoryLoading,
  qaHistoryLoadingMore,
  qaHistoryHasMore,
  qaHistoryError,
  viewedContentIds,
  explicitlyUnreadContentIds,
  contentViewedBefore,
  setContentViewedState,
  askingQuestion,
  generatingAiSummary,
  isPipelineSummaryGenerating,
  generatingSummaryText,
  pipelineGeneratingSummaryText,
  startingNewChat,
  lastQaSaved,
  clipboardWatching,
  clipboardScanning,
  openclawRunning,
  openclawScanning,
  openclawStatusText,
  openclawConnectionItems,
  openclawStatusTone,
  loadOpenClawStatus,
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
  selectedMarkdownPreview,
  selectedMarkdownSizeBytes,
  selectedReportSourceStats,
  result,
  logs,
  processLogEntries,
  batchTasks,
  batchTaskIds,
  promptTaskOptions,
  ribbonItems,
  mediaPreviewUrl,
  sidebarTreeItems,
  activeWorkspaceTab,
  activeWorkspaceContent,
  activeContentAiCalls,
  dailyAiTokenUsage,
  openClawTokenUsage,
  currentInsightHtml,
  currentInsightTitle,
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
  modelProfileOptions,
  currentStageLabel,
  workspaceTabById,
  contentForTab,
  resultForTab,
  mediaUrlForTab,
  originalMediaUrlForTab,
  transcriptForTab,
  articlePreviewForTab,
  statusLabel,
  statusTagType,
  progressStatus,
  roundedProgress,
  stepLabel,
  batchTaskName,
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
  toggleClipboardWatching,
  startOpenClawGateway,
  saveObsidianSettingsFromForm,
  saveCookie,
  saveBilibiliCookie,
  connectPlatformAuth,
  disconnectPlatformAuth,
  loadContentItems,
  revealContentItems,
  retryStartupHydration,
  monitorCreatorSyncTasks,
  setTaskQueuePollingInterval,
  loadLibraryFolders,
  loadLibraryFolderHistory,
  loadLibraryTrash,
  restoreLibraryTrashEntry,
  permanentlyDeleteLibraryTrashEntry,
  emptyLibraryTrash,
  retryContentSourceText,
  retryContentProcessing,
  reprocessLocalSource,
  retranscribeContentVideo,
  fetchExternalSubtitleForContent,
  refreshContentSourceContext,
  redownloadContentVideo,
  retryBatchTask,
  cancelBatchTask,
  cancelActiveTasks,
  loadBatchTaskDetails,
  pollBatchTasks,
  saveVideoDownloadSettings,
  loadContentAiCalls,
  loadAiTokenUsageSummary,
  runContentAnalysis,
  clearLogs,
  addLog,
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
  createLibraryFolder,
  renameLibraryFolder,
  setLibraryFolderPinned,
  deleteLibraryFolder,
  renameContentItem,
  deleteContentItem,
  moveLibraryNode,
  moveLibraryNodes,
  deleteLibraryNodes,
  revealLibraryNodeLocation,
  revealLocalPath,
  copyText,
  openExternalLink,
  startNewChat,
  onInputChange,
  runFullPipeline,
  insertQaShortcut,
  setSelectedTextContext,
  prioritizeCurrentArticleOcr,
  askQuestion,
  copyQaExchange,
  regenerateQaAnswer,
  loadMoreContentQaHistory,
  retryContentQaHistory,
  exportConversationMarkdown,
  generateAiSummary
} = useAppController()

const settingsInitialSection = ref('appearance')
const commandPaletteOpen = ref(false)

const commandPaletteItems = computed(() => {
  const viewItems = ribbonItems.map((item) => ({
    id: `view:${item.view}`,
    group: '工作区',
    kind: 'view',
    title: item.label,
    subtitle: item.view === activeView.value ? '当前页面' : '切换工作区',
    keywords: [item.view],
    view: item.view,
  }))
  const actionItems = [
    {
      id: 'action:settings',
      group: '操作',
      kind: 'action',
      title: '打开设置',
      subtitle: '主题、账号、下载与模型配置',
      keywords: ['设置 preferences'],
      action: 'settings',
      shortcut: '⌘,',
    },
    {
      id: 'action:sync-wechat',
      group: '操作',
      kind: 'action',
      title: '检查全部公众号',
      subtitle: '将已启用订阅交给后台队列依次检查',
      keywords: ['同步 微信 公众号 subscription refresh'],
      action: 'sync-wechat',
    },
    {
      id: 'action:sync-campus',
      group: '操作',
      kind: 'action',
      title: '检查全部校园来源',
      subtitle: '将已启用校园来源交给后台队列依次检查',
      keywords: ['同步 校园 网页 campus refresh'],
      action: 'sync-campus',
    },
    {
      id: 'action:refresh-library',
      group: '操作',
      kind: 'action',
      title: '刷新资料库',
      subtitle: '重新读取文件夹和资料列表',
      keywords: ['刷新 reload library 文件树'],
      action: 'refresh-library',
    },
  ]
  const tabItems = workspaceTabs.value.slice().reverse().map((tab) => ({
    id: `tab:${tab.id}`,
    group: '已打开',
    kind: 'content',
    title: tab.title || '未命名资料',
    subtitle: '切换到已打开资料',
    keywords: [tab.source_provider || ''],
    tabId: tab.id,
  }))
  const contentItems = sidebarTreeItems.value.slice(0, 80).map((content) => ({
    id: `content:${content.id}`,
    group: '资料库',
    kind: 'content',
    title: content.title || content.canonical_source_id || '未命名资料',
    subtitle: [content.source_name, content.source_provider].filter(Boolean).join(' · ') || '打开资料',
    keywords: [content.canonical_source_id || '', content.source_provider || ''],
    content,
  }))
  return [...viewItems, ...actionItems, ...tabItems, ...contentItems]
})

async function handleCommandPaletteSelect(item) {
  if (item?.kind === 'view' && item.view) {
    activeView.value = item.view
    return
  }
  if (item?.action === 'settings') {
    settingsInitialSection.value = 'appearance'
    showSettings.value = true
    return
  }
  if (item?.action === 'sync-wechat') {
    await syncAllWeChatSubscriptions()
    return
  }
  if (item?.action === 'sync-campus') {
    await syncAllCampusSources()
    return
  }
  if (item?.action === 'refresh-library') {
    await Promise.all([loadLibraryFolders(), loadContentItems()])
    return
  }
  if (item?.tabId) {
    await activateWorkspaceTab(item.tabId)
    return
  }
  if (item?.content) await openContentFromSidebar(item.content)
}

const {
  campusAccess,
  campusConnecting,
  campusSyncing,
  campusBulkSyncing,
  campusSources,
  campusSourcesLoading,
  campusSyncingSource,
  campusSyncingSources,
  loadCampusSources,
  updateCampusSource,
  loadCampusAccessStatus,
  connectCampusWebVpn,
  disconnectCampusWebVpn,
  syncCampusSource,
  syncCampusHistory,
  syncAllCampusSources
} = useCampusAccess({
  refreshContent: loadContentItems,
  refreshFolders: loadLibraryFolders,
  revealContentItems,
})

const {
  mediaTools,
  ffmpegPath,
  ytDlpPath,
  savingMediaTools,
  runtimeComponents,
  loadingRuntimeComponents,
  deepseekApiKey,
  deepseekBaseUrl,
  deepseekPricing,
  deepseekPeakPricingMultiplier,
  deepseekConfigured,
  savingDeepSeekSettings,
  testingDeepSeekConnection,
  embeddingApiKey,
  embeddingBaseUrl,
  embeddingModel,
  embeddingConfigured,
  savingEmbeddingSettings,
  testingEmbeddingConnection,
  paddleOcrAccessToken,
  paddleOcrConfigured,
  paddleOcrBaseUrl,
  paddleOcrModel,
  savingPaddleOcrSettings,
  manualAutoSummarize,
  loadManualCollectionSettings,
  saveManualCollectionSettings,
  loadDeepSeekSettings,
  saveDeepSeekSettings,
  testDeepSeekConnection,
  saveEmbeddingSettings,
  testEmbeddingConnection,
  loadPaddleOcrSettings,
  savePaddleOcrSettings,
  loadMediaTools,
  saveMediaTools,
  chooseMediaTool,
  loadRuntimeComponents,
  installRuntimeBrowser,
  downloadAsrModel,
  deleteAsrModel
} = useRuntimeSettingsController({
  formatBytes,
  loadAiTokenUsageSummary,
  requestDestructiveConfirmation
})

const WORKSPACE_PANE_VISIBILITY_KEY = 'knowledgehub.workspace-pane-visibility.v1'

function readWorkspacePaneVisibility() {
  try {
    return normalizeWorkspacePaneVisibility(JSON.parse(localStorage.getItem(WORKSPACE_PANE_VISIBILITY_KEY) || '{}'))
  } catch {
    return normalizeWorkspacePaneVisibility(null)
  }
}

const savedWorkspacePaneVisibility = readWorkspacePaneVisibility()
const contextSidebarOpen = ref(savedWorkspacePaneVisibility.context)
const primarySidebarOpen = ref(savedWorkspacePaneVisibility.primary)
const primaryPaneTransitioning = ref(false)
const workbenchShell = ref(null)
const primarySidebar = ref(null)
const librarySidebarMode = ref('files')
const knowledgeWorkspace = ref(null)
const knowledgeSidebar = ref(null)
const editorHost = ref(null)
const activeKnowledgeConversationId = ref('')
const knowledgeEvidence = ref(null)
const knowledgeConversationUsage = ref(emptyKnowledgeConversationUsage())
const folderImportWatching = ref(false)
const folderImportScanning = ref(false)
const folderImportPath = ref('')

async function openKnowledgeEvidence(chunkId) {
  if (!chunkId) return
  try {
    const response = await fetch(localApiRequestUrl(`${API}/knowledge/v2/evidence/${encodeURIComponent(chunkId)}`), {
      headers: await localApiAuthHeaders(),
    })
    if (!response.ok) throw Error('引用原文已不可用')
    knowledgeEvidence.value = await response.json()
    contextSidebarOpen.value = true
  } catch (error) {
    ElMessage.error(error.message || '无法打开引用原文')
  }
}

function emptyKnowledgeConversationUsage() {
  return {
    call_count: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    total_tokens: 0,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 0,
    estimated_cost: 0,
    unreported_count: 0,
  }
}

async function exportKnowledgeConversationMarkdown(payload) {
  const complete = typeof payload?.complete === 'function' ? payload.complete : () => {}
  const title = String(payload?.title || '知识库对话').replace(/\r?\n/gu, ' ').trim() || '知识库对话'
  const markdown = String(payload?.markdown || '')
  if (!markdown.trim()) {
    ElMessage.warning('当前没有可导出的知识库对话')
    complete()
    return
  }
  try {
    const desktopExport = window.knowledgeHubDesktop?.exportMarkdown
    const exported = desktopExport
      ? await desktopExport(title, markdown)
      : (await axios.post(`${API}/markdown/export`, { title, markdown }, { timeout: 15000 })).data
    ElMessage.success(`Markdown 已导出到 ${exported.path}`)
  } catch (error) {
    const message = error.response?.data?.detail || error.message || '导出 Markdown 失败'
    ElMessage.error(typeof message === 'string' ? message : '导出 Markdown 失败')
  } finally {
    complete()
  }
}

function seekSummaryTimestamp(seconds) {
  editorHost.value?.seekToTimestamp(seconds)
}

function returnToExternalSource() {
  editorHost.value?.focusSourceReader?.()
}

async function loadFolderImportWatcherStatus() {
  try {
    const response = await axios.get(FOLDER_IMPORT_WATCHER_API, { timeout: 10000 })
    folderImportWatching.value = Boolean(response.data?.running)
    folderImportPath.value = String(response.data?.folder_path || '')
  } catch {
    folderImportWatching.value = false
  }
}

async function chooseFolderImportDirectory() {
  const folder = await window.knowledgeHubDesktop?.chooseDirectory?.()
  if (folder) folderImportPath.value = folder
}

async function toggleFolderImportWatching(enabled) {
  if (enabled && !folderImportPath.value) {
    await chooseFolderImportDirectory()
    if (!folderImportPath.value) return
  }
  folderImportScanning.value = true
  try {
    const response = enabled
      ? await axios.post(`${FOLDER_IMPORT_WATCHER_API}/start`, { folder_path: folderImportPath.value, poll_interval: 15 }, { timeout: 10000 })
      : await axios.post(`${FOLDER_IMPORT_WATCHER_API}/stop`, {}, { timeout: 10000 })
    folderImportWatching.value = Boolean(response.data?.running)
    folderImportPath.value = String(response.data?.folder_path || folderImportPath.value)
    ElMessage.success(enabled ? '本地收件箱监听已开启；只会导入之后新放入的文件' : '本地收件箱监听已停止')
  } catch (error) {
    folderImportWatching.value = false
    ElMessage.error(wechatErrorMessage(error, '本地收件箱监听设置失败'))
  } finally {
    folderImportScanning.value = false
  }
}

const PROCESS_LOG_OPEN_KEY = 'knowledgehub.process-log-open.v1'
const PROCESS_LOG_HEIGHT_KEY = 'knowledgehub.process-log-height.v1'
const processLogOpen = ref(localStorage.getItem(PROCESS_LOG_OPEN_KEY) === 'true')
const processLogHeight = ref(Math.max(150, Math.min(360, Number(localStorage.getItem(PROCESS_LOG_HEIGHT_KEY) || 240))))

function askAboutSelection(context) {
  setSelectedTextContext(context)
  contextSidebarOpen.value = true
}

async function handleCreatorProcessingStarted(payload) {
  processLogOpen.value = true
  await monitorCreatorSyncTasks(payload)
}

async function reconnectDouyinAndRetryTask(task) {
  if (!task?.task_id) return
  const connected = await connectPlatformAuth('douyin')
  if (connected) await retryBatchTask(task)
}

const WECHAT_SUBSCRIPTION_API = `${API}/wechat-subscriptions`
const WECHAT_FILTER_API = `${API}/wechat-content-filters`
const WECHAT_FEED_API = `${API}/wechat-feed`
const WECHAT_REPORT_GROUP_API = `${API}/wechat-report-groups`
const FOLDER_IMPORT_WATCHER_API = `${API}/folder-import-watcher`
const WECHAT_PUBLISHING_API = `${API}/wechat-publishing`
const LIBRARY_SOURCE_GROUPS_API = `${API}/content/source-groups`
const LIBRARY_LOCAL_FILE_IMPORT_API = `${API}/content/import-file`
const PROMPT_WORKSPACE_API = API

async function openCampusAttachment(attachment) {
  if (!attachment?.url) return
  if (attachment.download_type !== 'direct') {
    openExternalLink(attachment.url)
    return
  }
  const download = window.knowledgeHubDesktop?.downloadCampusAttachment
  if (!download) {
    openExternalLink(attachment.url)
    return
  }
  try {
    const result = await download({ url: attachment.url, name: attachment.name })
    if (!result?.canceled) ElMessage.success('附件已保存')
  } catch (error) {
    ElMessage.error(error?.message || '附件下载失败，请重新连接 WebVPN 后重试')
  }
}
const {
  ensureWechatCoverConfigured,
  ensureWechatPublishingConfigured,
  loadWechatPublishingSettings,
  loadWechatQwenCoverSettings,
  saveWechatPublishingSettings,
  saveWechatQwenCoverSettings,
  savingWechatPublishingSettings,
  savingWechatQwenCoverSettings,
  testWechatQwenCoverConnection,
  testingWechatQwenCoverConnection,
  wechatPublicSiteBaseUrl,
  wechatPublishingAppId,
  wechatPublishingAppSecret,
  wechatPublishingDisplayName,
  wechatPublishingSettings,
  wechatQwenCoverApiKey,
  wechatQwenCoverEndpoint,
  wechatQwenCoverModel,
  wechatQwenCoverSettings,
} = useWechatPublishingSettingsController({
  apiBase: WECHAT_PUBLISHING_API,
  openSettings: (section) => {
    settingsInitialSection.value = section
    showSettings.value = true
  },
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const {
  confirmWechatPublication,
  createWechatReportDraft,
  creatingWechatDraft,
  disposeWechatDraftController,
  loadingWechatDraftDefaults,
  openWechatDraftDialog,
  truncateWechatDigest,
  verifyWechatDraftIp,
  verifyingWechatDraftIp,
  wechatDraftAuthor,
  wechatDraftCoverAvailable,
  wechatDraftCoverStatus,
  wechatDraftCoverUrl,
  wechatDraftDialogVisible,
  wechatDraftDigest,
  wechatDraftContentItemId,
  wechatDraftIpPreflight,
  wechatDraftLatestPublication,
  wechatDraftPreviewHtml,
  wechatDraftTask,
  wechatDraftTitle,
} = useWechatDraftController({
  apiBase: WECHAT_PUBLISHING_API,
  ensurePublishingConfigured: ensureWechatPublishingConfigured,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const {
  confirmWechatCoverPlan,
  disposeWechatCoverController,
  loadWechatCoverHistory,
  openWechatCoverPlan,
  planWechatCover,
  planningWechatCover,
  previewWechatCoverPrompt,
  previewingWechatCoverPrompt,
  regenerateWechatReportCover,
  selectWechatReportCover,
  submittingWechatCoverPlan,
  wechatCoverGeneratingContentIds,
  wechatCoverHistoryForContent,
  wechatCoverPlan,
  wechatCoverPlanDialogVisible,
  wechatCoverResolvedPrompt,
  wechatCoverStyle,
  wechatCoverSwitchingContentIds,
} = useWechatCoverController({
  apiBase: WECHAT_PUBLISHING_API,
  selectedContentItem,
  ensureCoverConfigured: ensureWechatCoverConfigured,
  refreshContentItems: loadContentItems,
  refreshContentAiCalls: loadContentAiCalls,
  refreshAiTokenUsage: loadAiTokenUsageSummary,
  draftState: {
    contentItemId: wechatDraftContentItemId,
    coverStatus: wechatDraftCoverStatus,
    coverUrl: wechatDraftCoverUrl,
    dialogVisible: wechatDraftDialogVisible,
  },
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const loadingWeChatSubscriptions = ref(false)
let wechatSubscriptionsLoadVersion = 0
const wechatAccounts = ref([])
const wechatSubscriptions = ref([])
const wechatContentFilters = ref([])
const wechatReportGroups = ref([])
const {
  loadWechatReportPrompts,
  loadingWechatReportPrompts,
  saveWechatReportPrompt,
  savingWechatReportPrompt,
  selectWechatReportPromptGroup,
  selectWechatReportPromptType,
  selectedWechatReportPromptGroupId,
  selectedWechatReportPromptType,
  syncWechatReportPromptEditor,
  wechatReportPromptText,
  wechatReportPrompts,
} = useWechatReportPromptController({
  reportGroups: wechatReportGroups,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const {
  librarySourceGroups,
  sourceGroupEditor,
  showSourceGroupEditor,
  removingSourceGroupKey,
  loadLibrarySourceGroups,
  openSourceGroupEditor,
  removeSourceFromGroup,
} = useLibrarySourceGroupController({
  apiBase: LIBRARY_SOURCE_GROUPS_API,
  loadWeChatSubscriptions,
  loadCampusSources,
  confirmDestructive: requestDestructiveConfirmation,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const fixedSystemPrompts = ref([])
const {
  promptWorkspaceTemplates,
  promptFolders,
  promptWorkspaceTabs,
  activePromptTabId,
  promptTrashEntries,
  loadingPromptTrash,
  systemPromptEntries,
  promptContextEntries,
  activePromptNodeId,
  loadPromptWorkspaceData,
  loadPromptTrash,
  activatePromptWorkspaceTab,
  openPromptWorkspaceFile,
  openSystemPromptWorkspaceFile,
  openPromptContextWorkspaceFile,
  createPromptWorkspaceFile,
  closePromptWorkspaceTabs,
  closePromptWorkspaceTab,
  savePromptWorkspaceCurrent,
  resetPromptWorkspaceCurrent,
  createPromptWorkspaceFolder,
  renamePromptWorkspaceFolder,
  renamePromptWorkspaceFile,
  renameReportPromptWorkspaceFile,
  deletePromptWorkspaceFile,
  deletePromptWorkspaceFolder,
  movePromptWorkspaceNode,
  restorePromptTrashEntry,
  permanentlyDeletePromptTrashEntry,
  activatePromptWorkspaceTemplate,
} = usePromptWorkspaceController({
  standardPrompt: {
    taskType: promptTaskType,
    templates: promptTemplates,
    selectedId: selectedPromptTemplateId,
    editorName: promptEditorName,
    editorText: promptEditorText,
    load: loadPromptTemplates,
    select: selectPromptTemplate,
    create: createPromptTemplate,
    save: savePromptTemplate,
    activate: activatePromptTemplate,
    refreshQaShortcutTemplates: loadQaShortcutTemplates,
    refreshContentAnalysisTemplates: loadContentAnalysisTemplates,
  },
  reportPrompt: {
    prompts: wechatReportPrompts,
    text: wechatReportPromptText,
    load: loadWechatReportPrompts,
    save: saveWechatReportPrompt,
    selectGroup: selectWechatReportPromptGroup,
    selectType: selectWechatReportPromptType,
  },
  fixedSystemPrompts,
  activeView,
  apiBase: PROMPT_WORKSPACE_API,
  reportGroupApi: WECHAT_REPORT_GROUP_API,
  confirmDestructive: requestDestructiveConfirmation,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})
const wechatSubscriptionInterval = ref(1440)
const wechatAutoProcess = ref(false)
const wechatSubscriptionStates = ref({})
const wechatSyncIntervalOptions = [
  { label: '每 6 小时', value: 360 },
  { label: '每 12 小时', value: 720 },
  { label: '每天', value: 1440 }
]
let wechatInitialSyncListPollTimer = null

function wechatErrorMessage(error, fallback = '微信公众号订阅操作失败') {
  return error?.response?.data?.detail || error?.message || fallback
}

const {
  wechatGeneratingGroupId,
  wechatPreparingGroupId,
  reportGenerationDialog,
  generateWeChatReport,
  confirmReportGenerationDialog,
  cancelReportGenerationDialog,
  disposeWechatReportGenerationController,
} = useWechatReportGenerationController({
  reportGroups: wechatReportGroups,
  reportGroupApi: WECHAT_REPORT_GROUP_API,
  addLog,
  processLogOpen,
  refreshContentItems: loadContentItems,
  refreshLibraryFolders: loadLibraryFolders,
  refreshAiTokenUsage: loadAiTokenUsageSummary,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const {
  selectedWeChatAccountId,
  wechatAccountDisplayName,
  wechatQrLogin,
  wechatQrStarting,
  wechatManualToken,
  wechatManualCookie,
  wechatManualConnecting,
  wechatSearchQuery,
  wechatSearchResults,
  wechatSearching,
  reconcileSelectedAccount,
  startWeChatQrLogin,
  scheduleWeChatQrPoll,
  stopWeChatQrPolling,
  connectWeChatManually,
  deleteWeChatAccount,
  transferWeChatAccountSubscriptions,
  searchWeChatAccounts,
  clearWeChatSearchResults,
  disposeWechatAccountController,
} = useWechatAccountController({
  accounts: wechatAccounts,
  refreshSubscriptions: loadWeChatSubscriptions,
  settingsOpen: showSettings,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const {
  syncingWeChatSubscriptionId,
  wechatBulkSyncState,
  syncWeChatSubscription,
  syncAllWeChatSubscriptions,
} = useWechatSubscriptionSyncController({
  subscriptions: wechatSubscriptions,
  loadSubscriptions: loadWeChatSubscriptions,
  refreshContentItems: loadContentItems,
  enqueueTask: enqueueSourceSyncTask,
  observeTask: observeSourceSyncTask,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const {
  refreshingWeChatProfileId,
  subscribeWeChatAccount,
  updateWeChatSubscription,
  bulkUpdateWeChatSubscriptions,
  bulkAddWeChatSubscriptionGroup,
  refreshWeChatSubscriptionProfile,
  deleteWeChatSubscription,
} = useWechatSubscriptionManagementController({
  selectedAccountId: selectedWeChatAccountId,
  subscriptions: wechatSubscriptions,
  reportGroups: wechatReportGroups,
  subscriptionStates: wechatSubscriptionStates,
  syncInterval: wechatSubscriptionInterval,
  autoProcess: wechatAutoProcess,
  loadSubscriptions: loadWeChatSubscriptions,
  refreshContentItems: loadContentItems,
  observeTask: observeSourceSyncTask,
  apiBase: WECHAT_SUBSCRIPTION_API,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const {
  savingWeChatFilter,
  createWeChatFilter,
  deleteWeChatFilter,
} = useWechatFilterController({
  filterApi: WECHAT_FILTER_API,
  loadSubscriptions: loadWeChatSubscriptions,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const {
  wechatDeletingGroupId,
  wechatSavingScheduleGroupId,
  createWeChatReportGroup,
  deleteWeChatReportGroup,
  saveWeChatReportSchedule,
} = useWechatReportGroupController({
  reportGroupApi: WECHAT_REPORT_GROUP_API,
  loadSubscriptions: loadWeChatSubscriptions,
  loadReportPrompts: loadWechatReportPrompts,
  selectedReportPromptGroupId: selectedWechatReportPromptGroupId,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

const { copyWeChatRss, exportWeChatSubscriptions } = useWechatFeedExportController({
  feedApi: WECHAT_FEED_API,
  errorMessage: (error, fallback) => wechatErrorMessage(error, fallback),
})

function formatWeChatInterval(minutes) {
  const value = Number(minutes)
  if (!Number.isFinite(value) || value <= 0) return '自动检查'
  if (value % 1440 === 0) return value === 1440 ? '每天检查' : `每 ${value / 1440} 天检查`
  if (value % 60 === 0) return `每 ${value / 60} 小时检查`
  return `每 ${value} 分钟检查`
}

function formatWeChatTimestamp(value) {
  const timestamp = Date.parse(value || '')
  if (!Number.isFinite(timestamp)) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(timestamp)
}

function wechatRateLimited(subscription) {
  const until = Date.parse(subscription?.account_rate_limited_until || '')
  return Number.isFinite(until) && until > Date.now()
}

function wechatAutoSyncSummary(subscription) {
  if (!subscription.enabled) return '自动检查已暂停'
  if (subscription.account_status !== 'active') return '需要重新授权后自动检查'
  if (wechatRateLimited(subscription)) {
    return `频控冷却中 · 预计 ${formatWeChatTimestamp(subscription.account_rate_limited_until)} 恢复`
  }
  const next = formatWeChatTimestamp(subscription.next_sync_at)
  return `${formatWeChatInterval(subscription.sync_interval_minutes)}${next ? ` · 下次 ${next}` : ''}`
}

function wechatLastSyncSummary(subscription) {
  if (!subscription.last_run_status) return '尚未完成同步'
  if (subscription.last_run_status === 'running') return '正在检查最新文章'
  const completed = formatWeChatTimestamp(subscription.last_run_finished_at || subscription.last_sync_at)
  if (subscription.last_run_status === 'succeeded') {
    return `${completed ? `上次 ${completed}` : '上次检查'}：检查到 ${subscription.last_run_found_count || 0} 篇，新增 ${subscription.last_run_imported_count || 0} 篇`
  }
  if (wechatRateLimited(subscription) || subscription.last_error_category === 'rate_limit') {
    const resumeAt = formatWeChatTimestamp(subscription.account_rate_limited_until || subscription.next_sync_at)
    return `${completed ? `上次 ${completed}` : '上次同步'}触发微信频控${resumeAt ? `，预计 ${resumeAt} 自动恢复` : '，已暂停自动检查'}`
  }
  if (subscription.last_error_category === 'authorization') {
    return `${completed ? `上次 ${completed}` : '上次同步'}未完成，需要重新授权后继续检查`
  }
  const retryAt = formatWeChatTimestamp(subscription.next_sync_at)
  const attempts = Number(subscription.consecutive_failure_count || 0)
  const retryDetail = retryAt ? `下次 ${retryAt}` : '等待下一次检查'
  const reason = subscription.last_error_category === 'remote' ? '微信暂时拒绝访问' : '同步暂时失败'
  return `${completed ? `上次 ${completed}` : '上次同步'}${reason}${attempts ? ` · 已连续 ${attempts} 次` : ''}，${retryDetail}`
}

async function openWeChatManager() {
  showSettings.value = false
  const alreadyOpen = activeView.value === 'wechat'
  activeView.value = 'wechat'
  await nextTick()
  // A view transition is loaded by the active-view watcher after the manager
  // mounts.  Reload explicitly only when this command is used from inside the
  // already-open manager, otherwise two identical requests race on startup.
  await Promise.all([
    alreadyOpen ? loadWeChatSubscriptions() : Promise.resolve(),
  ])
}

function openReportSources({ source } = {}) {
  activeView.value = source === 'campus' ? 'campus' : source === 'rss' ? 'rss' : 'wechat'
}

async function refreshLibraryAfterRssChange() {
  await Promise.all([loadContentItems(), loadLibraryFolders()])
}

function openGeneratedReport(contentItemId) {
  const item = allContentItems.value.find((content) => content.id === contentItemId)
  if (item) openContentFromSidebar(item)
}

async function openSettings() {
  settingsInitialSection.value = 'appearance'
  showSettings.value = true
  await Promise.all([loadWeChatSubscriptions(), loadWechatPublishingSettings(), loadWechatQwenCoverSettings(), loadMediaTools(), loadRuntimeComponents(), loadDeepSeekSettings(), loadPaddleOcrSettings(), loadManualCollectionSettings(), loadFolderImportWatcherStatus()])
}

async function chooseObsidianFolder() {
  const folder = await window.knowledgeHubDesktop?.chooseDirectory?.()
  if (!folder) return
  obsidianVaultPath.value = folder
  await saveObsidianSettingsFromForm()
}

async function chooseMarkdownExportFolder() {
  const folder = await window.knowledgeHubDesktop?.chooseDirectory?.()
  if (!folder) return
  markdownExportPath.value = folder
  await saveObsidianSettingsFromForm()
}

function stopWeChatInitialSyncListPolling() {
  if (wechatInitialSyncListPollTimer) clearTimeout(wechatInitialSyncListPollTimer)
  wechatInitialSyncListPollTimer = null
}

function scheduleWeChatInitialSyncListPolling() {
  stopWeChatInitialSyncListPolling()
  if (!wechatSubscriptions.value.some((subscription) => subscription.last_run_status === 'running')) return
  wechatInitialSyncListPollTimer = setTimeout(() => {
    void refreshWeChatInitialSyncList()
  }, 1500)
}

async function refreshWeChatInitialSyncList() {
  try {
    const response = await axios.get(WECHAT_SUBSCRIPTION_API, { timeout: 10000 })
    wechatSubscriptions.value = Array.isArray(response.data) ? response.data : []
    scheduleWeChatInitialSyncListPolling()
  } catch {
    // The normal screen refresh keeps the visible error handling.  This
    // background progress poll should retry quietly on its next visit.
  }
}

async function loadWeChatSubscriptions({ silent = false } = {}) {
  const requestVersion = ++wechatSubscriptionsLoadVersion
  if (!silent) loadingWeChatSubscriptions.value = true
  try {
    const [accountsResponse, subscriptionsResponse, filtersResponse, groupsResponse] = await Promise.all([
      axios.get(`${WECHAT_SUBSCRIPTION_API}/accounts`, { timeout: 10000 }),
      axios.get(WECHAT_SUBSCRIPTION_API, { timeout: 10000 }),
      axios.get(WECHAT_FILTER_API, { timeout: 10000 }),
      axios.get(WECHAT_REPORT_GROUP_API, { timeout: 10000 })
    ])
    if (requestVersion !== wechatSubscriptionsLoadVersion) return
    wechatAccounts.value = Array.isArray(accountsResponse.data) ? accountsResponse.data : []
    wechatSubscriptions.value = Array.isArray(subscriptionsResponse.data) ? subscriptionsResponse.data : []
    wechatContentFilters.value = Array.isArray(filtersResponse.data) ? filtersResponse.data : []
    wechatReportGroups.value = Array.isArray(groupsResponse.data) ? groupsResponse.data : []
    // This data enriches the library tree only. It must not leave the whole
    //公众号管理页 in a loading state when its independent request is slow.
    void loadLibrarySourceGroups()
    reconcileSelectedAccount()
    scheduleWeChatInitialSyncListPolling()
  } catch (error) {
    if (requestVersion === wechatSubscriptionsLoadVersion && !silent) {
      ElMessage.error(wechatErrorMessage(error, '无法读取公众号订阅状态'))
    }
  } finally {
    if (!silent && requestVersion === wechatSubscriptionsLoadVersion) {
      loadingWeChatSubscriptions.value = false
    }
  }
}

async function importLocalMarkdown({ file, files, libraryFolderId = null } = {}) {
  const importFiles = Array.isArray(files) ? files : [file]
  const validFiles = importFiles.filter((candidate) => candidate instanceof File)
  if (!validFiles.length) return
  // Text documents are imported synchronously; OCR and ASR return a durable
  // task while keeping a visible placeholder in the same external folder.
  const processLogWasOpen = processLogOpen.value
  try {
    let lastItem = null
    let queuedCount = 0
    let importedCount = 0
    const failures = []
    for (const importFile of validFiles) {
      try {
        const body = new FormData()
        body.append('file', importFile)
        if (libraryFolderId) body.append('library_folder_id', libraryFolderId)
        // Large media is streamed by the backend; an arbitrary client timeout
        // would incorrectly turn a valid local import into a failure.
        const response = await axios.post(LIBRARY_LOCAL_FILE_IMPORT_API, body, { timeout: 0 })
        importedCount += 1
        lastItem = response.data?.item || lastItem
        if (response.data?.task_id) {
          queuedCount += 1
          batchTaskIds.value = [...new Set([...batchTaskIds.value, response.data.task_id])]
        }
      } catch (error) {
        const reason = wechatErrorMessage(error, '导入失败')
        failures.push(`${importFile.name}：${typeof reason === 'string' ? reason : '导入失败'}`)
      }
    }
    if (!importedCount) {
      ElMessage.error(failures[0] || '资料导入失败')
      return
    }
    await Promise.all([loadContentItems(), loadLibraryFolders(), loadLibrarySourceGroups()])
    if (validFiles.length === 1 && lastItem?.id) await openContentFromSidebar(lastItem)
    if (queuedCount) {
      processLogOpen.value = true
      void pollBatchTasks()
    } else processLogOpen.value = processLogWasOpen
    const summary = validFiles.length > 1
      ? `已导入 ${importedCount}/${validFiles.length} 份资料${queuedCount ? `，${queuedCount} 份正在处理` : ''}`
      : queuedCount ? '资料已加入处理队列' : '资料已导入资料库'
    if (failures.length) {
      ElMessage.warning(`${summary}；${failures.length} 份失败：${failures.slice(0, 2).join('；')}`)
    } else {
      ElMessage.success(summary)
    }
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '资料导入失败'))
  }
}

async function openOriginalFile(path) {
  const openPath = window.knowledgeHubDesktop?.openPath
  if (!openPath) {
    ElMessage.warning('请在桌面版中打开原始文件')
    return
  }
  try {
    await openPath(String(path || ''))
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '打开原始文件失败'))
  }
}

function statusbarDirectoryName(value) {
  const path = String(value || '').trim().replace(/[\\/]+$/u, '')
  if (!path) return '资料库'
  const segments = path.split(/[\\/]+/u).filter(Boolean)
  return segments.at(-1) || path
}

const statusbarBreadcrumbItems = computed(() => {
  if (activeView.value !== 'library') return []
  const content = activeWorkspaceContent.value || selectedContentItem.value
  if (!content?.id) return []

  const rootPath = obsidianVaultPath.value || markdownExportPath.value || ''
  const items = [{
    id: '__library_root__',
    kind: 'root',
    label: statusbarDirectoryName(rootPath),
    title: rootPath || '资料库写入目录',
    actionable: true,
  }]
  const foldersById = new Map(libraryFolders.value.map((folder) => [String(folder.id), folder]))
  const folders = []
  let folderId = content.library_folder_id ? String(content.library_folder_id) : ''
  const visited = new Set()
  while (folderId && foldersById.has(folderId) && !visited.has(folderId)) {
    visited.add(folderId)
    const folder = foldersById.get(folderId)
    folders.unshift(folder)
    folderId = folder?.parent_folder_id ? String(folder.parent_folder_id) : ''
  }
  for (const folder of folders) {
    items.push({
      id: `folder:${folder.id}`,
      kind: 'folder',
      label: String(folder.name || '未命名目录'),
      title: String(folder.name || '未命名目录'),
      folderId: String(folder.id),
      actionable: true,
    })
  }
  items.push({
    id: `content:${content.id}`,
    kind: 'content',
    label: String(content.title || content.canonical_source_id || '未命名资料'),
    title: String(content.title || content.canonical_source_id || '未命名资料'),
    current: true,
  })
  return items
})

function handleStatusBreadcrumbSelect(item) {
  if (!item?.actionable) return
  activeView.value = 'library'
  searchQuery.value = ''
  if (item.folderId) libraryFolderRevealIds.value = [item.folderId]
}

const cacheStatusItems = computed(() => {
  const entries = Array.isArray(allContentItems.value) ? allContentItems.value : []
  const todayStart = new Date()
  todayStart.setHours(0, 0, 0, 0)
  const tomorrowStart = new Date(todayStart)
  tomorrowStart.setDate(todayStart.getDate() + 1)
  const summary = entries.reduce((counts, item) => {
    if (item?.content_type === 'article') counts.article += 1
    else counts.video += 1
    const updatedAt = Date.parse(item?.updated_at || '')
    if (Number.isFinite(updatedAt) && updatedAt >= todayStart.getTime() && updatedAt < tomorrowStart.getTime()) counts.today += 1
    return counts
  }, { article: 0, video: 0, today: 0 })

  return [
    { label: '文章', value: summary.article.toLocaleString() },
    { label: '视频', value: summary.video.toLocaleString() },
    { label: '今日更新', value: summary.today.toLocaleString() },
  ]
})

const articlePreparationStatusLabel = computed(() => {
  const status = articlePreparationStatus.value || {}
  const webActive = Number(status.web_capture_active_count || 0)
  const webQueued = Number(status.web_capture_queued_count || 0)
  const wechatActive = Number(status.wechat_capture_active_count || 0)
  const wechatQueued = Number(status.wechat_capture_queued_count || 0)
  const ocrActive = Number(status.ocr_active_count || 0)
  const ocrQueued = Number(status.ocr_queued_count || 0)
  const web = webActive || webQueued
    ? `网页 ${webActive ? '处理中' : '等待'}${webQueued ? ` ${webQueued}` : ''}`
    : ''
  const wechat = wechatActive || wechatQueued
    ? `微信 ${wechatActive ? '处理中' : '等待'}${wechatQueued ? ` ${wechatQueued}` : ''}`
    : ''
  const ocr = ocrActive || ocrQueued
    ? `OCR ${ocrActive ? '处理中' : '等待'}${ocrQueued ? ` ${ocrQueued}` : ''}`
    : ''
  if (web || wechat || ocr) return [web, wechat, ocr].filter(Boolean).join(' · ')
  return '空闲'
})

const articlePreparationStatusTooltip = computed(() => {
  const status = articlePreparationStatus.value || {}
  const webActive = Number(status.web_capture_active_count || 0)
  const webQueued = Number(status.web_capture_queued_count || 0)
  const wechatActive = Number(status.wechat_capture_active_count || 0)
  const wechatQueued = Number(status.wechat_capture_queued_count || 0)
  const ocrActive = Number(status.ocr_active_count || 0)
  const ocrQueued = Number(status.ocr_queued_count || 0)
  const completedCount = Number(status.completed_count || 0)
  const failedCount = Number(status.failed_count || 0)
  const nextSlot = Number(status.next_wechat_slot_in_seconds || 0)
  const lines = [
    '网页与公众号使用独立抓取通道；图片 OCR 随后独立补全，不会阻塞文章阅读。',
    `网页：${webActive ? `处理中 ${webActive} 篇` : '空闲'}${webQueued ? `；等待 ${webQueued} 篇` : ''}。`,
    `微信公众号：${wechatActive ? `处理中 ${wechatActive} 篇` : '空闲'}${wechatQueued ? `；等待微信限额 ${wechatQueued} 篇` : ''}。`,
    `OCR：${ocrActive ? `处理中 ${ocrActive} 篇` : '空闲'}${ocrQueued ? `；等待 ${ocrQueued} 篇` : ''}。`,
    `本次服务已完成：${completedCount} 篇${failedCount ? `；失败：${failedCount} 篇` : ''}。`,
  ]
  if (wechatActive && nextSlot > 0) lines.push(`微信公众号下一次抓取间隔约 ${nextSlot.toFixed(1)} 秒。`)
  return lines.join('\n')
})

const aiTokenUsage = computed(() => {
  if (activeView.value === 'knowledge') {
    const usage = knowledgeConversationUsage.value || emptyKnowledgeConversationUsage()
    const callCount = Number(usage.call_count || 0)
    const totalTokens = Number(usage.total_tokens || 0)
    const promptTokens = Number(usage.prompt_tokens || 0)
    const completionTokens = Number(usage.completion_tokens || 0)
    const cacheHitTokens = Number(usage.prompt_cache_hit_tokens || 0)
    const cacheMissTokens = Number(usage.prompt_cache_miss_tokens || 0)
    const estimatedCost = Number(usage.estimated_cost || 0)
    const unreportedCount = Number(usage.unreported_count || 0)
    const hasReportedUsage = callCount > unreportedCount
    const parts = []
    if (hasReportedUsage) parts.push(formatTokenCount(totalTokens))
    else if (callCount) parts.push('Token 未返回')
    if (callCount) parts.push(`¥${formatCnyCost(estimatedCost)}`)
    return {
      label: parts.length ? `AI 用量：本对话 ${parts.join(' · ')}` : 'AI 用量：本对话等待调用',
      tooltip: [
        '当前知识库对话',
        `模型调用 ${callCount} 次 · 输入 ${hasReportedUsage ? (promptTokens ? formatTokenCount(promptTokens) : '0') : '未返回'} · 输出 ${hasReportedUsage ? (completionTokens ? formatTokenCount(completionTokens) : '0') : '未返回'} · 合计 ${hasReportedUsage ? (totalTokens ? formatTokenCount(totalTokens) : '0') : callCount ? '未返回' : '0'} tokens`,
        `提示缓存 · 命中 ${cacheHitTokens ? formatTokenCount(cacheHitTokens) : '0'} · 未命中 ${cacheMissTokens ? formatTokenCount(cacheMissTokens) : '0'}`,
        `本机估算费用 · ¥${formatCnyCost(estimatedCost)}`,
        ...(unreportedCount ? [`${unreportedCount} 次调用未返回 Token，用量未纳入合计。`] : []),
      ].join('\n'),
      hasUsage: totalTokens > 0,
      hasUnreportedUsage: unreportedCount > 0,
      toggleLabel: '当前知识库对话的 AI 用量',
    }
  }
  const daily = dailyAiTokenUsage.value || {}
  const dailyCallCount = Number(daily.call_count || 0)
  const dailyTotal = Number(daily.total_tokens || 0)
  const dailyPrompt = Number(daily.prompt_tokens || 0)
  const dailyCompletion = Number(daily.completion_tokens || 0)
  const dailyUnreported = Number(daily.unreported_count || 0)
  const dailyCacheHit = Number(daily.prompt_cache_hit_tokens || 0)
  const dailyCacheMiss = Number(daily.prompt_cache_miss_tokens || 0)
  const dailyEstimatedCost = Number(daily.estimated_cost || 0)
  const dailyImageCallCount = Number(daily.image_call_count || 0)
  const dailyImageCount = Number(daily.image_count || 0)
  const dailyImageEstimatedCost = Number(daily.image_estimated_cost || 0)
  const openClaw = openClawTokenUsage.value || {}
  const openClawAvailable = Boolean(openClaw.available)
  const openClawTotal = Number(openClaw.total_tokens || 0)
  const openClawInput = Number(openClaw.input_tokens || 0)
  const openClawOutput = Number(openClaw.output_tokens || 0)
  const openClawCacheRead = Number(openClaw.cache_read_tokens || 0)
  const openClawCalls = Number(openClaw.model_response_count || 0)
  const openClawSessions = Number(openClaw.session_count || 0)
  const openClawCost = Number(openClaw.estimated_cost_usd || 0)
  const openClawLines = openClawAvailable
    ? [
        `OpenClaw 当前会话 · ${openClawSessions} 条 · ${openClawCalls} 次模型响应`,
        `模型调用：输入 ${formatTokenCount(openClawInput)} · 输出 ${formatTokenCount(openClawOutput)} · 缓存读取 ${formatTokenCount(openClawCacheRead)} · 合计 ${formatTokenCount(openClawTotal)}`,
        openClawCost > 0 ? `服务商已报告成本：US$${openClawCost.toFixed(4)}` : '服务商未返回可计费金额；Token 总量已统计。',
        ...(Array.isArray(openClaw.sessions) ? openClaw.sessions.map((session) => {
          const model = [session.provider, session.model].filter(Boolean).join('/') || '未知模型'
          return `${session.label || '会话'} · ${model} · ${formatTokenCount(Number(session.total_tokens || 0))}`
        }) : [])
      ]
    : [String(openClaw.reason || 'OpenClaw 用量暂不可读取。')]

  const tooltipLines = [
    '文本模型（Token 计量）',
    ...(dailyCallCount
      ? [
          `今日 ${dailyCallCount} 次 · 输入 ${formatTokenCount(dailyPrompt)} · 输出 ${formatTokenCount(dailyCompletion)} · 合计 ${formatTokenCount(dailyTotal)}`,
          `提示缓存 · 命中 ${formatTokenCount(dailyCacheHit)} · 未命中 ${formatTokenCount(dailyCacheMiss)}`,
          `本机估算费用 · ¥${formatCnyCost(dailyEstimatedCost)}`,
          ...modelUsageTooltipLines(daily.by_model)
        ]
      : ['今日尚未产生文本模型调用。']),
    '',
    '图像模型（按张计量）',
    ...(dailyImageCount
      ? [
          `今日 ${dailyImageCallCount} 次请求 · 生成 ${dailyImageCount} 张`,
          `目录价估算 · ¥${formatCnyCost(dailyImageEstimatedCost)}`,
          ...imageUsageTooltipLines(daily.by_image_model),
          '实际扣费可能受免费额度或折扣影响，请以百炼账单为准。'
        ]
      : ['今日尚未产生图像生成调用。'])
  ]

  const calls = Array.isArray(activeContentAiCalls.value) ? activeContentAiCalls.value : []
  const tokenCalls = calls.filter((call) => String(call.usage_unit || 'tokens') !== 'images')
  const imageCalls = calls.filter((call) => String(call.usage_unit || '') === 'images')
  const currentContentTitle = String(activeWorkspaceContent.value?.title || result.display_title || result.source_title || '当前内容').trim()
  const hasCurrentContent = Boolean(activeWorkspaceContent.value?.id || result.content_item_id)
  const showCurrent = aiTokenDisplayMode.value === 'current' && hasCurrentContent
  if (!showCurrent) {
    const dailyParts = []
    if (dailyCallCount && dailyTotal > 0) dailyParts.push(formatTokenCount(dailyTotal))
    else if (dailyCallCount) dailyParts.push('Token 未返回')
    if (dailyImageCount) dailyParts.push(`图 ${dailyImageCount} 张`)
    const label = dailyParts.length ? `AI 用量：今日 ${dailyParts.join(' · ')}` : 'AI 用量：今日等待调用'
    return {
      label,
      tooltip: [...tooltipLines, '', ...openClawLines, '', hasCurrentContent ? '点击切换为当前内容用量。' : '打开一篇文章或视频后可查看当前内容用量。'].join('\n'),
      hasUsage: dailyTotal > 0 || dailyImageCount > 0 || openClawTotal > 0,
      hasUnreportedUsage: dailyUnreported > 0,
      toggleLabel: hasCurrentContent ? '切换为当前内容 AI 用量' : '当前没有可切换的内容'
    }
  }

  const normalizedCalls = tokenCalls.map((call) => {
    const prompt = optionalUsageMetric(call.prompt_tokens)
    const completion = optionalUsageMetric(call.completion_tokens)
    const reportedTotal = optionalUsageMetric(call.total_tokens)
    const derivedTotal = prompt !== null && completion !== null ? prompt + completion : null
    const total = reportedTotal ?? derivedTotal
    const cacheHit = optionalUsageMetric(call.prompt_cache_hit_tokens)
    const cacheMiss = optionalUsageMetric(call.prompt_cache_miss_tokens)
    const cost = Number(call.estimated_cost)
    return {
      prompt,
      completion,
      total,
      cacheHit,
      cacheMiss,
      cost: Number.isFinite(cost) ? cost : null,
      provider: String(call.provider || 'unknown'),
      model: String(call.model || 'unknown')
    }
  })
  const reportedCalls = normalizedCalls.filter((call) => call.total !== null)
  const totalTokens = reportedCalls.reduce((sum, call) => sum + call.total, 0)
  const hasUnreportedUsage = reportedCalls.length !== normalizedCalls.length
  const cacheReportedCalls = normalizedCalls.filter((call) => call.cacheHit !== null || call.cacheMiss !== null)
  const cacheHitTokens = cacheReportedCalls.reduce((sum, call) => sum + (call.cacheHit || 0), 0)
  const cacheMissTokens = cacheReportedCalls.reduce((sum, call) => sum + (call.cacheMiss || 0), 0)
  const currentEstimatedCost = normalizedCalls.reduce((sum, call) => sum + (call.cost || 0), 0)
  const currentByModel = new Map()
  for (const call of normalizedCalls) {
    const key = `${call.provider}\u0000${call.model}`
    const aggregate = currentByModel.get(key) || {
      provider: call.provider,
      model: call.model,
      count: 0,
      prompt: 0,
      completion: 0,
      total: 0,
      cacheHit: 0,
      cacheMiss: 0,
      cost: 0,
      unreported: 0
    }
    aggregate.count += 1
    if (call.prompt !== null) aggregate.prompt += call.prompt
    if (call.completion !== null) aggregate.completion += call.completion
    if (call.total !== null) aggregate.total += call.total
    else aggregate.unreported += 1
    if (call.cacheHit !== null) aggregate.cacheHit += call.cacheHit
    if (call.cacheMiss !== null) aggregate.cacheMiss += call.cacheMiss
    if (call.cost !== null) aggregate.cost += call.cost
    currentByModel.set(key, aggregate)
  }
  const detailLines = modelUsageTooltipLines([...currentByModel.values()].map((aggregate) => ({
    provider: aggregate.provider,
    model: aggregate.model,
    call_count: aggregate.count,
    prompt_tokens: aggregate.prompt,
    completion_tokens: aggregate.completion,
    total_tokens: aggregate.total,
    prompt_cache_hit_tokens: aggregate.cacheHit,
    prompt_cache_miss_tokens: aggregate.cacheMiss,
    estimated_cost: aggregate.cost,
    unreported_count: aggregate.unreported
  })))
  const currentImageCount = imageCalls.reduce((sum, call) => sum + Math.max(0, Number(call.image_count || 0)), 0)
  const currentImageEstimatedCost = imageCalls.reduce((sum, call) => sum + Math.max(0, Number(call.estimated_cost || 0)), 0)
  const currentLabelParts = []
  if (reportedCalls.length) currentLabelParts.push(formatTokenCount(totalTokens))
  else if (normalizedCalls.length) currentLabelParts.push('Token 未返回')
  if (currentImageCount) currentLabelParts.push(`图 ${currentImageCount} 张`)

  return {
    label: currentLabelParts.length ? `AI 用量：当前 ${currentLabelParts.join(' · ')}` : 'AI 用量：当前等待调用',
    tooltip: [
      `当前内容 · ${currentContentTitle}`,
      '',
      '文本模型（Token 计量）',
      `调用 ${normalizedCalls.length} 次 · 合计 ${reportedCalls.length ? formatTokenCount(totalTokens) : normalizedCalls.length ? '未返回' : '0'} tokens`,
      cacheReportedCalls.length
        ? `提示缓存 · 命中 ${formatTokenCount(cacheHitTokens)} · 未命中 ${formatTokenCount(cacheMissTokens)}`
        : '提示缓存：旧调用或服务未返回命中数据。',
      `本机估算费用 · ¥${formatCnyCost(currentEstimatedCost)}`,
      ...detailLines,
      '',
      '图像模型（按张计量）',
      ...(currentImageCount
        ? [
            `调用 ${imageCalls.length} 次 · 生成 ${currentImageCount} 张`,
            `目录价估算 · ¥${formatCnyCost(currentImageEstimatedCost)}`,
            ...imageUsageTooltipLines(imageCalls.map((call) => ({ ...call, call_count: 1 }))),
            '实际扣费可能受免费额度或折扣影响，请以百炼账单为准。'
          ]
        : ['当前内容尚未产生图像生成调用。']),
      '',
      ...openClawLines,
      '',
      '点击切换为今日总计。'
    ].join('\n'),
    hasUsage: totalTokens > 0 || currentImageCount > 0,
    hasUnreportedUsage,
    toggleLabel: '切换为今日总计 AI 用量'
  }
})

const aiTokenDisplayMode = ref('current')

function toggleAiTokenDisplayMode() {
  if (activeView.value === 'knowledge') return
  if (!activeWorkspaceContent.value?.id && !result.content_item_id) return
  aiTokenDisplayMode.value = aiTokenDisplayMode.value === 'current' ? 'total' : 'current'
}

watch(() => activeWorkspaceContent.value?.id, (contentItemId, previousContentItemId) => {
  if (contentItemId && contentItemId !== previousContentItemId) aiTokenDisplayMode.value = 'current'
})

function optionalUsageMetric(value) {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatCnyCost(value) {
  const cost = Number(value)
  if (!Number.isFinite(cost) || cost <= 0) return '0.0000'
  return cost < 0.0001 ? '<0.0001' : cost.toFixed(4)
}

function aiModelDisplayName(provider, model) {
  const modelName = String(model || 'unknown').trim() || 'unknown'
  const providerName = String(provider || 'unknown').trim() || 'unknown'
  const displayModel = {
    'deepseek-v4-flash': 'V4 Flash',
    'deepseek-v4-pro': 'V4 Pro'
  }[modelName] || modelName
  const displayProvider = providerName === 'deepseek' ? 'DeepSeek' : providerName
  return `${displayProvider} · ${displayModel}`
}

function modelUsageTooltipLines(items) {
  const modelItems = Array.isArray(items) ? items : []
  if (!modelItems.length) return ['暂无已返回用量的模型明细。']
  return modelItems.map((item) => {
    const suffix = Number(item.unreported_count || 0) ? ` · ${Number(item.unreported_count)} 次未返回用量` : ''
    return [
      `${aiModelDisplayName(item.provider, item.model)} · ${Number(item.call_count || 0)} 次${suffix}`,
      `输入 ${formatTokenCount(Number(item.prompt_tokens || 0))} · 输出 ${formatTokenCount(Number(item.completion_tokens || 0))} · 合计 ${formatTokenCount(Number(item.total_tokens || 0))}`,
      `缓存命中 ${formatTokenCount(Number(item.prompt_cache_hit_tokens || 0))} · 未命中 ${formatTokenCount(Number(item.prompt_cache_miss_tokens || 0))} · ¥${formatCnyCost(item.estimated_cost)}`
    ].join('\n')
  })
}

function imageUsageTooltipLines(items) {
  const modelItems = Array.isArray(items) ? items : []
  if (!modelItems.length) return ['暂无图像生成明细。']
  return modelItems.map((item) => {
    const count = Math.max(0, Number(item.image_count || 0))
    const callCount = Math.max(0, Number(item.call_count || 0))
    const width = Math.max(0, Number(item.image_width || 0))
    const height = Math.max(0, Number(item.image_height || 0))
    const dimensions = width && height ? ` · ${width}×${height}` : ''
    const region = String(item.billing_region || '') === 'international' ? '国际站' : '中国内地'
    const requestId = String(item.request_id || '').trim()
    const requestLine = requestId ? `\n请求 ID · ${requestId}` : ''
    const unitPrice = Number(item.unit_price_cny)
    const price = Number.isFinite(unitPrice) && unitPrice > 0 ? ` · 目录价 ¥${formatCnyCost(unitPrice)}/张` : ''
    return `${aiModelDisplayName(item.provider, item.model)} · ${callCount || 1} 次 · ${count} 张${dimensions}\n${region}${price} · 估算 ¥${formatCnyCost(item.estimated_cost)}${requestLine}`
  })
}

const showPrimaryPane = computed(() => {
  return !isSinglePaneWorkspaceView(activeView.value) && primarySidebarOpen.value
})

const showContextPane = computed(() => {
  return ['library', 'knowledge'].includes(activeView.value)
    && contextSidebarOpen.value
    && (activeView.value === 'library' || Boolean(knowledgeEvidence.value))
})

const workspaceChromeActionProps = computed(() => ({
  openclawStatusText: openclawStatusText.value,
  openclawRunning: openclawRunning.value,
  openclawScanning: openclawScanning.value,
  startupBlocking: startupBlocking.value,
  clipboardWatching: clipboardWatching.value,
  clipboardScanning: clipboardScanning.value,
  activeView: activeView.value,
  contextSidebarOpen: contextSidebarOpen.value,
  processLogOpen: processLogOpen.value,
}))

const editorPaneSize = computed(() => {
  const primarySize = showPrimaryPane.value ? workspaceLayout.primary : 0
  const contextSize = showContextPane.value ? workspaceLayout.context : 0
  return Math.max(18, 100 - primarySize - contextSize)
})

async function openLibrarySidebar() {
  activeView.value = 'library'
  setPrimarySidebarOpen(true)
  await nextTick()
}

function setPrimarySidebarOpen(open, event) {
  const next = Boolean(open)
  if (primarySidebarOpen.value === next || primaryPaneTransitioning.value) return
  const origin = event?.currentTarget?.getBoundingClientRect?.()
  if (origin) workbenchShell.value?.beginPrimaryToggleMotion?.(origin, next)
  // The collapse control belongs to different headers in the open and
  // collapsed layouts. Do not render either copy while Splitpanes animates,
  // otherwise their distinct positioning contexts visibly hand off mid-frame.
  primaryPaneTransitioning.value = true
  primarySidebarOpen.value = next
}

function handlePaneVisibilityTransitionEnd({ side } = {}) {
  if (side === 'primary') primaryPaneTransitioning.value = false
}

async function showLibraryFiles() {
  librarySidebarMode.value = 'files'
  await openLibrarySidebar()
  primarySidebar.value?.showLibraryFiles?.()
}

async function focusLibrarySearch() {
  librarySidebarMode.value = 'search'
  await openLibrarySidebar()
  primarySidebar.value?.showLibrarySearch?.()
}

function handlePaneSnapCollapse(side) {
  if (side === 'primary') {
    setPrimarySidebarOpen(false)
    return
  }
  if (side === 'context') contextSidebarOpen.value = false
}

function handlePaneSnapOpen(side) {
  if (side === 'primary') {
    workspaceLayout.primary = Math.max(workspaceLayout.primary, minimumSidebarPercent())
    setPrimarySidebarOpen(true)
    return
  }
  if (side === 'context' && ['library', 'knowledge'].includes(activeView.value)) {
    workspaceLayout.context = Math.max(workspaceLayout.context, minimumSidebarPercent())
    contextSidebarOpen.value = true
  }
}

function handlePaneDragResize({ side, size } = {}) {
  const nextSize = Number(size)
  if (!Number.isFinite(nextSize)) return

  if (side === 'primary') {
    const visibleContextSize = showContextPane.value ? workspaceLayout.context : 0
    workspaceLayout.primary = Math.max(8, Math.min(45, 82 - visibleContextSize, nextSize))
  } else if (side === 'context' && ['library', 'knowledge'].includes(activeView.value)) {
    const visiblePrimarySize = showPrimaryPane.value ? workspaceLayout.primary : 0
    workspaceLayout.context = Math.max(12, Math.min(65, 82 - visiblePrimarySize, nextSize))
  } else {
    return
  }

  workspaceLayout.editor = Math.max(
    18,
    100
      - (showPrimaryPane.value ? workspaceLayout.primary : 0)
      - (showContextPane.value ? workspaceLayout.context : 0)
  )
}

function minimumSidebarPercent() {
  const availableWidth = Math.max(600, window.innerWidth - 48)
  return Math.max(8, (200 / availableWidth) * 100)
}

watch(activeView, (view, previousView) => {
  void axios.post(`${API}/telemetry/events`, {
    event_name: 'workspace_opened',
    properties: { view: String(view || 'unknown').slice(0, 40) },
  }, { timeout: 2000 }).catch(() => {})
  // 管理、提示词等页面不需要以 2 秒频率刷新整个任务队列；保留低频刷新即可。
  // 编辑器仍维持实时反馈，避免处理中的任务看起来停滞。
  setTaskQueuePollingInterval(view === 'library' ? 2000 : 15000)
  if (view === 'library' && previousView && previousView !== 'library') {
    contextSidebarOpen.value = true
  }
  if (view === 'wechat' && previousView !== 'wechat') {
    nextTick(() => {
      if (activeView.value === 'wechat') void loadWeChatSubscriptions()
    })
  }
  if (view === 'reports' && previousView !== 'reports') {
    loadWeChatSubscriptions()
  }
  if (view === 'campus' && previousView !== 'campus') {
    Promise.all([
      loadCampusAccessStatus({ silent: true }),
      loadCampusSources({ silent: true })
    ])
  }
}, { immediate: true })

watch(allContentItems, () => {
  loadLibrarySourceGroups()
}, { immediate: true })

watch(activeView, (view) => {
  if (view === 'prompts') {
    Promise.all([
      loadPromptWorkspaceData(),
      loadWeChatSubscriptions().then(loadWechatReportPrompts),
      loadPromptTrash(),
    ])
  }
})

watch(showSettings, (isOpen) => {
  if (!isOpen) {
    stopWeChatQrPolling()
    return
  }
  void loadFolderImportWatcherStatus()
  if (wechatQrLogin.value.login_id) scheduleWeChatQrPoll()
})

watch(activeWorkspaceTab, (tab, previousTab) => {
  if (activeView.value === 'library' && tab?.id && tab.id !== previousTab?.id) {
    contextSidebarOpen.value = true
  }
})

watch(processLogOpen, (value) => {
  localStorage.setItem(PROCESS_LOG_OPEN_KEY, String(value))
})

watch(processLogHeight, (value) => {
  const height = Math.max(150, Math.min(360, Number(value) || 240))
  localStorage.setItem(PROCESS_LOG_HEIGHT_KEY, String(height))
})

watch([primarySidebarOpen, contextSidebarOpen], ([primary, context]) => {
  localStorage.setItem(WORKSPACE_PANE_VISIBILITY_KEY, JSON.stringify({ primary, context }))
})

onBeforeUnmount(() => {
  disposeWechatReportGenerationController()
  disposeWechatAccountController()
  disposeWechatCoverController()
  disposeWechatDraftController()
  stopWeChatInitialSyncListPolling()
})

</script>

<style scoped src="./styles/app.css"></style>
