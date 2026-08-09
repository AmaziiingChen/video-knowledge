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
            :running="running"
            :result="result"
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
            :format-token-count="formatTokenCount"
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
            :current-obsidian-path="currentObsidianPath"
            :conversation-key="activeWorkspaceContent?.id || result.content_item_id || ''"
            :markdown-state="markdownState"
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
            :last-qa-saved="lastQaSaved"
            :task-status="taskStatus"
            :has-task-progress="hasTaskProgress"
            :current-stage-label="currentStageLabel"
            :result="result"
            :total-elapsed="totalElapsed"
            :selected-ai-model="assistantAiModel"
            :available-ai-models="availableAiModels"
            :markdown-sync-label="markdownSyncLabel"
            :render-markdown="renderMarkdown"
            :status-tag-type="statusTagType"
            :status-label="statusLabel"
            :model-label="modelLabel"
            :format-seconds="formatSeconds"
            :rounded-progress="roundedProgress"
            :progress-status="progressStatus"
            @open-markdown="openMarkdownDialog"
            @copy-link="copyText($event, '链接已复制')"
            @update:selected-ai-model="assistantAiModel = $event"
            @new-chat="startNewChat"
            @generate-ai-summary="generateAiSummary"
            @ask-question="askQuestion"
            @clear-selected-text-context="clearSelectedTextContext"
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
import { computed, defineAsyncComponent, h, nextTick, onBeforeUnmount, ref, watch } from 'vue'
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
import EditorHost from './workbench/EditorHost.vue'
import ProcessLogDock from './workbench/ProcessLogDock.vue'
import PrimarySidebar from './workbench/PrimarySidebar.vue'
import { normalizeWorkspacePaneVisibility } from './workbench/paneVisibilityState.js'
import { isSinglePaneWorkspaceView } from './workbench/workspaceViewLoading.js'
import { formatReportTaskWindow } from './features/reports/reportGenerationPresentation.js'
import SecondarySidebar from './features/assistant/SecondarySidebar.vue'
import { useAppController } from './composables/useAppController'
import { useCampusAccess } from './composables/useCampusAccess'
import { useRuntimeSettingsController } from './features/settings/useRuntimeSettingsController.js'
import { requestDestructiveConfirmation } from './composables/useDestructiveConfirm'
import { enqueueSourceSyncTask, observeSourceSyncTask } from './utils/sourceSyncTask'
import { promptTaskContracts, promptTemplateDisplayName } from './config/promptInterface'
import { WECHAT_COVER_STYLE_OPTIONS } from './config/wechatCoverStyles'
import { useWechatCoverController } from './features/wechat/useWechatCoverController.js'
import { useWechatDraftController } from './features/wechat/useWechatDraftController.js'
import { useWechatPublishingSettingsController } from './features/wechat/useWechatPublishingSettingsController.js'

const loadWeChatManager = () => import('./features/wechat/WeChatManager.vue')
const loadCampusManager = () => import('./features/campus/CampusManager.vue')
const loadCreatorWorkspace = () => import('./features/creator/CreatorWorkspace.vue')
const loadRssWorkspace = () => import('./features/rss/RssWorkspace.vue')
const loadReportsWorkspace = () => import('./features/reports/ReportsWorkspace.vue')
const loadKnowledgeWorkspace = () => import('./features/knowledge/KnowledgeWorkspace.vue')
const loadKnowledgeSidebar = () => import('./features/knowledge/KnowledgeSidebar.vue')
const loadEvidencePreviewSidebar = () => import('./features/knowledge/EvidencePreviewSidebar.vue')
const WeChatManager = defineAsyncComponent(loadWeChatManager)
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
  retryingContentId,
  libraryFolders,
  libraryFolderHistoryStates,
  libraryFolderRevealIds,
  allContentItems,
  contentPagesLoading,
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
  statusForTab,
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
  openMarkdownDialog,
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
  clearSelectedTextContext,
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
    const response = await fetch(`${API}/knowledge/v2/evidence/${encodeURIComponent(chunkId)}`)
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
const WECHAT_REPORT_PROMPT_API = `${API}/wechat-report-prompts`
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
const librarySourceGroups = ref([])
const sourceGroupEditor = ref(null)
const showSourceGroupEditor = ref(false)
const removingSourceGroupKey = ref('')
const wechatGeneratingGroupId = ref('')
const wechatPreparingGroupId = ref('')
const wechatDeletingGroupId = ref('')
const wechatSavingScheduleGroupId = ref('')
const reportGenerationDialog = ref({
  visible: false,
  phase: 'checking',
  requestId: '',
  reportKey: '',
  reportLabel: '报告',
  groupName: '',
  preflight: null,
})
let reportGenerationRequestSequence = 0
let reportGenerationConfirmationResolver = null
let reportPreflightRequest = null
let wechatPreparingRequestId = ''
const wechatReportPrompts = ref([])
const fixedSystemPrompts = ref([])
const selectedWechatReportPromptGroupId = ref('')
const selectedWechatReportPromptType = ref('group_context')
const wechatReportPromptText = ref('')
const loadingWechatReportPrompts = ref(false)
const savingWechatReportPrompt = ref(false)
const promptWorkspaceTemplates = ref([])
const promptFolders = ref([])
const promptWorkspaceTabs = ref([])
const activePromptTabId = ref('')
let promptWorkspaceActivationSequence = 0
let promptWorkspaceEditorSyncDepth = 0
const promptTrashEntries = ref([])
const loadingPromptTrash = ref(false)
// Configurable prompts live in their feature folders, where they can be edited and
// activated.  Keep this read-only section for the small set of fixed system rules.
const systemPromptEntries = computed(() => fixedSystemPrompts.value)
const promptContextEntries = computed(() => wechatReportPrompts.value
  .filter((prompt) => prompt.report_type === 'group_context')
  .map((prompt) => ({
    id: `context:${prompt.id}`,
    category: `分组报告 · ${prompt.group_name || '未命名分组'}`,
    name: String(prompt.display_name || '组别说明'),
    description: '随每个生成阶段作为 user 任务上下文发送；不是 system prompt。',
    template: prompt.template || '',
  })))
const activePromptNodeId = computed(() => {
  const tab = promptWorkspaceTabs.value.find((item) => item.id === activePromptTabId.value)
  if (!tab) return ''
  if (tab.kind === 'system') return `system:${tab.systemPromptId}`
  if (tab.kind === 'context') return `context:${tab.systemPromptId}`
  return tab.kind === 'report' ? `report:${tab.reportPromptId}` : tab.promptId ? `prompt:${tab.promptId}` : tab.id
})
const savingWeChatFilter = ref(false)
const selectedWeChatAccountId = ref('')
const wechatAccountDisplayName = ref('微信公众平台账号')
const wechatQrLogin = ref({ login_id: '', status: '', message: '', qr_image_data_url: '' })
const wechatQrStarting = ref(false)
const wechatManualToken = ref('')
const wechatManualCookie = ref('')
const wechatManualConnecting = ref(false)
const wechatSearchQuery = ref('')
const wechatSearchResults = ref([])
const wechatSearching = ref(false)
const wechatSubscriptionInterval = ref(1440)
const wechatAutoProcess = ref(false)
const wechatSubscriptionStates = ref({})
const syncingWeChatSubscriptionId = ref('')
const wechatBulkSyncState = ref({ status: 'idle', total: 0, completed: 0, succeeded: 0, failed: 0, skipped: 0, imported_count: 0, incomplete_count: 0 })
const refreshingWeChatProfileId = ref('')
const wechatSubscriptionUpdateRevision = new Map()
const wechatSyncIntervalOptions = [
  { label: '每 6 小时', value: 360 },
  { label: '每 12 小时', value: 720 },
  { label: '每天', value: 1440 }
]
let wechatQrPollTimer = null
let wechatBulkSyncPollTimer = null
let wechatBulkProgressRefreshKey = ''
let wechatBulkProgressRefreshInFlight = false
const wechatInitialSyncPollTimers = new Map()
const wechatInitialSyncImportedCounts = new Map()
let wechatInitialSyncListPollTimer = null
let wechatIncrementalLibraryRefreshInFlight = false
let wechatIncrementalLibraryRefreshQueued = false

function wechatErrorMessage(error, fallback = '微信公众号订阅操作失败') {
  return error?.response?.data?.detail || error?.message || fallback
}

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
    if (!wechatAccounts.value.some((account) => account.id === selectedWeChatAccountId.value)) {
      selectedWeChatAccountId.value = wechatAccounts.value[0]?.id || ''
    }
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

