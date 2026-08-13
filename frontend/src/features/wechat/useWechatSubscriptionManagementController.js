import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

export function useWechatSubscriptionManagementController({
  selectedAccountId,
  subscriptions,
  reportGroups,
  subscriptionStates,
  syncInterval,
  autoProcess,
  loadSubscriptions,
  refreshContentItems,
  observeTask,
  request = axios,
  apiBase,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const refreshingWeChatProfileId = ref('')
  const updateRevisionBySubscriptionId = new Map()
  let incrementalLibraryRefreshInFlight = false
  let incrementalLibraryRefreshQueued = false

  function setSubscriptionState(accountId, fakeid, state = '') {
    const normalizedAccountId = String(accountId || '')
    const normalizedFakeid = String(fakeid || '')
    if (!normalizedAccountId || !normalizedFakeid) return
    const key = `${normalizedAccountId}:${normalizedFakeid}`
    const next = { ...subscriptionStates.value }
    if (state) next[key] = state
    else delete next[key]
    subscriptionStates.value = next
  }

  function upsertSubscription(subscription) {
    if (!subscription?.id) return
    const index = subscriptions.value.findIndex((item) => item.id === subscription.id)
    if (index < 0) {
      subscriptions.value = [subscription, ...subscriptions.value]
      return
    }
    subscriptions.value = subscriptions.value.map((item) => (
      item.id === subscription.id ? { ...item, ...subscription } : item
    ))
  }

  async function refreshLibraryForIncrement() {
    if (incrementalLibraryRefreshInFlight) {
      incrementalLibraryRefreshQueued = true
      return
    }
    incrementalLibraryRefreshInFlight = true
    try {
      // The content-tree refresh also includes its source folder and unread
      // state, so a successful first sync becomes visible as one update.
      await refreshContentItems()
    } finally {
      incrementalLibraryRefreshInFlight = false
      if (incrementalLibraryRefreshQueued) {
        incrementalLibraryRefreshQueued = false
        void refreshLibraryForIncrement()
      }
    }
  }

  async function subscribeWeChatAccount(item) {
    if (!selectedAccountId.value) return
    const accountId = String(selectedAccountId.value)
    const fakeid = String(item.fakeid || '')
    const stateKey = `${accountId}:${fakeid}`
    if (!fakeid || subscriptionStates.value[stateKey]) return
    if (subscriptions.value.some((subscription) => (
      String(subscription.account_id) === accountId && String(subscription.fakeid) === fakeid
    ))) return
    setSubscriptionState(accountId, fakeid, 'subscribing')
    try {
      const response = await request.post(apiBase, {
        account_id: accountId,
        fakeid: item.fakeid,
        mp_name: item.name,
        biz: item.biz || '',
        avatar_url: item.avatar_url || '',
        description: item.description || '',
        sync_interval_minutes: syncInterval.value,
        auto_process: autoProcess.value,
        initial_sync: true,
        initial_limit: 10,
      }, { timeout: 15000 })
      const subscription = response.data?.subscription
      if (!subscription?.id) throw new Error('订阅接口未返回公众号信息')
      upsertSubscription(subscription)
      await refreshContentItems()
      const sync = response.data?.sync
      if (sync?.task_id) {
        setSubscriptionState(accountId, fakeid, 'checking')
        observeTask(sync.task_id, {
          onSucceeded: async () => {
            await Promise.all([loadSubscriptions(), refreshLibraryForIncrement()])
            setSubscriptionState(accountId, fakeid)
          },
          onFailed: (message) => {
            setSubscriptionState(accountId, fakeid)
            notify.warning(message || `${subscription.mp_name || '公众号'}已订阅，首次检查失败，可稍后手动检查`)
          },
        })
        notify.success('公众号已订阅，正在后台检查最近文章')
      } else {
        setSubscriptionState(accountId, fakeid)
        notify.success('公众号已订阅')
      }
    } catch (error) {
      setSubscriptionState(accountId, fakeid)
      notify.error(errorMessage(error, '创建公众号订阅失败'))
    }
  }

  async function updateWeChatSubscription(subscription, payload, { silent = false } = {}) {
    const index = subscriptions.value.findIndex((item) => item.id === subscription.id)
    if (index < 0) return false
    const previous = subscriptions.value[index]
    const revision = (updateRevisionBySubscriptionId.get(subscription.id) || 0) + 1
    updateRevisionBySubscriptionId.set(subscription.id, revision)
    subscriptions.value = subscriptions.value.map((item) => (
      item.id === subscription.id ? { ...item, ...payload } : item
    ))
    try {
      const response = await request.patch(`${apiBase}/${subscription.id}`, payload, { timeout: 10000 })
      if (updateRevisionBySubscriptionId.get(subscription.id) === revision && response.data) {
        subscriptions.value = subscriptions.value.map((item) => (
          item.id === subscription.id ? { ...item, ...response.data } : item
        ))
      }
      return true
    } catch (error) {
      if (updateRevisionBySubscriptionId.get(subscription.id) === revision) {
        subscriptions.value = subscriptions.value.map((item) => (
          item.id === subscription.id ? previous : item
        ))
      }
      if (!silent) notify.error(errorMessage(error, '更新公众号订阅失败'))
      return false
    }
  }

  async function updateSubscriptionsInParallel(items, payloadForSubscription) {
    let cursor = 0
    let succeeded = 0
    let failed = 0
    const worker = async () => {
      while (cursor < items.length) {
        const subscription = items[cursor]
        cursor += 1
        const ok = await updateWeChatSubscription(subscription, payloadForSubscription(subscription), { silent: true })
        if (ok) succeeded += 1
        else failed += 1
      }
    }
    await Promise.all(Array.from({ length: Math.min(5, items.length) }, worker))
    return { succeeded, failed }
  }

  async function bulkUpdateWeChatSubscriptions({ subscriptionIds = [], payload = {}, label = '设置' } = {}) {
    const selectedIds = new Set(subscriptionIds.map(String))
    const selectedSubscriptions = subscriptions.value.filter((item) => selectedIds.has(String(item.id)))
    const allowedKeys = new Set(['sync_interval_minutes', 'auto_process', 'notify_on_new', 'enabled'])
    const safePayload = Object.fromEntries(Object.entries(payload).filter(([key]) => allowedKeys.has(key)))
    if (!selectedSubscriptions.length || !Object.keys(safePayload).length) {
      notify.warning('请选择公众号和要更新的设置')
      return
    }

    const { succeeded, failed } = await updateSubscriptionsInParallel(selectedSubscriptions, () => safePayload)
    if (failed) {
      notify.warning(`已更新 ${succeeded} 个公众号的${label}，${failed} 个更新失败`)
      return
    }
    notify.success(`已更新 ${succeeded} 个公众号的${label}`)
  }

  async function bulkAddWeChatSubscriptionGroup({ subscriptionIds = [], groupId } = {}) {
    const selectedIds = new Set(subscriptionIds.map(String))
    const group = reportGroups.value.find((item) => String(item.id) === String(groupId))
    const selectedSubscriptions = subscriptions.value.filter((item) => selectedIds.has(String(item.id)))
    if (!group || !selectedSubscriptions.length) {
      notify.warning('请选择公众号和要添加的分组')
      return
    }

    const eligible = selectedSubscriptions.filter((subscription) => {
      const groupIds = subscription.group_ids || []
      return groupIds.length < 3 && !groupIds.some((id) => String(id) === String(groupId))
    })
    const skipped = selectedSubscriptions.length - eligible.length
    if (!eligible.length) {
      notify.warning('所选公众号已包含该分组，或均已达到三个分组上限')
      return
    }

    const { succeeded, failed } = await updateSubscriptionsInParallel(eligible, (subscription) => ({
      group_ids: [...(subscription.group_ids || []), groupId],
    }))
    const details = [`已将“${group.name}”添加到 ${succeeded} 个公众号`]
    if (skipped) details.push(`${skipped} 个已存在该分组或已达到上限`)
    if (failed) details.push(`${failed} 个更新失败`)
    notify[failed ? 'warning' : 'success'](details.join('；'))
  }

  async function refreshWeChatSubscriptionProfile(subscriptionId) {
    refreshingWeChatProfileId.value = subscriptionId
    try {
      await request.post(`${apiBase}/${subscriptionId}/profile`, {}, { timeout: 30000 })
      await loadSubscriptions()
      notify.success('公众号资料已更新')
    } catch (error) {
      notify.error(errorMessage(error, '更新公众号资料失败'))
    } finally {
      refreshingWeChatProfileId.value = ''
    }
  }

  async function deleteWeChatSubscription(subscriptionId) {
    try {
      await request.delete(`${apiBase}/${subscriptionId}`, { timeout: 10000 })
      notify.success('已取消公众号订阅')
      await loadSubscriptions()
    } catch (error) {
      notify.error(errorMessage(error, '取消公众号订阅失败'))
    }
  }

  return {
    refreshingWeChatProfileId,
    subscribeWeChatAccount,
    updateWeChatSubscription,
    bulkUpdateWeChatSubscriptions,
    bulkAddWeChatSubscriptionGroup,
    refreshWeChatSubscriptionProfile,
    deleteWeChatSubscription,
  }
}
