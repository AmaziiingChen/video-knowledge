import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'
import {
  progressiveTaskSnapshot,
  shouldHydrateProgressiveTask,
} from '../../composables/contentRefreshState.js'

export function useProgressiveTaskHydrationController({
  progressiveTaskSnapshots,
  getContentItemDetail,
  syncTaskTabMetadata,
  getActiveContentItemId,
  setSelectedContentItem,
  setCurrentMarkdownItem,
  updatePendingArticlePreviewReadiness,
  articlePreviews,
  loadArticlePreview,
  mergeBatchTasks,
  addBackendLogs,
  getActiveResultContentItemId,
  applyTaskData,
  request = axios,
  apiBase = API,
}) {
  const progressiveTaskHydratingIds = new Set()
  const articleSnapshotPreviewedTaskIds = new Set()
  const mediaSnapshotPreviewedTaskIds = new Set()
  const transcriptSnapshotPreviewedTaskIds = new Set()

  async function syncVisibleProgressiveContent(task) {
    if (!task?.content_item_id) return null
    const content = await getContentItemDetail(task.content_item_id)
    if (!content) return null
    syncTaskTabMetadata(content)

    // Background task milestones update an already-open reader but never
    // steal focus or create a new workspace tab.
    if (getActiveContentItemId() === content.id) {
      setSelectedContentItem(content)
      setCurrentMarkdownItem(content)
      updatePendingArticlePreviewReadiness(content)
      const preview = articlePreviews[content.id]
      const isReadableArticle = ['article', 'forum_post'].includes(content.content_type)
        && ['wechat', 'campus', 'rss', 'wechat_miniprogram', 'xiaohongshu'].includes(content.source_provider)
      if (isReadableArticle && (!preview || preview.error)) {
        void loadArticlePreview(content, { force: Boolean(preview?.error) })
      }
    }
    return content
  }

  async function hydrateProgressiveTask(task, previousSnapshot) {
    if (!shouldHydrateProgressiveTask(task, previousSnapshot)) return
    const taskId = String(task.task_id || '')
    if (!taskId || progressiveTaskHydratingIds.has(taskId)) return
    progressiveTaskHydratingIds.add(taskId)
    try {
      const previousParts = String(previousSnapshot || '').split('|')
      const transcriptBecameReady = !previousParts.includes('transcript-ready')
        && Number(task?.progress?.transcribe || 0) >= 100
      const contentChanged = !previousSnapshot || previousParts[0] !== String(task.content_item_id || '')
      // Summary growth does not alter the durable content row. Fetch details
      // only for content identity and transcript milestones.
      const shouldSyncContent = contentChanged || transcriptBecameReady
      const [detailResult, hydratedContent] = await Promise.all([
        task.details_included === false
          ? request.get(`${apiBase}/tasks/${taskId}`, { timeout: 10000 })
            .then((response) => response.data)
            .catch(() => null)
          : Promise.resolve(task),
        shouldSyncContent ? syncVisibleProgressiveContent(task) : Promise.resolve(true),
      ])
      // Do not acknowledge a milestone until its content row is readable.
      if (!hydratedContent) return

      const resolvedTask = detailResult || task
      if (detailResult) {
        mergeBatchTasks([detailResult])
        addBackendLogs(detailResult.logs || [], detailResult)
        // The content row was already hydrated in the parallel branch. Only
        // read again if a compact task unexpectedly resolves to another item.
        if (shouldSyncContent && detailResult.content_item_id !== task.content_item_id) {
          await syncVisibleProgressiveContent(detailResult)
        }
        if (getActiveResultContentItemId() === detailResult.content_item_id) {
          applyTaskData(detailResult)
        }
      }
      progressiveTaskSnapshots.set(taskId, progressiveTaskSnapshot(resolvedTask))
    } finally {
      progressiveTaskHydratingIds.delete(taskId)
    }
  }

  async function revealWechatArticleSnapshot(task) {
    if (
      task?.platform !== 'wechat'
      || task?.text_source?.kind !== 'article'
      || !task?.transcript?.trim()
      || !task?.content_item_id
      || articleSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    await syncVisibleProgressiveContent(task)
    rememberPreviewedTask(articleSnapshotPreviewedTaskIds, task.task_id)
  }

  async function revealVideoSnapshot(task) {
    if (
      !task?.video_path
      || !task?.content_item_id
      || mediaSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    const content = await syncVisibleProgressiveContent(task)
    if (!content) return
    rememberPreviewedTask(mediaSnapshotPreviewedTaskIds, task.task_id)
  }

  async function revealTranscriptSnapshot(task) {
    if (
      !task?.transcript?.trim()
      || !task?.content_item_id
      || transcriptSnapshotPreviewedTaskIds.has(task.task_id)
    ) return

    const detail = await syncVisibleProgressiveContent(task)
    if (!detail) return
    rememberPreviewedTask(transcriptSnapshotPreviewedTaskIds, task.task_id)
  }

  function rememberPreviewedTask(taskIds, taskId) {
    if (taskIds.size >= 200) taskIds.clear()
    taskIds.add(taskId)
  }

  return {
    syncVisibleProgressiveContent,
    hydrateProgressiveTask,
    revealWechatArticleSnapshot,
    revealVideoSnapshot,
    revealTranscriptSnapshot,
  }
}