async function loadLibrarySourceGroups() {
  try {
    const response = await axios.get(LIBRARY_SOURCE_GROUPS_API, { timeout: 10000 })
    librarySourceGroups.value = Array.isArray(response.data) ? response.data : []
  } catch {
    // Source groups are an additional library view and must not block core content loading.
  }
}

async function openSourceGroupEditor(group) {
  if (!group?.id) return
  await loadLibrarySourceGroups()
  sourceGroupEditor.value = librarySourceGroups.value.find((item) => String(item.id) === String(group.id)) || {
    ...group,
    sources: [],
  }
  showSourceGroupEditor.value = true
}

async function removeSourceFromGroup(source) {
  const group = sourceGroupEditor.value
  const sourceId = String(source?.source_id || '').trim()
  const sourceKind = String(source?.kind || '').trim()
  if (!group?.id || !sourceId || !sourceKind || removingSourceGroupKey.value) return

  const sourceLabel = source.label || '这个来源'
  const confirmed = await requestDestructiveConfirmation({
    title: '移出分组',
    message: `将“${sourceLabel}”移出“${group.name}”？原来源与已收集内容会保留。`,
    confirmLabel: '移出分组',
    cancelLabel: '保留',
  })
  if (!confirmed) return

  const removalKey = `${sourceKind}:${sourceId}`
  removingSourceGroupKey.value = removalKey
  try {
    await axios.delete(
      `${LIBRARY_SOURCE_GROUPS_API}/${encodeURIComponent(group.id)}/sources/${encodeURIComponent(sourceKind)}/${encodeURIComponent(sourceId)}`,
      { timeout: 10000 },
    )
    await Promise.all([loadLibrarySourceGroups(), loadWeChatSubscriptions(), loadCampusSources({ silent: true })])
    const refreshedGroup = librarySourceGroups.value.find((item) => String(item.id) === String(group.id)) || null
    if (refreshedGroup) {
      sourceGroupEditor.value = refreshedGroup
    } else {
      showSourceGroupEditor.value = false
      sourceGroupEditor.value = null
    }
    ElMessage.success(`已将“${sourceLabel}”移出“${group.name}”`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '移出分组失败'))
  } finally {
    if (removingSourceGroupKey.value === removalKey) removingSourceGroupKey.value = ''
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

function syncWechatReportPromptEditor() {
  if (!wechatReportGroups.value.some((group) => group.id === selectedWechatReportPromptGroupId.value)) {
    selectedWechatReportPromptGroupId.value = wechatReportGroups.value[0]?.id || ''
  }
  const hasSelectedAdapter = wechatReportPrompts.value.some((item) => (
    item.group_id === selectedWechatReportPromptGroupId.value
    && item.report_type === selectedWechatReportPromptType.value
  ))
  if (!hasSelectedAdapter) selectedWechatReportPromptType.value = 'group_context'
  const current = wechatReportPrompts.value.find((item) => (
    item.group_id === selectedWechatReportPromptGroupId.value
    && item.report_type === selectedWechatReportPromptType.value
  ))
  wechatReportPromptText.value = current?.template || ''
}

async function loadWechatReportPrompts() {
  loadingWechatReportPrompts.value = true
  try {
    const response = await axios.get(WECHAT_REPORT_PROMPT_API, { timeout: 10000 })
    wechatReportPrompts.value = Array.isArray(response.data) ? response.data : []
    syncWechatReportPromptEditor()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '无法读取分组报告提示词'))
  } finally {
    loadingWechatReportPrompts.value = false
  }
}

function selectWechatReportPromptGroup(groupId) {
  selectedWechatReportPromptGroupId.value = groupId
  syncWechatReportPromptEditor()
}

function selectWechatReportPromptType(reportType) {
  selectedWechatReportPromptType.value = reportType
  syncWechatReportPromptEditor()
}

async function saveWechatReportPrompt() {
  const groupId = selectedWechatReportPromptGroupId.value
  const reportType = selectedWechatReportPromptType.value
  const template = wechatReportPromptText.value.trim()
  if (!groupId || !template) {
    ElMessage.warning('请选择分组并填写提示词')
    return false
  }
  savingWechatReportPrompt.value = true
  try {
    await axios.put(`${WECHAT_REPORT_GROUP_API}/${groupId}/prompts/${reportType}`, { template }, { timeout: 10000 })
    await loadWechatReportPrompts()
    ElMessage.success('区间报告提示词已保存')
    return true
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '保存报告提示词失败'))
    return false
  } finally {
    savingWechatReportPrompt.value = false
  }
}

function activePromptWorkspaceTab() {
  return promptWorkspaceTabs.value.find((tab) => tab.id === activePromptTabId.value) || null
}

function captureActivePromptDraft() {
  if (promptWorkspaceEditorSyncDepth > 0) return
  const tab = activePromptWorkspaceTab()
  if (!tab) return
  if (tab.kind === 'system' || tab.kind === 'context') return
  if (tab.kind === 'report') {
    tab.draftText = wechatReportPromptText.value
  } else {
    tab.draftName = promptEditorName.value
    tab.draftText = promptEditorText.value
  }
  tab.dirty = promptWorkspaceTabDirty(tab)
}

function promptWorkspaceTabDirty(tab) {
  if (!tab) return false
  if (tab.kind === 'system' || tab.kind === 'context') return false
  if (tab.isNew) return Boolean(String(tab.draftName || '').trim() || String(tab.draftText || '').trim())
  if (tab.kind === 'report') return tab.draftText !== tab.originalText
  return tab.draftName !== tab.originalName || tab.draftText !== tab.originalText
}

function reconcilePromptWorkspaceTabs() {
  const templateMap = new Map(promptWorkspaceTemplates.value.map((template) => [template.id, template]))
  const reportMap = new Map(wechatReportPrompts.value.map((prompt) => [prompt.id, prompt]))
  const systemMap = new Map(systemPromptEntries.value.map((prompt) => [prompt.id, prompt]))
  const contextMap = new Map(promptContextEntries.value.map((prompt) => [prompt.id, prompt]))
  promptWorkspaceTabs.value = promptWorkspaceTabs.value
    .filter((tab) => tab.isNew || (
      tab.kind === 'report'
        ? reportMap.has(tab.reportPromptId)
        : tab.kind === 'system'
          ? systemMap.has(tab.systemPromptId)
          : tab.kind === 'context'
            ? contextMap.has(tab.systemPromptId)
          : templateMap.has(tab.promptId)
    ))
    .map((tab) => {
      const source = tab.kind === 'report'
        ? reportMap.get(tab.reportPromptId)
        : tab.kind === 'system'
          ? systemMap.get(tab.systemPromptId)
          : tab.kind === 'context'
            ? contextMap.get(tab.systemPromptId)
          : templateMap.get(tab.promptId)
      if (!source) return tab
      return {
        ...tab,
        title: tab.kind === 'report'
          ? String(source.display_name || '区间报告')
          : tab.kind === 'system'
            ? String(source.name || '系统提示词')
          : tab.kind === 'context'
            ? String(source.name || '任务上下文')
          : promptTemplateDisplayName(source),
        originalText: ['system', 'context'].includes(tab.kind) ? String(source.template || '') : tab.originalText,
        draftText: ['system', 'context'].includes(tab.kind) ? String(source.template || '') : tab.draftText,
      }
    })
  if (!promptWorkspaceTabs.value.some((tab) => tab.id === activePromptTabId.value)) {
    activePromptTabId.value = promptWorkspaceTabs.value[0]?.id || ''
  }
}

async function loadPromptWorkspaceData() {
  try {
    const [templatesResponse, foldersResponse, systemResponse] = await Promise.all([
      axios.get(`${PROMPT_WORKSPACE_API}/prompts`, { timeout: 10000 }),
      axios.get(`${PROMPT_WORKSPACE_API}/prompt-folders`, { timeout: 10000 }),
      axios.get(`${PROMPT_WORKSPACE_API}/system-prompts`, { timeout: 10000 }),
    ])
    promptWorkspaceTemplates.value = Array.isArray(templatesResponse.data) ? templatesResponse.data : []
    promptFolders.value = Array.isArray(foldersResponse.data) ? foldersResponse.data : []
    fixedSystemPrompts.value = Array.isArray(systemResponse.data) ? systemResponse.data : []
    reconcilePromptWorkspaceTabs()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '无法读取提示词文件树'))
  }
}

