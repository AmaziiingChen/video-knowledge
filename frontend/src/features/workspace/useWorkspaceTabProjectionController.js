import { computed } from 'vue'

export function useWorkspaceTabProjectionController({
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
  apiBase,
}) {
  function workspaceTabById(tabId) {
    return workspaceTabs.value.find((tab) => tab.id === tabId) || null
  }

  function contentItemIdForTab(tabId) {
    const tab = workspaceTabById(tabId)
    return tab?.content_item_id
      || (String(tabId || '').startsWith('content:') ? String(tabId).slice('content:'.length) : '')
  }

  function contentForTab(tabId) {
    const contentItemId = contentItemIdForTab(tabId)
    if (!contentItemId) return null
    // The library list intentionally omits runtime-only fields such as the
    // retained original path. For the open item, always prefer its hydrated
    // detail so PDF/image originals can render immediately.
    if (selectedContentItem.value?.id === contentItemId) return selectedContentItem.value
    return allContentItems.value.find((item) => item.id === contentItemId) || null
  }

  function resultForTab(tabId) {
    const contentItemId = contentItemIdForTab(tabId)
    if (!contentItemId) return null
    const matchingTasks = batchTasks.value.filter((candidate) => candidate.content_item_id === contentItemId)
    // A live retry/reprocessing task is authoritative over an older completed
    // snapshot for the same item.
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
    return videoPath ? localApiRequestUrl(`${apiBase}/media?path=${encodeURIComponent(videoPath)}`) : ''
  }

  function originalMediaUrlForTab(tabId) {
    const originalPath = contentForTab(tabId)?.original_file_path
    return originalPath ? localApiRequestUrl(`${apiBase}/media?path=${encodeURIComponent(originalPath)}`) : ''
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

  const activeWorkspaceTab = computed(() => (
    workspaceTabById(activeWorkspaceTabId.value)
  ))

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

  const activeWorkspaceStatus = computed(() => (
    activeWorkspaceContent.value?.status || activeWorkspaceResult.value?.status || activeWorkspaceTab.value?.status || 'inbox'
  ))

  const activeWorkspaceMediaUrl = computed(() => {
    const videoPath = activeWorkspaceResult.value?.video_path || activeWorkspaceContent.value?.video_path
    return videoPath ? localApiRequestUrl(`${apiBase}/media?path=${encodeURIComponent(videoPath)}`) : ''
  })

  const activeWorkspaceTranscript = computed(() => {
    if (activeWorkspaceResult.value?.transcript) return activeWorkspaceResult.value.transcript
    if (['article', 'forum_post', 'forum_capture'].includes(activeWorkspaceContent.value?.content_type)
      && selectedContentItem.value?.id === activeWorkspaceContent.value.id) {
      return selectedMarkdownSourceText.value
    }
    if (!activeWorkspaceContent.value
      && ['article', 'forum_post', 'forum_capture'].includes(selectedContentItem.value?.content_type)) {
      return selectedMarkdownSourceText.value
    }
    return ''
  })

  return {
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
    activeWorkspaceStatus,
    activeWorkspaceMediaUrl,
    activeWorkspaceTranscript,
  }
}
