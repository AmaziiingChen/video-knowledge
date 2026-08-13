import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useCompletionNotificationController({
  allContentItems,
  getContentItemDetail,
  openContentTab,
  activeView,
  ribbonItems,
  desktop = window.knowledgeHubDesktop,
  request = axios,
  apiBase = API,
  scheduleInterval = (callback, delay) => window.setInterval(callback, delay),
  cancelInterval = (timer) => window.clearInterval(timer),
}) {
  const completionNotifications = ref([])
  let completionNotificationTimer = null

  async function loadCompletionNotifications() {
    try {
      const response = await request.get(`${apiBase}/completion-notifications`, { params: { limit: 20 }, timeout: 10000 })
      completionNotifications.value = Array.isArray(response.data) ? response.data : []
      const pushToTray = desktop?.setPendingNotifications
      if (typeof pushToTray === 'function') await pushToTray(completionNotifications.value)
    } catch {
      // This auxiliary refresh must not interrupt the workbench.
    }
  }

  async function openCompletionNotification(notification) {
    const id = String(notification?.id || '')
    const contentItemId = String(notification?.content_item_id || '')
    if (contentItemId) {
      const content = allContentItems.value.find((item) => String(item.id) === contentItemId) || await getContentItemDetail(contentItemId)
      if (content) await openContentTab(content)
    } else if (notification?.target_view) {
      const targetView = String(notification.target_view)
      activeView.value = ribbonItems.some((item) => item.view === targetView) ? targetView : 'library'
    }
    if (id) {
      await request.post(`${apiBase}/completion-notifications/seen`, { ids: [id] }, { timeout: 10000 }).catch(() => {})
      await loadCompletionNotifications()
    }
  }

  function startCompletionNotificationPolling() {
    if (completionNotificationTimer) return
    completionNotificationTimer = scheduleInterval(loadCompletionNotifications, 15000)
  }

  function stopCompletionNotificationPolling() {
    if (!completionNotificationTimer) return
    cancelInterval(completionNotificationTimer)
    completionNotificationTimer = null
  }

  return {
    completionNotifications,
    loadCompletionNotifications,
    openCompletionNotification,
    startCompletionNotificationPolling,
    stopCompletionNotificationPolling,
  }
}