async function loadPromptTrash() {
  loadingPromptTrash.value = true
  try {
    const response = await axios.get(`${PROMPT_WORKSPACE_API}/prompts/trash`, { timeout: 10000 })
    promptTrashEntries.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '无法读取提示词回收站'))
  } finally {
    loadingPromptTrash.value = false
  }
}

async function activatePromptWorkspaceTab(tabId, { capture = true } = {}) {
  const activationSequence = ++promptWorkspaceActivationSequence
  if (capture) captureActivePromptDraft()
  const tab = promptWorkspaceTabs.value.find((item) => item.id === tabId)
  if (!tab) return
  promptWorkspaceEditorSyncDepth += 1
  try {
    activePromptTabId.value = tabId
    if (tab.kind === 'report') {
      promptTaskType.value = 'wechat_reports'
      selectWechatReportPromptGroup(tab.groupId)
      selectWechatReportPromptType(tab.reportType)
      wechatReportPromptText.value = tab.draftText
      return
    }
    if (tab.kind === 'system') {
      promptTaskType.value = 'system_prompts'
      promptEditorName.value = tab.title
      promptEditorText.value = tab.draftText
      return
    }
    if (tab.kind === 'context') {
      promptTaskType.value = 'prompt_contexts'
      promptEditorName.value = tab.title
      promptEditorText.value = tab.draftText
      return
    }
    if (tab.isNew) {
      createPromptTemplate({ taskType: tab.taskType, name: tab.draftName, folderId: tab.folderId })
      promptEditorText.value = tab.draftText
      return
    }
    promptTaskType.value = tab.taskType
    await loadPromptTemplates()
    if (activationSequence !== promptWorkspaceActivationSequence || activePromptTabId.value !== tabId) return
    selectPromptTemplate(tab.promptId)
    promptEditorName.value = tab.draftName
    promptEditorText.value = tab.draftText
  } finally {
    // Flush programmatic editor writes before user-edit capture resumes.
    await nextTick()
    promptWorkspaceEditorSyncDepth = Math.max(0, promptWorkspaceEditorSyncDepth - 1)
  }
}

async function openPromptWorkspaceFile({ kind, prompt }) {
  if (!prompt?.id) return
  const tabId = `${kind}:${prompt.id}`
  if (!promptWorkspaceTabs.value.some((tab) => tab.id === tabId)) {
    const isReport = kind === 'report'
    const title = isReport
      ? String(prompt.display_name || '区间报告')
      : promptTemplateDisplayName(prompt)
    promptWorkspaceTabs.value.push({
      id: tabId,
      title,
      kind,
      promptId: isReport ? null : prompt.id,
      reportPromptId: isReport ? prompt.id : null,
      taskType: isReport ? 'wechat_reports' : prompt.task_type,
      groupId: isReport ? prompt.group_id : null,
      reportType: isReport ? prompt.report_type : null,
      originalName: title,
      originalText: prompt.template || '',
      draftName: title,
      draftText: prompt.template || '',
      isNew: false,
      dirty: false,
    })
  }
  await activatePromptWorkspaceTab(tabId)
}

async function openSystemPromptWorkspaceFile(prompt) {
  if (!prompt?.id) return
  const tabId = `system:${prompt.id}`
  if (!promptWorkspaceTabs.value.some((tab) => tab.id === tabId)) {
    promptWorkspaceTabs.value.push({
      id: tabId,
      title: String(prompt.name || '系统提示词'),
      kind: 'system',
      systemPromptId: prompt.id,
      taskType: 'system_prompts',
      originalName: String(prompt.name || '系统提示词'),
      originalText: String(prompt.template || ''),
      draftName: String(prompt.name || '系统提示词'),
      draftText: String(prompt.template || ''),
      isNew: false,
      dirty: false,
    })
  }
  await activatePromptWorkspaceTab(tabId)
}

async function openPromptContextWorkspaceFile(prompt) {
  if (!prompt?.id) return
  const tabId = `context:${prompt.id}`
  if (!promptWorkspaceTabs.value.some((tab) => tab.id === tabId)) {
    promptWorkspaceTabs.value.push({
      id: tabId,
      title: String(prompt.name || '任务上下文'),
      kind: 'context',
      systemPromptId: prompt.id,
      taskType: 'prompt_contexts',
      originalName: String(prompt.name || '任务上下文'),
      originalText: String(prompt.template || ''),
      draftName: String(prompt.name || '任务上下文'),
      draftText: String(prompt.template || ''),
      isNew: false,
      dirty: false,
    })
  }
  await activatePromptWorkspaceTab(tabId)
}

async function createPromptWorkspaceFile({ taskType, folderId = null, name }) {
  promptWorkspaceActivationSequence += 1
  captureActivePromptDraft()
  const tabId = `prompt:new:${Date.now()}`
  promptWorkspaceTabs.value.push({
    id: tabId,
    title: name,
    kind: 'prompt',
    promptId: null,
    taskType,
    folderId,
    originalName: '',
    originalText: '',
    draftName: name,
    draftText: '',
    isNew: true,
    dirty: true,
  })
  activePromptTabId.value = tabId
  createPromptTemplate({ taskType, name, folderId })
}

async function closePromptWorkspaceTabs(tabIds, { force = false } = {}) {
  captureActivePromptDraft()
  const closingIds = new Set((Array.isArray(tabIds) ? tabIds : [tabIds]).filter(Boolean))
  if (!closingIds.size) return
  const closingTabs = promptWorkspaceTabs.value.filter((tab) => closingIds.has(tab.id))
  if (!force && closingTabs.some(promptWorkspaceTabDirty)) {
    const confirmed = await requestDestructiveConfirmation({
      title: '关闭提示词',
      message: '关闭后将丢失尚未保存的提示词修改。',
      confirmLabel: '放弃修改并关闭',
      cancelLabel: '继续编辑',
    })
    if (!confirmed) return
  }
  const activeIndex = promptWorkspaceTabs.value.findIndex((tab) => tab.id === activePromptTabId.value)
  const activeClosed = closingIds.has(activePromptTabId.value)
  promptWorkspaceTabs.value = promptWorkspaceTabs.value.filter((tab) => !closingIds.has(tab.id))
  if (!activeClosed) return
  const next = promptWorkspaceTabs.value[Math.min(Math.max(activeIndex, 0), promptWorkspaceTabs.value.length - 1)]
  if (next) {
    await activatePromptWorkspaceTab(next.id, { capture: false })
  } else {
    promptWorkspaceActivationSequence += 1
    activePromptTabId.value = ''
    selectedPromptTemplateId.value = ''
    promptEditorName.value = ''
    promptEditorText.value = ''
    wechatReportPromptText.value = ''
  }
}

async function closePromptWorkspaceTab(tabId) {
  await closePromptWorkspaceTabs([tabId])
}

async function savePromptWorkspaceCurrent() {
  const tab = activePromptWorkspaceTab()
  if (!tab) return
  if (tab.kind === 'system' || tab.kind === 'context') return
  captureActivePromptDraft()
  if (tab.kind === 'report') {
    const saved = await saveWechatReportPrompt()
    if (!saved) return
    tab.originalText = wechatReportPromptText.value
    tab.draftText = wechatReportPromptText.value
    tab.dirty = false
    await loadPromptWorkspaceData()
    return
  }
  const savedId = await savePromptTemplate()
  if (!savedId) return
  const wasNew = tab.isNew
  tab.promptId = savedId
  tab.isNew = false
  tab.originalName = promptEditorName.value
  tab.originalText = promptEditorText.value
  tab.draftName = promptEditorName.value
  tab.draftText = promptEditorText.value
  tab.title = promptEditorName.value
  tab.dirty = false
  if (wasNew) {
    tab.id = `prompt:${savedId}`
    activePromptTabId.value = tab.id
  }
  await loadPromptWorkspaceData()
}

