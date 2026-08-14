import { onBeforeUnmount, ref } from 'vue'
import { normalizeContentReadState, uniqueIds } from './contentReadState.js'
import { useUnreadDockBadgeController } from '../notifications/useUnreadDockBadgeController.js'

const CONTENT_VIEW_STATE_KEY = 'knowledgehub.content-view-state.v1'

export function useContentReadState({ isCurrentContent, allContentItems }) {
  const restored = loadContentViewState()
  const viewedContentIds = ref(restored.viewedContentIds)
  const explicitlyUnreadContentIds = ref(restored.explicitlyUnreadContentIds)
  const contentViewedBefore = ref(restored.viewedBefore)
  let initialized = restored.initialized
  let needsBaselineMigration = restored.needsBaselineMigration
  let viewedTimer = null
  const unreadDockBadge = allContentItems ? useUnreadDockBadgeController({
    allContentItems,
    viewedContentIds,
    explicitlyUnreadContentIds,
    contentViewedBefore,
  }) : null

  onBeforeUnmount(() => {
    if (viewedTimer) window.clearTimeout(viewedTimer)
    unreadDockBadge?.dispose()
  })

  function loadContentViewState() {
    if (typeof window === 'undefined' || !window.localStorage) return normalizeContentReadState(null)
    try {
      const raw = window.localStorage.getItem(CONTENT_VIEW_STATE_KEY)
      return raw ? normalizeContentReadState(JSON.parse(raw)) : normalizeContentReadState(null)
    } catch {
      return normalizeContentReadState(null)
    }
  }

  function persistContentViewState() {
    if (typeof window === 'undefined' || !window.localStorage) return
    try {
      window.localStorage.setItem(CONTENT_VIEW_STATE_KEY, JSON.stringify({
        version: 2,
        initialized,
        viewed_content_ids: viewedContentIds.value,
        explicitly_unread_content_ids: explicitlyUnreadContentIds.value,
        viewed_before: contentViewedBefore.value || null
      }))
    } catch {
      // Read state is convenience metadata; storage failures must not affect the library.
    }
  }

  function reconcileContentViewState(items, { initialWindowComplete = false } = {}) {
    const currentIds = new Set((items || []).map((item) => String(item?.id || '')).filter(Boolean))
    if (!initialized) {
      if (!initialWindowComplete) return
      viewedContentIds.value = [...currentIds]
      initialized = true
      contentViewedBefore.value = new Date().toISOString()
      persistContentViewState()
      return
    }
    if (!needsBaselineMigration || !initialWindowComplete) return

    const viewedIds = new Set(viewedContentIds.value)
    explicitlyUnreadContentIds.value = uniqueIds([
      ...explicitlyUnreadContentIds.value,
      ...[...currentIds].filter((id) => !viewedIds.has(id))
    ])
    contentViewedBefore.value = new Date().toISOString()
    needsBaselineMigration = false
    persistContentViewState()
  }

  function scheduleContentViewed(contentItemId) {
    if (!contentItemId) return
    if (viewedTimer) window.clearTimeout(viewedTimer)
    const id = String(contentItemId)
    viewedTimer = window.setTimeout(() => {
      viewedTimer = null
      if (!isCurrentContent(id) || viewedContentIds.value.includes(id)) return
      viewedContentIds.value = [...viewedContentIds.value, id]
      explicitlyUnreadContentIds.value = explicitlyUnreadContentIds.value.filter((currentId) => currentId !== id)
      persistContentViewState()
    }, 800)
  }

  function setContentViewedState(contentItemIds, viewed) {
    const ids = uniqueIds(contentItemIds)
    if (!ids.length) return
    if (viewedTimer) {
      window.clearTimeout(viewedTimer)
      viewedTimer = null
    }
    const currentIds = new Set(viewedContentIds.value)
    const unreadIds = new Set(explicitlyUnreadContentIds.value)
    ids.forEach((id) => {
      if (viewed) {
        currentIds.add(id)
        unreadIds.delete(id)
      } else {
        currentIds.delete(id)
        unreadIds.add(id)
      }
    })
    viewedContentIds.value = [...currentIds]
    explicitlyUnreadContentIds.value = [...unreadIds]
    persistContentViewState()
  }

  return {
    viewedContentIds,
    explicitlyUnreadContentIds,
    contentViewedBefore,
    reconcileContentViewState,
    scheduleContentViewed,
    setContentViewedState
  }
}
