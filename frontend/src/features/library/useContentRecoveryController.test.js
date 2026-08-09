import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useContentRecoveryController } from './useContentRecoveryController.js'

function createController({ request = {} } = {}) {
  const notices = []
  const calls = { readiness: [], previews: [], refreshes: 0, applied: [], registered: [], polls: [], batchPolls: 0, details: [] }
  const autoDownloadBilibiliVideo = ref(false)
  const douyinVideoQuality = ref('standard')
  const controller = useContentRecoveryController({
    autoDownloadBilibiliVideo,
    douyinVideoQuality,
    mergeContentTextReadiness: (...args) => calls.readiness.push(args),
    resetArticlePreview: (...args) => calls.previews.push(['reset', ...args]),
    loadArticlePreview: async (...args) => calls.previews.push(['load', ...args]),
    refreshContentTextReadiness: async () => { calls.refreshes += 1 },
    applyTaskData: (task) => calls.applied.push(task),
    registerBatchTask: (...args) => calls.registered.push(args),
    loadContentItems: async () => { calls.refreshes += 1 },
    pollTask: (taskId) => calls.polls.push(taskId),
    pollBatchTasks: async () => { calls.batchPolls += 1 },
    getContentItemDetail: async (id) => calls.details.push(id),
    notify: {
      success: (message) => notices.push(['success', message]),
      error: (message) => notices.push(['error', message]),
      info: (message) => notices.push(['info', message]),
    },
    request: { post: async () => ({ data: {} }), put: async () => ({ data: {} }), ...request },
    apiBase: 'http://api.test',
  })
  return { controller, calls, notices, autoDownloadBilibiliVideo, douyinVideoQuality }
}

test('retrying source text refreshes readiness and invalidates the old preview', async () => {
  const requests = []
  const { controller, calls, notices } = createController({
    request: { post: async (...args) => { requests.push(args); return { data: { state: 'ready' } } } },
  })
  await controller.retryContentSourceText({ id: 'content-1', title: '文章' })
  assert.deepEqual(requests, [['http://api.test/content/content-1/source-text/refresh', {}, { timeout: 30000 }]])
  assert.deepEqual(calls.readiness, [['content-1', { state: 'ready' }]])
  assert.deepEqual(calls.previews, [
    ['reset', 'content-1'],
    ['load', { id: 'content-1', title: '文章', text_readiness: { state: 'ready' } }],
  ])
  assert.deepEqual(notices, [['success', '正文已重新抓取']])
})

test('retranscription stays on the existing task queue and refreshes content', async () => {
  const task = { task_id: 'task-1', status: 'queued' }
  const { controller, calls, notices } = createController({ request: { post: async () => ({ data: task }) } })
  await controller.retranscribeContentVideo({ id: 'content-1', title: '录音', content_type: 'audio' })
  assert.deepEqual(calls.registered, [[task, { id: 'content-1', title: '录音', content_type: 'audio' }]])
  assert.deepEqual(calls.applied, [task])
  assert.deepEqual(calls.polls, ['task-1'])
  assert.equal(calls.refreshes, 1)
  assert.deepEqual(notices, [['success', '已使用本地音频重新开始转写']])
})

test('local reprocessing retains the queue summary contract without forcing a detail merge', async () => {
  const task = { task_id: 'task-1' }
  const { controller, calls } = createController({ request: { post: async () => ({ data: task }) } })
  await controller.reprocessLocalSource({ id: 'content-1', title: '导入文件' })
  assert.deepEqual(calls.registered, [[task, { id: 'content-1', title: '导入文件' }, { merge: false, allowSourceUrlFallback: false }]])
  assert.equal(calls.batchPolls, 1)
  assert.deepEqual(calls.applied, [])
})

test('saving video settings accepts only supported quality values from the server', async () => {
  const requests = []
  const { controller, autoDownloadBilibiliVideo, douyinVideoQuality, notices } = createController({
    request: {
      put: async (...args) => {
        requests.push(args)
        return { data: { auto_download_bilibili_video: true, douyin_video_quality: 'unsupported' } }
      },
    },
  })
  douyinVideoQuality.value = 'high'
  await controller.saveVideoDownloadSettings()
  assert.deepEqual(requests, [[
    'http://api.test/video-download-settings',
    { auto_download_bilibili_video: false, douyin_video_quality: 'high' },
  ]])
  assert.equal(autoDownloadBilibiliVideo.value, true)
  assert.equal(douyinVideoQuality.value, 'standard')
  assert.deepEqual(notices, [['success', '视频下载设置已保存']])
})
