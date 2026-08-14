import { computed, watch } from 'vue'

import { contentIsUnread } from '../library/contentReadState.js'

export function useUnreadDockBadgeController({
  allContentItems,
  viewedContentIds,
  explicitlyUnreadContentIds,
  contentViewedBefore,
  desktop = window.knowledgeHubDesktop,
}) {
  const unreadCount = computed(() => {
    const viewedIds = new Set(viewedContentIds.value.map(String))
    const explicitlyUnreadIds = new Set(explicitlyUnreadContentIds.value.map(String))
    return allContentItems.value.reduce((count, item) => (
      contentIsUnread(item, {
        viewedContentIds: viewedIds,
        explicitlyUnreadContentIds: explicitlyUnreadIds,
        viewedBefore: contentViewedBefore.value,
      }) ? count + 1 : count
    ), 0)
  })

  async function syncUnreadBadge(count = unreadCount.value) {
    const setUnreadBadgeCount = desktop?.setUnreadBadgeCount
    if (typeof setUnreadBadgeCount !== 'function') return
    try {
      await setUnreadBadgeCount(count)
    } catch {
      // A Dock badge is an optional desktop affordance and must not affect the library.
    }
  }

  const stopWatching = watch(unreadCount, (count) => {
    void syncUnreadBadge(count)
  }, { immediate: true })

  function dispose() {
    stopWatching()
    void syncUnreadBadge(0)
  }

  return {
    unreadCount,
    syncUnreadBadge,
    dispose,
  }
}