async function resetPromptWorkspaceCurrent() {
  const tab = activePromptWorkspaceTab()
  if (!tab) return
  if (tab.kind === 'system' || tab.kind === 'context') return
  const promptName = String(tab.title || '当前提示词')
  const confirmed = await requestDestructiveConfirmation({
    title: '恢复内置默认',
    message: `将“${promptName}”恢复为内置默认内容。当前修改会被替换，且无法撤销。`,
    confirmLabel: '恢复默认',
    cancelLabel: '取消',
  })
  if (!confirmed) return
  try {
    if (tab.kind === 'report') {
      await axios.post(`${WECHAT_REPORT_GROUP_API}/${tab.groupId}/prompts/${tab.reportType}/reset`, {}, { timeout: 10000 })
      await loadWechatReportPrompts()
      const prompt = wechatReportPrompts.value.find((item) => item.id === tab.reportPromptId)
      wechatReportPromptText.value = prompt?.template || ''
      tab.originalText = wechatReportPromptText.value
      tab.draftText = wechatReportPromptText.value
    } else {
      await axios.post(`${PROMPT_WORKSPACE_API}/prompts/${tab.promptId}/reset`, {}, { timeout: 10000 })
      await loadPromptWorkspaceData()
      const prompt = promptTemplates.value.find((item) => item.id === tab.promptId)
      promptEditorText.value = prompt?.template || ''
      tab.originalText = promptEditorText.value
      tab.draftText = promptEditorText.value
    }
    tab.dirty = false
    ElMessage.success(`已恢复“${promptName}”的内置默认内容`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '恢复默认提示词失败'))
  }
}

watch([promptEditorName, promptEditorText, wechatReportPromptText], () => {
  if (activeView.value !== 'prompts' || promptWorkspaceEditorSyncDepth > 0) return
  captureActivePromptDraft()
})

async function createPromptWorkspaceFolder({ taskType, parentFolderId, name }) {
  try {
    await axios.post(`${PROMPT_WORKSPACE_API}/prompt-folders`, {
      name,
      task_type: taskType,
      parent_folder_id: parentFolderId,
    }, { timeout: 10000 })
    await loadPromptWorkspaceData()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '新建提示词文件夹失败'))
  }
}

async function renamePromptWorkspaceFolder({ folder, name }) {
  try {
    await axios.patch(`${PROMPT_WORKSPACE_API}/prompt-folders/${folder.id}`, { name }, { timeout: 10000 })
    await loadPromptWorkspaceData()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '重命名提示词文件夹失败'))
  }
}

async function renamePromptWorkspaceFile({ prompt, name }) {
  captureActivePromptDraft()
  try {
    await axios.patch(`${PROMPT_WORKSPACE_API}/prompts/${prompt.id}`, { name }, { timeout: 10000 })
    const tab = promptWorkspaceTabs.value.find((item) => item.promptId === prompt.id)
    if (tab) {
      tab.title = name
      tab.originalName = name
      tab.draftName = name
    }
    if (promptTaskType.value === prompt.task_type) await loadPromptTemplates()
    if (tab?.id === activePromptTabId.value) {
      promptEditorName.value = name
      promptEditorText.value = tab.draftText
      tab.dirty = promptWorkspaceTabDirty(tab)
    }
    await loadPromptWorkspaceData()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '重命名提示词失败'))
  }
}

async function renameReportPromptWorkspaceFile({ prompt, name }) {
  try {
    await axios.put(`${WECHAT_REPORT_GROUP_API}/${prompt.group_id}/prompts/${prompt.report_type}`, {
      display_name: name,
    }, { timeout: 10000 })
    const tab = promptWorkspaceTabs.value.find((item) => item.reportPromptId === prompt.id)
    if (tab) tab.title = name
    await loadWechatReportPrompts()
    reconcilePromptWorkspaceTabs()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '重命名报告提示词失败'))
  }
}

function showPromptTrashUndo(entry, message) {
  let handle = null
  handle = ElMessage({
    type: 'success',
    duration: 6500,
    showClose: true,
    customClass: 'vk-trash-undo-message',
    message: h('span', { class: 'vk-trash-undo-content' }, [
      h('span', { class: 'vk-trash-undo-label' }, message),
      h('button', {
        type: 'button',
        class: 'vk-trash-undo-action',
        'aria-label': '撤销移入提示词回收站',
        onClick: async (event) => {
          event.preventDefault()
          event.stopPropagation()
          handle?.close?.()
          await restorePromptTrashEntry(entry)
        },
      }, '撤销'),
    ]),
  })
}

async function deletePromptWorkspaceFile(prompt) {
  const confirmed = await requestDestructiveConfirmation({
    title: '移入回收站',
    message: `将“${promptTemplateDisplayName(prompt)}”移入提示词回收站？`,
    confirmLabel: '移入回收站',
  })
  if (!confirmed) return
  try {
    await axios.delete(`${PROMPT_WORKSPACE_API}/prompts/${prompt.id}`, { timeout: 10000 })
    await closePromptWorkspaceTabs([`prompt:${prompt.id}`], { force: true })
    await Promise.all([loadPromptWorkspaceData(), loadPromptTrash(), loadQaShortcutTemplates(), loadContentAnalysisTemplates()])
    showPromptTrashUndo({ entry_type: 'prompt', id: prompt.id, name: promptTemplateDisplayName(prompt) }, `已将“${promptTemplateDisplayName(prompt)}”移入回收站`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '删除提示词失败'))
  }
}

async function deletePromptWorkspaceFolder(folder) {
  const confirmed = await requestDestructiveConfirmation({
    title: '移入回收站',
    message: `将文件夹“${folder.name}”及其内容移入提示词回收站？`,
    confirmLabel: '移入回收站',
  })
  if (!confirmed) return
  try {
    await axios.delete(`${PROMPT_WORKSPACE_API}/prompt-folders/${folder.id}`, { timeout: 10000 })
    await Promise.all([loadPromptWorkspaceData(), loadPromptTrash(), loadQaShortcutTemplates(), loadContentAnalysisTemplates()])
    reconcilePromptWorkspaceTabs()
    const nextTab = activePromptWorkspaceTab()
    if (nextTab) await activatePromptWorkspaceTab(nextTab.id, { capture: false })
    else {
      selectedPromptTemplateId.value = ''
      promptEditorName.value = ''
      promptEditorText.value = ''
    }
    showPromptTrashUndo({ entry_type: 'folder', id: folder.id, name: folder.name }, `已将“${folder.name}”移入回收站`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '删除提示词文件夹失败'))
  }
}

async function movePromptWorkspaceNode({ kind, node, folderId }) {
  try {
    if (kind === 'folder') {
      await axios.patch(`${PROMPT_WORKSPACE_API}/prompt-folders/${node.id}`, {
        parent_folder_id: folderId,
      }, { timeout: 10000 })
    } else {
      await axios.patch(`${PROMPT_WORKSPACE_API}/prompts/${node.id}`, {
        folder_id: folderId,
      }, { timeout: 10000 })
    }
    await loadPromptWorkspaceData()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '移动提示词项目失败'))
  }
}

async function restorePromptTrashEntry(entry) {
  try {
    await axios.post(`${PROMPT_WORKSPACE_API}/prompts/trash/${entry.entry_type}/${entry.id}/restore`, {}, { timeout: 10000 })
    await Promise.all([loadPromptWorkspaceData(), loadPromptTrash(), loadQaShortcutTemplates(), loadContentAnalysisTemplates()])
    ElMessage.success(`已恢复“${entry.name}”`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '恢复提示词项目失败'))
  }
}

async function permanentlyDeletePromptTrashEntry(entry) {
  try {
    await axios.delete(`${PROMPT_WORKSPACE_API}/prompts/trash/${entry.entry_type}/${entry.id}`, { timeout: 10000 })
    await loadPromptTrash()
    ElMessage.success('已彻底删除')
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '彻底删除提示词项目失败'))
  }
}

async function activatePromptWorkspaceTemplate(templateId) {
  captureActivePromptDraft()
  const tab = activePromptWorkspaceTab()
  await activatePromptTemplate(templateId)
  if (tab?.id === activePromptTabId.value) {
    promptEditorName.value = tab.draftName
    promptEditorText.value = tab.draftText
  }
  await Promise.all([loadPromptWorkspaceData(), loadQaShortcutTemplates(), loadContentAnalysisTemplates()])
}

function stopWeChatQrPolling() {
  if (wechatQrPollTimer) {
    clearTimeout(wechatQrPollTimer)
    wechatQrPollTimer = null
  }
}

