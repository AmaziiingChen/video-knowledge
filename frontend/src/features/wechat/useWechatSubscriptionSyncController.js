import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const IDLE_BULK_SYNC = Object.freeze({
  status: 'idle', total: 0, completed: 0, succeeded: 0, failed: 0,
  skipped: 0, imported_count: 0, incomplete_count: 0,
})

export function useWechatSubscriptionSyncController({
  subscriptions,
  loadSubscriptions,
  refreshContentItems,
  enqueueTask,
  observeTask,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const syncingWeChatSubscriptionId = ref('')
  const wechatBulkSyncState = ref({ ...IDLE_BULK_SYNC })

  function notifyWeChatBulkSyncFinished(state) {
    const imported = Number(state.imported_count || 0)
    if (state.status === 'succeeded') {
      const coverage = Number(state.incomplete_count || 0)
      notify.success(`全部公众号检查完成：检查 ${state.completed || 0} 个，新增 ${imported} 篇${coverage ? `；${coverage} 个达到单次补漏上限` : ''}`)
      return
    }
    if (state.status === 'completed_with_errors') {
      notify.warning(`公众号检查完成：成功 ${state.succeeded || 0} 个，失败 ${state.failed || 0} 个，新增 ${imported} 篇`)
      return
    }
    if (state.status === 'stopped') notify.warning(state.message || '批量更新已停止，请检查微信授权状态')
  }

  async function syncWeChatSubscription(subscriptionId, options = { mode: 'latest', max_items: 10 }) {
    syncingWeChatSubscriptionId.value = subscriptionId
    try {
      const subscription = subscriptions.value.find((item) => String(item.id) === String(subscriptionId))
      const task = await enqueueTask({
        kind: 'wechat_subscription',
        source_title: subscription?.mp_name || '公众号检查',
        source_url: subscription?.source_url,
        subscription_id: subscriptionId,
        mode: options.mode || 'latest',
        max_items: options.max_items || undefined,
        published_after: options.published_after || undefined,
        published_before: options.published_before || undefined,
      })
      notify.success('已开始检查公众号更新')
      observeTask(task.task_id, {
        onSucceeded: async (result) => {
          const queued = Number(result.queued_for_analysis || 0)
          notify.success(`检查完成：检查到 ${result.found_count || 0} 篇，新增 ${result.imported_count || 0} 篇${queued ? `，已加入 ${queued} 篇自动分析` : ''}`)
          await loadSubscriptions()
        },
        onFailed: (message) => notify.error(message || '公众号同步失败'),
      })
    } catch (error) {
      notify.error(errorMessage(error, '公众号同步失败'))
    } finally {
      syncingWeChatSubscriptionId.value = ''
    }
  }

  async function syncAllWeChatSubscriptions() {
    if (['queued', 'running'].includes(wechatBulkSyncState.value.status)) return
    try {
      const total = subscriptions.value.filter((subscription) => subscription.enabled).length
      if (!total) {
        notify.info('没有已启用的公众号需要更新')
        return
      }
      const task = await enqueueTask({ kind: 'wechat_bulk', source_title: '检查全部公众号' })
      wechatBulkSyncState.value = { status: task.status || 'queued', total, completed: 0, succeeded: 0, failed: 0, skipped: 0, imported_count: 0, incomplete_count: 0 }
      notify.success(`已开始逐个检查 ${total} 个公众号`)
      observeTask(task.task_id, {
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
          await Promise.all([loadSubscriptions(), refreshContentItems()])
          notifyWeChatBulkSyncFinished(wechatBulkSyncState.value)
        },
        onFailed: (message) => {
          wechatBulkSyncState.value = { ...wechatBulkSyncState.value, status: 'failed', message }
          notify.error(message || '公众号检查失败')
        },
      })
    } catch (error) {
      notify.error(errorMessage(error, '检查全部公众号未能启动'))
    }
  }

  return {
    syncingWeChatSubscriptionId,
    wechatBulkSyncState,
    syncWeChatSubscription,
    syncAllWeChatSubscriptions,
  }
}
