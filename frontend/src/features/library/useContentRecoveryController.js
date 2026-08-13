import { ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

function errorMessage(error, fallback) {
  const message = error.response?.data?.detail || error.message || fallback
  return typeof message === 'string' ? message : fallback
}

export function useContentRecoveryController({
  autoDownloadBilibiliVideo,
  douyinVideoQuality,
  mergeContentTextReadiness,
  resetArticlePreview,
  loadArticlePreview,
  refreshContentTextReadiness,
  applyTaskData,
  registerBatchTask,
  loadContentItems,
  pollTask,
  pollBatchTasks,
  getContentItemDetail,
  notify,
  request = axios,
  apiBase = API,
}) {
  const retryingContentId = ref(null)

  async function retryContentSourceText(item) {
    if (!item?.id) return
    try {
      const res = await request.post(`${apiBase}/content/${item.id}/source-text/refresh`, {}, { timeout: 30000 })
      mergeContentTextReadiness(item.id, res.data)
      resetArticlePreview(item.id)
      await loadArticlePreview({ ...item, text_readiness: res.data })
      notify.success('正文已重新抓取')
    } catch (error) {
      await refreshContentTextReadiness(item.id)
      notify.error(errorMessage(error, '正文重新抓取失败'))
    }
  }

  async function retryContentProcessing(item) {
    if (!item?.id || retryingContentId.value) return
    retryingContentId.value = item.id
    try {
      const res = await request.post(`${apiBase}/content/${item.id}/retry-processing`, {}, { timeout: 10000 })
      applyTaskData(res.data)
      await loadContentItems()
      pollTask(res.data.task_id)
      notify.success('已重新加入处理队列')
    } catch (error) {
      notify.error(errorMessage(error, '重新处理失败'))
    } finally {
      retryingContentId.value = null
    }
  }

  async function reprocessLocalSource(item) {
    if (!item?.id || retryingContentId.value) return
    retryingContentId.value = item.id
    try {
      const res = await request.post(`${apiBase}/content/${item.id}/reprocess-local-source`, {}, { timeout: 10000 })
      const taskId = res.data?.task_id
      if (taskId) {
        registerBatchTask(res.data, item, { merge: false, allowSourceUrlFallback: false })
        void pollBatchTasks()
      }
      await loadContentItems()
      notify.success(taskId ? '已重新加入处理队列' : '已重新提取原文件')
    } catch (error) {
      notify.error(errorMessage(error, '重新处理原文件失败'))
    } finally {
      retryingContentId.value = null
    }
  }

  async function submitTask(item, endpoint, {
    before,
    success,
    failure,
    refresh = false,
    hydrate = false,
    applyTask = true,
    pollImmediately = true,
  } = {}) {
    if (!item?.id || retryingContentId.value) return
    retryingContentId.value = item.id
    if (before) notify.info(before)
    try {
      const res = await request.post(`${apiBase}/content/${item.id}/${endpoint}`, {}, { timeout: 10000 })
      const task = res.data
      if (task?.task_id) registerBatchTask(task, item)
      if (applyTask) applyTaskData(task)
      if (refresh) await loadContentItems()
      if (hydrate) await getContentItemDetail(item.id)
      if (task?.task_id && pollImmediately) void pollTask(task.task_id)
      notify.success(success)
    } catch (error) {
      notify.error(errorMessage(error, failure || `${success}失败`))
    } finally {
      retryingContentId.value = null
    }
  }

  function retranscribeContentVideo(item) {
    const success = item?.content_type === 'audio' ? '已使用本地音频重新开始转写' : '已使用本地视频重新开始转写'
    return submitTask(item, 'retranscribe', { success, failure: '重新转写失败', refresh: true })
  }

  function fetchExternalSubtitleForContent(item) {
    return submitTask(item, 'fetch-external-subtitle', {
      before: '正在检查 B站播放器外挂字幕…',
      success: '已开始尝试获取外挂字幕；不会下载视频或进行语音识别',
      failure: '获取外挂字幕失败',
      refresh: true,
    })
  }

  function refreshContentSourceContext(item) {
    return submitTask(item, 'refresh-source-context', {
      success: '已开始补采互动指标与评论；完成后会用于总结、追问和搜索',
      failure: '互动与评论补采失败',
      applyTask: false,
    })
  }

  async function saveVideoDownloadSettings() {
    try {
      const res = await request.put(`${apiBase}/video-download-settings`, {
        auto_download_bilibili_video: Boolean(autoDownloadBilibiliVideo.value),
        douyin_video_quality: douyinVideoQuality.value,
      })
      autoDownloadBilibiliVideo.value = Boolean(res.data?.auto_download_bilibili_video)
      douyinVideoQuality.value = ['low', 'standard', 'high'].includes(res.data?.douyin_video_quality)
        ? res.data.douyin_video_quality
        : 'standard'
      notify.success('视频下载设置已保存')
    } catch (error) {
      notify.error(error.response?.data?.detail || '视频下载设置保存失败')
    }
  }

  function redownloadContentVideo(item) {
    const success = item?.source_provider === 'bilibili'
      ? '已开始优先获取外挂字幕并生成总结，视频预览将同步下载'
      : '已开始重新下载本地预览视频'
    return submitTask(item, 'redownload-video', {
      before: '正在创建视频下载任务…',
      success,
      failure: '重新下载视频失败',
      hydrate: true,
    })
  }

  return {
    retryingContentId,
    retryContentSourceText,
    retryContentProcessing,
    reprocessLocalSource,
    retranscribeContentVideo,
    fetchExternalSubtitleForContent,
    refreshContentSourceContext,
    saveVideoDownloadSettings,
    redownloadContentVideo,
  }
}