async function startWeChatQrLogin(reauthorizeAccountId = '') {
  stopWeChatQrPolling()
  wechatQrStarting.value = true
  const account = wechatAccounts.value.find((item) => item.id === reauthorizeAccountId)
  try {
    const response = await axios.post(`${WECHAT_SUBSCRIPTION_API}/accounts/qr-login`, {
      display_name: account?.display_name || wechatAccountDisplayName.value.trim() || '微信公众平台账号',
      reauthorize_account_id: reauthorizeAccountId || null
    }, { timeout: 30000 })
    wechatQrLogin.value = response.data || {}
    scheduleWeChatQrPoll()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '未能获取微信公众平台二维码'))
  } finally {
    wechatQrStarting.value = false
  }
}

function scheduleWeChatQrPoll() {
  stopWeChatQrPolling()
  if (!wechatQrLogin.value.login_id || !showSettings.value) return
  wechatQrPollTimer = setTimeout(pollWeChatQrLogin, 1800)
}

async function pollWeChatQrLogin() {
  const loginId = wechatQrLogin.value.login_id
  if (!loginId || !showSettings.value) return
  try {
    const response = await axios.post(`${WECHAT_SUBSCRIPTION_API}/accounts/qr-login/${loginId}/poll`, {
      display_name: wechatAccountDisplayName.value.trim() || '微信公众平台账号',
      reauthorize_account_id: wechatQrLogin.value.reauthorize_account_id || null
    }, { timeout: 30000 })
    wechatQrLogin.value = response.data || {}
    if (response.data?.status === 'confirmed') {
      ElMessage.success(response.data?.reauthorize_account_id ? '微信公众平台已重新授权，订阅保持不变' : '微信公众平台授权成功')
      wechatQrLogin.value = { login_id: '', status: '', message: '', qr_image_data_url: '' }
      await loadWeChatSubscriptions()
      return
    }
    if (['expired', 'failed'].includes(response.data?.status)) {
      stopWeChatQrPolling()
      ElMessage.warning(response.data?.message || '二维码已失效，请重新点击扫码连接')
      return
    }
    scheduleWeChatQrPoll()
  } catch (error) {
    stopWeChatQrPolling()
    ElMessage.error(wechatErrorMessage(error, '微信扫码授权失败'))
  }
}

async function connectWeChatManually() {
  if (!wechatManualToken.value.trim() || !wechatManualCookie.value.trim()) {
    ElMessage.warning('请输入 token 和 Cookie')
    return
  }
  wechatManualConnecting.value = true
  try {
    const response = await axios.post(`${WECHAT_SUBSCRIPTION_API}/accounts`, {
      display_name: wechatAccountDisplayName.value.trim() || '微信公众平台账号',
      token: wechatManualToken.value.trim(),
      cookie: wechatManualCookie.value.trim()
    }, { timeout: 30000 })
    selectedWeChatAccountId.value = response.data?.id || ''
    wechatManualToken.value = ''
    wechatManualCookie.value = ''
    ElMessage.success('微信公众平台账号已连接')
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '微信公众平台登录态不可用'))
  } finally {
    wechatManualConnecting.value = false
  }
}

async function deleteWeChatAccount(accountId) {
  try {
    await axios.delete(`${WECHAT_SUBSCRIPTION_API}/accounts/${accountId}`, { timeout: 10000 })
    ElMessage.success('授权账号已移除')
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '移除授权账号失败'))
  }
}

async function transferWeChatAccountSubscriptions(sourceAccountId) {
  const targetAccountId = String(selectedWeChatAccountId.value || '')
  if (!targetAccountId || targetAccountId === String(sourceAccountId)) {
    ElMessage.warning('请先在授权账号列表中选中接管订阅的新账号')
    return
  }
  try {
    const response = await axios.post(
      `${WECHAT_SUBSCRIPTION_API}/accounts/${sourceAccountId}/transfer-subscriptions`,
      { target_account_id: targetAccountId },
      { timeout: 10000 },
    )
    ElMessage.success(`已迁移 ${response.data?.moved_count || 0} 个公众号订阅`)
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '迁移公众号订阅失败'))
  }
}

async function searchWeChatAccounts() {
  if (!selectedWeChatAccountId.value || !wechatSearchQuery.value.trim()) return
  wechatSearching.value = true
  wechatSearchResults.value = []
  try {
    const response = await axios.get(`${WECHAT_SUBSCRIPTION_API}/accounts/${selectedWeChatAccountId.value}/search`, {
      params: { q: wechatSearchQuery.value.trim(), limit: 10 },
      timeout: 30000
    })
    wechatSearchResults.value = Array.isArray(response.data) ? response.data : []
    if (!wechatSearchResults.value.length) ElMessage.info('没有找到匹配的公众号')
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '搜索公众号失败'))
  } finally {
    wechatSearching.value = false
  }
}

function clearWeChatSearchResults() {
  wechatSearchResults.value = []
}

function setWeChatSubscriptionState(accountId, fakeid, state = '') {
  const normalizedAccountId = String(accountId || '')
  const normalizedFakeid = String(fakeid || '')
  if (!normalizedAccountId || !normalizedFakeid) return
  const key = `${normalizedAccountId}:${normalizedFakeid}`
  const next = { ...wechatSubscriptionStates.value }
  if (state) next[key] = state
  else delete next[key]
  wechatSubscriptionStates.value = next
}

function upsertWeChatSubscription(subscription) {
  if (!subscription?.id) return
  const index = wechatSubscriptions.value.findIndex((item) => item.id === subscription.id)
  if (index < 0) {
    wechatSubscriptions.value = [subscription, ...wechatSubscriptions.value]
    return
  }
  wechatSubscriptions.value = wechatSubscriptions.value.map((item) => (
    item.id === subscription.id ? { ...item, ...subscription } : item
  ))
}

function stopWeChatInitialSyncPolling(subscriptionId) {
  const timer = wechatInitialSyncPollTimers.get(subscriptionId)
  if (timer) clearTimeout(timer)
  wechatInitialSyncPollTimers.delete(subscriptionId)
}

async function refreshLibraryForWeChatIncrement() {
  if (wechatIncrementalLibraryRefreshInFlight) {
    wechatIncrementalLibraryRefreshQueued = true
    return
  }
  wechatIncrementalLibraryRefreshInFlight = true
  try {
    // loadContentItems also refreshes folder metadata, so the new document,
    // its source folder, unread state, and file tree arrive together.
    await loadContentItems()
  } finally {
    wechatIncrementalLibraryRefreshInFlight = false
    if (wechatIncrementalLibraryRefreshQueued) {
      wechatIncrementalLibraryRefreshQueued = false
      void refreshLibraryForWeChatIncrement()
    }
  }
}

function pollWeChatInitialSync(subscription, accountId, fakeid, attempt = 0) {
  stopWeChatInitialSyncPolling(subscription.id)
  const timer = setTimeout(async () => {
    try {
      const response = await axios.get(
        `${WECHAT_SUBSCRIPTION_API}/${subscription.id}/initial-sync`,
        { timeout: 10000 }
      )
      const status = response.data?.status || 'idle'
      if (status === 'queued' || status === 'running') {
        const importedCount = Number(response.data?.imported_count || 0)
        const previousImportedCount = Number(wechatInitialSyncImportedCounts.get(subscription.id) || 0)
        if (importedCount > previousImportedCount) {
          wechatInitialSyncImportedCounts.set(subscription.id, importedCount)
          void refreshLibraryForWeChatIncrement()
        }
        setWeChatSubscriptionState(accountId, fakeid, 'checking')
        pollWeChatInitialSync(subscription, accountId, fakeid, attempt + 1)
        return
      }
      const subscriptionResponse = await axios.get(
        `${WECHAT_SUBSCRIPTION_API}/${subscription.id}`,
        { timeout: 10000 }
      )
      upsertWeChatSubscription(subscriptionResponse.data)
      await refreshLibraryForWeChatIncrement()
      setWeChatSubscriptionState(accountId, fakeid)
      stopWeChatInitialSyncPolling(subscription.id)
      wechatInitialSyncImportedCounts.delete(subscription.id)
      if (status === 'failed') ElMessage.warning(`${subscription.mp_name || '公众号'}已订阅，但首次检查失败，可稍后手动检查`)
    } catch (error) {
      if (attempt < 120) {
        pollWeChatInitialSync(subscription, accountId, fakeid, attempt + 1)
        return
      }
      setWeChatSubscriptionState(accountId, fakeid)
      stopWeChatInitialSyncPolling(subscription.id)
      wechatInitialSyncImportedCounts.delete(subscription.id)
      ElMessage.warning(`${subscription.mp_name || '公众号'}已订阅，首次检查仍在后台进行`)
    }
  }, attempt ? 1500 : 500)
  wechatInitialSyncPollTimers.set(subscription.id, timer)
}

