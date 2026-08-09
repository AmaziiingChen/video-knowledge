import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'
import { truncateWechatDigest } from './wechatDraftPresentation.js'

export function useWechatDraftController({
  apiBase = `${API}/wechat-publishing`,
  ensurePublishingConfigured,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
  request = axios,
  notify = ElMessage,
  messageBox = ElMessageBox,
  timers = globalThis,
} = {}) {
  const wechatDraftDialogVisible = ref(false)
  const loadingWechatDraftDefaults = ref(false)
  const creatingWechatDraft = ref(false)
  const wechatDraftContentItemId = ref('')
  const wechatDraftTitle = ref('')
  const wechatDraftDigest = ref('')
  const wechatDraftAuthor = ref('')
  const wechatDraftPreviewHtml = ref('')
  const wechatDraftCoverUrl = ref('')
  const wechatDraftCoverStatus = ref('')
  const wechatDraftCoverAvailable = ref(false)
  const wechatDraftLatestPublication = ref(null)
  const wechatDraftTask = ref(null)
  const wechatDraftIpPreflight = ref(null)
  const verifyingWechatDraftIp = ref(false)
  const wechatDraftTaskRunning = computed(() => (
    ['queued', 'running'].includes(wechatDraftTask.value?.status)
  ))
  let taskPollTimer = null
  let disposed = false

  function stopTaskPoll() {
    if (taskPollTimer) timers.clearTimeout(taskPollTimer)
    taskPollTimer = null
  }

  function scheduleTaskPoll(delay = 1200) {
    stopTaskPoll()
    if (disposed || !wechatDraftTaskRunning.value || !wechatDraftTask.value?.task_id) return
    taskPollTimer = timers.setTimeout(() => void loadWechatDraftTask(), delay)
  }

  function resetDraftState() {
    stopTaskPoll()
    wechatDraftCoverUrl.value = ''
    wechatDraftCoverStatus.value = ''
    wechatDraftCoverAvailable.value = false
    wechatDraftLatestPublication.value = null
    wechatDraftTask.value = null
    wechatDraftIpPreflight.value = null
    verifyingWechatDraftIp.value = false
  }

  async function openWechatDraftDialog(contentItem) {
    const contentItemId = contentItem?.id
    if (!contentItemId) {
      notify.error('未找到报告内容')
      return
    }
    if (!(await ensurePublishingConfigured?.())) return

    wechatDraftContentItemId.value = contentItemId
    resetDraftState()
    wechatDraftDialogVisible.value = true
    loadingWechatDraftDefaults.value = true
    try {
      const response = await request.get(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}`,
        { timeout: 15000 },
      )
      wechatDraftTitle.value = response.data?.title || contentItem?.title || ''
      wechatDraftDigest.value = response.data?.digest || ''
      wechatDraftAuthor.value = response.data?.author || ''
      wechatDraftPreviewHtml.value = response.data?.preview_html || ''
      wechatDraftLatestPublication.value = response.data?.latest_publication || null
      wechatDraftCoverUrl.value = response.data?.cover_url || ''
      wechatDraftCoverStatus.value = response.data?.cover_status || ''
      wechatDraftCoverAvailable.value = Boolean(response.data?.cover_generation_available)

      const ipPreflightResponse = await request.get(`${apiBase}/ip-preflight`, { timeout: 10000 })
      wechatDraftIpPreflight.value = ipPreflightResponse.data || null
      if (['unavailable', 'unverified'].includes(wechatDraftIpPreflight.value?.status)) {
        await verifyWechatDraftIp({ silent: true })
      }

      const taskResponse = await request.get(
        `${apiBase}/reports/${encodeURIComponent(contentItemId)}/draft-task`,
        { timeout: 10000 },
      )
      wechatDraftTask.value = taskResponse.data || null
      if (wechatDraftTaskRunning.value) scheduleTaskPoll()
    } catch (error) {
      wechatDraftDialogVisible.value = false
      wechatDraftPreviewHtml.value = ''
      wechatDraftCoverUrl.value = ''
      wechatDraftCoverStatus.value = ''
      wechatDraftCoverAvailable.value = false
      notify.error(errorMessage(error, '无法准备公众号草稿'))
    } finally {
      loadingWechatDraftDefaults.value = false
    }
  }

  async function verifyWechatDraftIp({ silent = false } = {}) {
    verifyingWechatDraftIp.value = true
    try {
      const response = await request.post(`${apiBase}/ip-preflight/verify`, {}, { timeout: 25000 })
      wechatDraftIpPreflight.value = response.data || null
      if (wechatDraftIpPreflight.value?.status === 'verified') {
        if (!silent) notify.success('公众号 IP 白名单验证通过')
      } else if (!silent) {
        notify.error(wechatDraftIpPreflight.value?.message || '公众号 IP 白名单验证未通过')
      }
    } catch (error) {
      notify.error(errorMessage(error, '无法验证公众号 IP 白名单'))
    } finally {
      verifyingWechatDraftIp.value = false
    }
  }

  async function createWechatReportDraft() {
    const contentItemId = wechatDraftContentItemId.value
    if (!contentItemId || !wechatDraftTitle.value.trim()) return
    creatingWechatDraft.value = true
    try {
      const response = await request.post(`${apiBase}/reports/${encodeURIComponent(contentItemId)}/draft`, {
        title: wechatDraftTitle.value.trim(),
        digest: truncateWechatDigest(wechatDraftDigest.value),
        author: wechatDraftAuthor.value.trim(),
      }, { timeout: 10000 })
      wechatDraftTask.value = response.data || null
      if (wechatDraftTask.value?.status === 'succeeded' && wechatDraftTask.value?.publication) {
        wechatDraftLatestPublication.value = {
          ...wechatDraftTask.value.publication,
          is_current_source: true,
        }
        notify.success('草稿已创建，未重复提交。')
      } else {
        notify.success('已转入后台处理，可关闭窗口后继续等待。')
        scheduleTaskPoll()
      }
    } catch (error) {
      notify.error(errorMessage(error, '存入公众号草稿箱失败'))
    } finally {
      creatingWechatDraft.value = false
    }
  }

  async function loadWechatDraftTask() {
    const taskId = wechatDraftTask.value?.task_id
    if (!taskId || disposed) return
    try {
      const response = await request.get(
        `${apiBase}/draft-tasks/${encodeURIComponent(taskId)}`,
        { timeout: 10000 },
      )
      const previousStatus = wechatDraftTask.value?.status
      wechatDraftTask.value = response.data || null
      if (wechatDraftTask.value?.status === 'succeeded') {
        if (wechatDraftTask.value.publication) {
          wechatDraftLatestPublication.value = {
            ...wechatDraftTask.value.publication,
            is_current_source: true,
          }
        }
        if (previousStatus !== 'succeeded') {
          notify.success('已存入公众号草稿箱；发表后可在此写入历史档案。')
        }
        stopTaskPoll()
        return
      }
      if (wechatDraftTask.value?.status === 'failed') {
        if (previousStatus !== 'failed') {
          notify.error(wechatDraftTask.value.error || '存入公众号草稿箱失败')
        }
        stopTaskPoll()
        return
      }
      scheduleTaskPoll()
    } catch {
      scheduleTaskPoll(3000)
    }
  }

  async function confirmWechatPublication() {
    const publicationId = wechatDraftLatestPublication.value?.id
    if (!publicationId) return
    try {
      const { value } = await messageBox.prompt(
        '可选：粘贴公众号文章的公开链接，历史档案会显示“查看原文”。',
        '确认已在公众号发表',
        {
          inputPlaceholder: 'https://mp.weixin.qq.com/…',
          inputValidator: (input) => (
            !input?.trim() || input.trim().startsWith('https://') || '链接必须使用 HTTPS'
          ),
          confirmButtonText: '写入历史档案',
          cancelButtonText: '取消',
        },
      )
      const response = await request.post(
        `${apiBase}/publications/${encodeURIComponent(publicationId)}/confirm`,
        { wechat_article_url: String(value || '').trim() },
        { timeout: 15000 },
      )
      wechatDraftLatestPublication.value = response.data || null
      notify.success('已写入历史档案；重新构建并部署公开网站后即可生效')
    } catch (error) {
      if (error === 'cancel' || error?.action === 'cancel' || error?.action === 'close') return
      notify.error(errorMessage(error, '写入历史档案失败'))
    }
  }

  function disposeWechatDraftController() {
    disposed = true
    stopTaskPoll()
  }

  return {
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
    wechatDraftTaskRunning,
    wechatDraftTitle,
  }
}
