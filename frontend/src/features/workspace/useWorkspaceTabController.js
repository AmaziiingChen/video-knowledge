import { makeContentTab, tabIdForContent } from '../../workbench/workspaceModel.js'

export function useWorkspaceTabController({
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
  notify,
}) {
  function tabForId(tabId) {
    return workspaceTabs.value.find((tab) => tab.id === tabId) || null
  }

  function updateTabMetadata(tab, content) {
    if (!tab || !content) return
    tab.title = content.title || tab.title
    tab.source_provider = content.source_provider || tab.source_provider
    tab.status = content.status || tab.status
  }

  function upsertContentTab(content) {
    if (!content?.id) return ''
    const tabId = tabIdForContent(content.id)
    const existing = tabForId(tabId)
    if (existing) updateTabMetadata(existing, content)
    else workspaceTabs.value.push(makeContentTab(content))
    return tabId
  }

  async function activateWorkspaceTab(tabId) {
    activeWorkspaceTabId.value = tabId
    activeView.value = 'library'
    const tab = tabForId(tabId)
    let content = tab?.content_item_id
      ? allContentItems.value.find((item) => item.id === tab.content_item_id)
      : null
    if (!content && tab?.content_item_id) content = await getContentItemDetail(tab.content_item_id)
    if (content) {
      await selectContentItem(content)
      return
    }
    selectedContentItem.value = null
    resetMarkdownState()
    detachQaSession()
  }

  async function openContentTab(content) {
    const tabId = upsertContentTab(content)
    if (tabId) await activateWorkspaceTab(tabId)
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
      void activateWorkspaceTab(nextTab.id)
      return
    }
    activeWorkspaceTabId.value = ''
    selectedContentItem.value = null
    resetMarkdownState()
    detachQaSession()
  }

  function closeWorkspaceTab(tabId) {
    closeWorkspaceTabs([tabId])
  }

  async function revealWorkspaceTabLocation(tab) {
    const contentItemId = String(tab?.content_item_id || '').trim()
    if (contentItemId) await revealLibraryNodeLocation({ type: 'content', id: contentItemId })
  }

  async function deleteWorkspaceTabContent(tab) {
    const contentItemId = String(tab?.content_item_id || '').trim()
    if (!contentItemId) return
    const content = allContentItems.value.find((item) => String(item.id) === contentItemId)
      || await getContentItemDetail(contentItemId)
    if (!content) {
      notify.error('找不到该文件，无法移入回收站')
      return
    }
    await deleteContentItem(content)
  }

  async function syncActiveWorkspaceTabSelection({ awaitPrimaryPreview = false } = {}) {
    const tab = tabForId(activeWorkspaceTabId.value)
    if (!tab?.content_item_id) return
    let content = allContentItems.value.find((item) => item.id === tab.content_item_id)
    if (!content) content = await getContentItemDetail(tab.content_item_id)
    if (!content) return
    updateTabMetadata(tab, content)
    await selectContentItem(content, { awaitPrimaryPreview })
  }

  async function syncCompletedTaskContent(contentItemId) {
    if (!contentItemId) return
    // A task completion must refresh only its own detail. Reloading the full
    // library here collapses the progressively disclosed tree while media
    // work is still settling.
    const content = await getContentItemDetail(contentItemId)
    if (!content) return
    await openContentTab(content)
  }

  function syncTaskTabMetadata(content) {
    if (!content?.id) return
    updateTabMetadata(tabForId(tabIdForContent(content.id)), content)
  }

  return {
    openContentTab,
    activateWorkspaceTab,
    closeWorkspaceTab,
    closeWorkspaceTabs,
    revealWorkspaceTabLocation,
    deleteWorkspaceTabContent,
    syncActiveWorkspaceTabSelection,
    syncCompletedTaskContent,
    syncTaskTabMetadata,
  }
}