async function subscribeWeChatAccount(item) {
  if (!selectedWeChatAccountId.value) return
  const accountId = String(selectedWeChatAccountId.value)
  const fakeid = String(item.fakeid || '')
  const stateKey = `${accountId}:${fakeid}`
  if (!fakeid || wechatSubscriptionStates.value[stateKey]) return
  if (wechatSubscriptions.value.some((subscription) => (
    String(subscription.account_id) === accountId && String(subscription.fakeid) === fakeid
  ))) return
  setWeChatSubscriptionState(accountId, fakeid, 'subscribing')
  try {
    const response = await axios.post(WECHAT_SUBSCRIPTION_API, {
      account_id: accountId,
      fakeid: item.fakeid,
      mp_name: item.name,
      biz: item.biz || '',
      avatar_url: item.avatar_url || '',
      description: item.description || '',
      sync_interval_minutes: wechatSubscriptionInterval.value,
      auto_process: wechatAutoProcess.value,
      initial_sync: true,
      initial_limit: 10
    }, { timeout: 15000 })
    const subscription = response.data?.subscription
    if (!subscription?.id) throw new Error('订阅接口未返回公众号信息')
    upsertWeChatSubscription(subscription)
    await loadContentItems()
    const sync = response.data?.sync
    if (sync?.task_id) {
      setWeChatSubscriptionState(accountId, fakeid, 'checking')
      observeSourceSyncTask(sync.task_id, {
        onSucceeded: async () => {
          await Promise.all([loadWeChatSubscriptions(), refreshLibraryForWeChatIncrement()])
          setWeChatSubscriptionState(accountId, fakeid)
        },
        onFailed: (message) => {
          setWeChatSubscriptionState(accountId, fakeid)
          ElMessage.warning(message || `${subscription.mp_name || '公众号'}已订阅，首次检查失败，可稍后手动检查`)
        },
      })
      ElMessage.success('公众号已订阅，正在后台检查最近文章')
    } else {
      setWeChatSubscriptionState(accountId, fakeid)
      ElMessage.success('公众号已订阅')
    }
  } catch (error) {
    setWeChatSubscriptionState(accountId, fakeid)
    ElMessage.error(wechatErrorMessage(error, '创建公众号订阅失败'))
  }
}

async function updateWeChatSubscription(subscription, payload, { silent = false } = {}) {
  const index = wechatSubscriptions.value.findIndex((item) => item.id === subscription.id)
  if (index < 0) return false
  const previous = wechatSubscriptions.value[index]
  const revision = (wechatSubscriptionUpdateRevision.get(subscription.id) || 0) + 1
  wechatSubscriptionUpdateRevision.set(subscription.id, revision)
  wechatSubscriptions.value = wechatSubscriptions.value.map((item) => (
    item.id === subscription.id ? { ...item, ...payload } : item
  ))
  try {
    const response = await axios.patch(`${WECHAT_SUBSCRIPTION_API}/${subscription.id}`, payload, { timeout: 10000 })
    if (wechatSubscriptionUpdateRevision.get(subscription.id) === revision && response.data) {
      wechatSubscriptions.value = wechatSubscriptions.value.map((item) => (
        item.id === subscription.id ? { ...item, ...response.data } : item
      ))
    }
    return true
  } catch (error) {
    if (wechatSubscriptionUpdateRevision.get(subscription.id) === revision) {
      wechatSubscriptions.value = wechatSubscriptions.value.map((item) => (
        item.id === subscription.id ? previous : item
      ))
    }
    if (!silent) ElMessage.error(wechatErrorMessage(error, '更新公众号订阅失败'))
    return false
  }
}

async function updateWeChatSubscriptionsInParallel(subscriptions, payloadForSubscription) {
  let cursor = 0
  let succeeded = 0
  let failed = 0
  const worker = async () => {
    while (cursor < subscriptions.length) {
      const subscription = subscriptions[cursor]
      cursor += 1
      const ok = await updateWeChatSubscription(subscription, payloadForSubscription(subscription), { silent: true })
      if (ok) succeeded += 1
      else failed += 1
    }
  }
  await Promise.all(Array.from({ length: Math.min(5, subscriptions.length) }, worker))
  return { succeeded, failed }
}

async function bulkUpdateWeChatSubscriptions({ subscriptionIds = [], payload = {}, label = '设置' } = {}) {
  const selectedIds = new Set(subscriptionIds.map(String))
  const selectedSubscriptions = wechatSubscriptions.value.filter((item) => selectedIds.has(String(item.id)))
  const allowedKeys = new Set(['sync_interval_minutes', 'auto_process', 'notify_on_new', 'enabled'])
  const safePayload = Object.fromEntries(Object.entries(payload).filter(([key]) => allowedKeys.has(key)))
  if (!selectedSubscriptions.length || !Object.keys(safePayload).length) {
    ElMessage.warning('请选择公众号和要更新的设置')
    return
  }

  const { succeeded, failed } = await updateWeChatSubscriptionsInParallel(selectedSubscriptions, () => safePayload)

  if (failed) {
    ElMessage.warning(`已更新 ${succeeded} 个公众号的${label}，${failed} 个更新失败`)
    return
  }
  ElMessage.success(`已更新 ${succeeded} 个公众号的${label}`)
}

async function bulkAddWeChatSubscriptionGroup({ subscriptionIds = [], groupId } = {}) {
  const selectedIds = new Set(subscriptionIds.map(String))
  const group = wechatReportGroups.value.find((item) => String(item.id) === String(groupId))
  const selectedSubscriptions = wechatSubscriptions.value.filter((item) => selectedIds.has(String(item.id)))
  if (!group || !selectedSubscriptions.length) {
    ElMessage.warning('请选择公众号和要添加的分组')
    return
  }

  const eligible = selectedSubscriptions.filter((subscription) => {
    const groupIds = subscription.group_ids || []
    return groupIds.length < 3 && !groupIds.some((id) => String(id) === String(groupId))
  })
  const skipped = selectedSubscriptions.length - eligible.length
  if (!eligible.length) {
    ElMessage.warning('所选公众号已包含该分组，或均已达到三个分组上限')
    return
  }

  const { succeeded, failed } = await updateWeChatSubscriptionsInParallel(eligible, (subscription) => ({
    group_ids: [...(subscription.group_ids || []), groupId]
  }))

  const details = [`已将“${group.name}”添加到 ${succeeded} 个公众号`]
  if (skipped) details.push(`${skipped} 个已存在该分组或已达到上限`)
  if (failed) details.push(`${failed} 个更新失败`)
  ElMessage[failed ? 'warning' : 'success'](details.join('；'))
}

async function refreshWeChatSubscriptionProfile(subscriptionId) {
  refreshingWeChatProfileId.value = subscriptionId
  try {
    await axios.post(`${WECHAT_SUBSCRIPTION_API}/${subscriptionId}/profile`, {}, { timeout: 30000 })
    await loadWeChatSubscriptions()
    ElMessage.success('公众号资料已更新')
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '更新公众号资料失败'))
  } finally {
    refreshingWeChatProfileId.value = ''
  }
}

async function syncWeChatSubscription(subscriptionId, options = { mode: 'latest', max_items: 10 }) {
  syncingWeChatSubscriptionId.value = subscriptionId
  try {
    const subscription = wechatSubscriptions.value.find((item) => String(item.id) === String(subscriptionId))
    const task = await enqueueSourceSyncTask({
      kind: 'wechat_subscription',
      source_title: subscription?.mp_name || '公众号检查',
      source_url: subscription?.source_url,
      subscription_id: subscriptionId,
      mode: options.mode || 'latest',
      max_items: options.max_items || undefined,
      published_after: options.published_after || undefined,
      published_before: options.published_before || undefined,
    })
    ElMessage.success('已开始检查公众号更新')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        const queued = Number(result.queued_for_analysis || 0)
        ElMessage.success(`检查完成：检查到 ${result.found_count || 0} 篇，新增 ${result.imported_count || 0} 篇${queued ? `，已加入 ${queued} 篇自动分析` : ''}`)
        await loadWeChatSubscriptions()
      },
      onFailed: (message) => ElMessage.error(message || '公众号同步失败'),
    })
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '公众号同步失败'))
  } finally {
    syncingWeChatSubscriptionId.value = ''
  }
}

function stopWeChatBulkSyncPolling() {
  if (wechatBulkSyncPollTimer) clearTimeout(wechatBulkSyncPollTimer)
  wechatBulkSyncPollTimer = null
}

function scheduleWeChatBulkSyncPoll() {
  stopWeChatBulkSyncPolling()
  if (!['queued', 'running'].includes(wechatBulkSyncState.value.status)) return
  wechatBulkSyncPollTimer = setTimeout(() => loadWeChatBulkSyncStatus({ notify: true }), 1200)
}

function wechatBulkProgressKey(state) {
  return [state?.job_id || '', Number(state?.completed || 0), state?.current_subscription_id || ''].join(':')
}

async function refreshWeChatSubscriptionsForBulkProgress() {
  if (wechatBulkProgressRefreshInFlight) return
  wechatBulkProgressRefreshInFlight = true
  try {
    await loadWeChatSubscriptions()
  } finally {
    wechatBulkProgressRefreshInFlight = false
  }
}

function notifyWeChatBulkSyncFinished(state) {
  const imported = Number(state.imported_count || 0)
  if (state.status === 'succeeded') {
    const coverage = Number(state.incomplete_count || 0)
    ElMessage.success(`全部公众号检查完成：检查 ${state.completed || 0} 个，新增 ${imported} 篇${coverage ? `；${coverage} 个达到单次补漏上限` : ''}`)
    return
  }
  if (state.status === 'completed_with_errors') {
    ElMessage.warning(`公众号检查完成：成功 ${state.succeeded || 0} 个，失败 ${state.failed || 0} 个，新增 ${imported} 篇`)
    return
  }
  if (state.status === 'stopped') ElMessage.warning(state.message || '批量更新已停止，请检查微信授权状态')
}

async function loadWeChatBulkSyncStatus({ notify = false } = {}) {
  // Bulk checks are now ordinary persistent tasks. Their observer updates
  // this presentation state, so reopening the view never probes a transient
  // in-memory queue from a previous backend process.
  if (notify) return
}

async function syncAllWeChatSubscriptions() {
  if (['queued', 'running'].includes(wechatBulkSyncState.value.status)) return
  try {
    const total = wechatSubscriptions.value.filter((subscription) => subscription.enabled).length
    if (!total) {
      ElMessage.info('没有已启用的公众号需要更新')
      return
    }
    const task = await enqueueSourceSyncTask({ kind: 'wechat_bulk', source_title: '检查全部公众号' })
    wechatBulkSyncState.value = { status: task.status || 'queued', total, completed: 0, succeeded: 0, failed: 0, skipped: 0, imported_count: 0, incomplete_count: 0 }
    ElMessage.success(`已开始逐个检查 ${total} 个公众号`)
    observeSourceSyncTask(task.task_id, {
      onUpdate: (update) => {
        const progress = Math.max(0, Math.min(100, Number(update.overall_progress || 0)))
        const message = update.logs?.at(-1)?.message || ''
        const currentName = message.includes('：') ? message.split('：').at(-1).split('，')[0] : ''
        wechatBulkSyncState.value = {
          ...wechatBulkSyncState.value,
          status: update.status,
          completed: Math.min(total, Math.floor(progress / 100 * total)),
          current_name: currentName,
        }
      },
      onSucceeded: async (result) => {
        wechatBulkSyncState.value = { status: 'succeeded', ...result }
        await Promise.all([loadWeChatSubscriptions(), loadContentItems()])
        notifyWeChatBulkSyncFinished(wechatBulkSyncState.value)
      },
      onFailed: (message) => {
        wechatBulkSyncState.value = { ...wechatBulkSyncState.value, status: 'failed', message }
        ElMessage.error(message || '公众号检查失败')
      },
    })
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '检查全部公众号未能启动'))
  }
}

async function deleteWeChatSubscription(subscriptionId) {
  try {
    await axios.delete(`${WECHAT_SUBSCRIPTION_API}/${subscriptionId}`, { timeout: 10000 })
    ElMessage.success('已取消公众号订阅')
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '取消公众号订阅失败'))
  }
}

async function createWeChatFilter(payload, done) {
  savingWeChatFilter.value = true
  try {
    await axios.post(WECHAT_FILTER_API, payload, { timeout: 10000 })
    done?.()
    ElMessage.success('正文清洗规则已添加')
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '添加正文清洗规则失败'))
  } finally {
    savingWeChatFilter.value = false
  }
}

async function deleteWeChatFilter(ruleId) {
  try {
    await axios.delete(`${WECHAT_FILTER_API}/${ruleId}`, { timeout: 10000 })
    ElMessage.success('正文清洗规则已删除')
    await loadWeChatSubscriptions()
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '删除正文清洗规则失败'))
  }
}

async function createWeChatReportGroup(payload, done) {
  try {
    const response = await axios.post(WECHAT_REPORT_GROUP_API, payload, { timeout: 10000 })
    done?.()
    await loadWeChatSubscriptions()
    selectedWechatReportPromptGroupId.value = response.data?.id || selectedWechatReportPromptGroupId.value
    await loadWechatReportPrompts()
    ElMessage.success('报告分组已添加；可前往“提示词 → 分组报告”完善区间报告写法')
  } catch (error) { ElMessage.error(wechatErrorMessage(error, '添加公众号分组失败')) }
}

async function deleteWeChatReportGroup(group) {
  if (!group?.id || wechatDeletingGroupId.value) return
  wechatDeletingGroupId.value = group.id
  try {
    const response = await axios.delete(`${WECHAT_REPORT_GROUP_API}/${group.id}`, { timeout: 10000 })
    await loadWeChatSubscriptions()
    await loadWechatReportPrompts()
    const affected = Number(response.data?.affected_subscription_count || 0)
    ElMessage.success(`分组“${group.name}”已删除${affected ? `，已从 ${affected} 个公众号移除标签` : ''}`)
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '删除公众号分组失败'))
  } finally {
    if (wechatDeletingGroupId.value === group.id) wechatDeletingGroupId.value = ''
  }
}

async function saveWeChatReportSchedule(groupId, payload, done) {
  if (!groupId || wechatSavingScheduleGroupId.value) return
  wechatSavingScheduleGroupId.value = groupId
  try {
    await axios.put(
      `${WECHAT_REPORT_GROUP_API}/${encodeURIComponent(groupId)}/schedule`,
      payload,
      { timeout: 10000 },
    )
    await loadWeChatSubscriptions()
    done?.()
    ElMessage.success(payload.enabled ? '已开启定时生成' : '已关闭定时生成')
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '保存定时生成计划失败'))
  } finally {
    if (wechatSavingScheduleGroupId.value === groupId) wechatSavingScheduleGroupId.value = ''
  }
}

function openReportGenerationDialog({ requestId, reportKey, reportLabel, groupName }) {
  reportGenerationConfirmationResolver?.(false)
  reportGenerationDialog.value = {
    visible: true,
    phase: 'checking',
    requestId,
    reportKey,
    reportLabel,
    groupName,
    preflight: null,
  }
  return new Promise((resolve) => {
    reportGenerationConfirmationResolver = resolve
  })
}

function confirmReportGenerationDialog() {
  if (!reportGenerationDialog.value.visible || reportGenerationDialog.value.phase !== 'ready') return
  reportGenerationDialog.value = { ...reportGenerationDialog.value, phase: 'submitting' }
  const resolve = reportGenerationConfirmationResolver
  reportGenerationConfirmationResolver = null
  resolve?.(true)
}

function cancelReportGenerationDialog() {
  const state = reportGenerationDialog.value
  if (!state.visible || state.phase === 'submitting') return
  if (reportPreflightRequest?.requestId === state.requestId) reportPreflightRequest.controller.abort()
  const resolve = reportGenerationConfirmationResolver
  reportGenerationConfirmationResolver = null
  resolve?.(false)
  reportGenerationDialog.value = { ...state, visible: false }
  if (wechatPreparingRequestId === state.requestId) {
    wechatPreparingRequestId = ''
    wechatPreparingGroupId.value = ''
  }
}

function dismissReportGenerationDialog(requestId) {
  if (reportGenerationDialog.value.requestId !== requestId) return
  const resolve = reportGenerationConfirmationResolver
  reportGenerationConfirmationResolver = null
  resolve?.(false)
  reportGenerationDialog.value = { ...reportGenerationDialog.value, visible: false }
}

function closeReportGenerationDialog(requestId) {
  if (reportGenerationDialog.value.requestId !== requestId) return
  reportGenerationDialog.value = { ...reportGenerationDialog.value, visible: false }
}

async function generateWeChatReport(groupId, reportType, options = {}) {
  if (wechatGeneratingGroupId.value || wechatPreparingGroupId.value) return
  const reportKey = `${groupId}:${reportType}`
  const reportLabel = { daily: '日报', weekly: '周报', range: '区间报告' }[reportType] || '汇总'
  const groupName = wechatReportGroups.value.find((group) => group.id === groupId)?.name || '校园生活'
  const requestId = `report-confirm-${++reportGenerationRequestSequence}`
  const requestPayload = { report_type: reportType }
  if (options?.windowStart && options?.windowEnd) {
    requestPayload.window_start = options.windowStart
    requestPayload.window_end = options.windowEnd
    requestPayload.include_history_context = options.includeHistoryContext !== false
  }
  requestPayload.include_external_imports = options.includeExternalImports === true
  if (options?.fileName) requestPayload.file_name = options.fileName
  const preflightController = new AbortController()
  reportPreflightRequest = { requestId, controller: preflightController }
  wechatPreparingRequestId = requestId
  wechatPreparingGroupId.value = reportKey
  const confirmation = openReportGenerationDialog({
    requestId,
    reportKey,
    reportLabel,
    groupName,
  })
  let preflight
  try {
    const response = await axios.post(
      `${WECHAT_REPORT_GROUP_API}/${groupId}/preflight`,
      requestPayload,
      { timeout: 30000, signal: preflightController.signal }
    )
    preflight = response.data || {}
    if (reportGenerationDialog.value.requestId !== requestId) return
    reportGenerationDialog.value = {
      ...reportGenerationDialog.value,
      phase: 'ready',
      groupName: preflight.group_name || groupName,
      preflight,
    }
    const confirmed = await confirmation
    if (!confirmed) return
  } catch (error) {
    dismissReportGenerationDialog(requestId)
    const canceled = axios.isCancel(error) || error?.code === 'ERR_CANCELED'
    if (!canceled) ElMessage.error(wechatErrorMessage(error, '报告预检失败'))
    return
  } finally {
    if (reportPreflightRequest?.requestId === requestId) reportPreflightRequest = null
    if (wechatPreparingRequestId === requestId) {
      wechatPreparingRequestId = ''
      wechatPreparingGroupId.value = ''
    }
  }
  const taskId = `report:${reportType}:${Date.now()}`
  const windowLabel = formatReportTaskWindow(options.windowStart, options.windowEnd)
  const taskName = `${groupName} · ${windowLabel ? `${windowLabel} ${reportLabel}` : reportLabel}`
  wechatGeneratingGroupId.value = reportKey
  processLogOpen.value = true
  addLog(`开始生成${reportLabel}`, 'info', 'report_prepare', null, {
    task_id: taskId,
    task_name: taskName,
    task_status: 'running',
    task_progress: 0
  })
  try {
    let receivedProgress = false
    const result = await consumeWeChatReportStream(groupId, reportType, options, (event) => {
      if (!receivedProgress) {
        receivedProgress = true
        closeReportGenerationDialog(requestId)
      }
      addLog(
        event.message || '报告生成中',
        event.level || 'info',
        event.stage || 'report_prepare',
        event.elapsed_seconds ?? null,
        {
          task_id: taskId,
          task_name: taskName,
          task_status: event.level === 'error' ? 'failed' : 'running',
          task_progress: Number(event.progress || 0),
          model: event.model || null,
          call_count: Number(event.call_count || 0),
          prompt_tokens: event.prompt_tokens ?? null,
          completion_tokens: event.completion_tokens ?? null,
          total_tokens: event.total_tokens ?? null,
          input_chars: event.input_chars ?? null,
          output_chars: event.output_chars ?? null,
          estimated_cost: event.estimated_cost ?? null
        }
      )
    })
    closeReportGenerationDialog(requestId)
    const modeLabel = result?.generation_mode === 'campus_clustered' ? '，已完成事件聚类与引用审校' : ''
    addLog(`生成完成，共汇总 ${result?.source_count || 0} 篇文章${modeLabel}`, 'success', 'report_save', null, {
      task_id: taskId,
      task_name: taskName,
      task_status: 'succeeded',
      task_progress: 100,
      call_count: Number(result?.ai_token_usage?.call_count || 0),
      prompt_tokens: result?.ai_token_usage?.prompt_tokens ?? null,
      completion_tokens: result?.ai_token_usage?.completion_tokens ?? null,
      total_tokens: result?.ai_token_usage?.total_tokens ?? null,
      estimated_cost: result?.ai_token_usage?.estimated_cost ?? null
    })
    ElMessage.success(`已生成${reportLabel}，共汇总 ${result?.source_count || 0} 篇文章${modeLabel}`)
    await loadContentItems()
    await loadLibraryFolders()
  } catch (error) {
    closeReportGenerationDialog(requestId)
    const message = wechatErrorMessage(error, '生成报告失败')
    addLog(message, 'error', 'report_prepare', null, {
      task_id: taskId,
      task_name: taskName,
      task_status: 'failed',
      task_progress: 100
    })
    ElMessage.error(message)
  } finally {
    closeReportGenerationDialog(requestId)
    if (wechatGeneratingGroupId.value === reportKey) wechatGeneratingGroupId.value = ''
    void loadAiTokenUsageSummary()
  }
}

async function consumeWeChatReportStream(groupId, reportType, options, onProgress) {
  const payload = { report_type: reportType }
  if (options?.windowStart && options?.windowEnd) {
    payload.window_start = options.windowStart
    payload.window_end = options.windowEnd
    payload.include_history_context = options.includeHistoryContext !== false
  }
  payload.include_external_imports = options.includeExternalImports === true
  if (options?.fileName) payload.file_name = options.fileName
  return consumeReportEventStream(`${WECHAT_REPORT_GROUP_API}/${groupId}/generate-stream`, payload, onProgress)
}

async function consumeReportEventStream(url, payload, onProgress) {
  const response = await fetch(localApiRequestUrl(url), {
    method: 'POST',
    headers: await localApiAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  })
  if (!response.ok || !response.body) {
    let detail = `报告生成服务返回 ${response.status}`
    try {
      const payload = await response.json()
      detail = payload?.detail || detail
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(detail)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let result = null
  let streamError = ''

  const handleBlock = (block) => {
    const data = block.split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (event.event === 'progress') onProgress?.(event)
    if (event.event === 'complete') result = event.result || {}
    if (event.event === 'error') streamError = event.message || '报告生成失败'
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) handleBlock(block)
    if (done) break
  }
  if (buffer.trim()) handleBlock(buffer)
  if (streamError) throw new Error(streamError)
  if (!result) throw new Error('报告生成连接已结束，但没有收到完成结果')
  return result
}

async function copyWeChatRss(subscriptionId = '') {
  const suffix = subscriptionId ? `/rss/${subscriptionId}.xml` : '/rss.xml'
  const url = `${WECHAT_FEED_API}${suffix}`
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success(subscriptionId ? '单公众号 RSS 地址已复制' : '聚合 RSS 地址已复制')
  } catch {
    ElMessage.error('无法复制 RSS 地址，请检查系统剪贴板权限')
  }
}

async function exportWeChatSubscriptions() {
  try {
    const response = await axios.get(`${WECHAT_FEED_API}/subscriptions.json`, { timeout: 10000 })
    const blob = new Blob([JSON.stringify(response.data, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'knowledgehub-wechat-subscriptions.json'
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('订阅配置已导出，不包含登录凭据')
  } catch (error) {
    ElMessage.error(wechatErrorMessage(error, '导出订阅配置失败'))
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
  searchResults.value = []
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
  reportPreflightRequest?.controller.abort()
  reportGenerationConfirmationResolver?.(false)
  reportGenerationConfirmationResolver = null
  stopWeChatQrPolling()
  stopWeChatBulkSyncPolling()
  disposeWechatCoverController()
  disposeWechatDraftController()
  stopWeChatInitialSyncListPolling()
  for (const subscriptionId of wechatInitialSyncPollTimers.keys()) stopWeChatInitialSyncPolling(subscriptionId)
})

</script>

<style scoped src="./styles/app.css"></style>
