import assert from 'node:assert/strict'
import test from 'node:test'
import { createTaskDisplayPresentation } from './taskDisplayPresentation.js'

function createPresentation({ result = {}, taskStatus = 'running', currentStep = 'download', clearedAt = 0, taskNames = {} } = {}) {
  return createTaskDisplayPresentation({
    getTaskStatus: () => taskStatus,
    getCurrentStep: () => currentStep,
    getResult: () => result,
    getParsedUrl: () => ({ platform: 'bilibili' }),
    getTaskNames: () => taskNames,
    getLogClearedAt: () => clearedAt,
    sourceProviderFromUrl: () => 'bilibili',
    sourceProviderLabel: (value) => ({ bilibili: '哔哩哔哩', wechat: '微信' })[value] || value,
    formatBytes: (value) => `${value}B`,
    roundedProgress: (value) => Math.round(Number(value) || 0),
    stepNames: { download: '下载', summarize: 'AI 总结' },
    modelProfiles: [{ model: 'small', label: '小模型' }],
    promptTaskOptions: [{ value: 'summary', label: '摘要' }],
  })
}

test('keeps status-bar labels, source context, and transfer formatting stable', () => {
  const presentation = createPresentation({ result: { source_title: 'https://example.com', platform: 'bilibili' } })
  assert.equal(presentation.statusbarStageLabel({ status: 'running', step: 'info', platform: 'wechat' }), '读取文章')
  assert.equal(presentation.statusbarTaskContext(), '哔哩哔哩内容')
  assert.equal(presentation.statusbarTaskContext({ task_id: 't1', source_title: '本地任务' }), '本地任务')
  assert.equal(presentation.statusbarTransferDetail({ detail: '下载中', received_bytes: 2, total_bytes: 10, bytes_per_second: 3 }, 'fallback'), '下载中 · 2B / 10B · 3B/s')
})

test('keeps task visibility, progress, and human labels bounded', () => {
  const clearedAt = Date.parse('2026-01-02T00:00:00Z')
  const presentation = createPresentation({ clearedAt, result: { progress: { summarize: 100 } } })
  assert.equal(presentation.isActiveTask({ status: 'paused' }), true)
  assert.equal(presentation.shouldDisplayTask({ status: 'succeeded', created_at: '2026-01-01T00:00:00Z' }), false)
  assert.equal(presentation.shouldDisplayTask({ status: 'succeeded', created_at: '2026-01-03T00:00:00Z' }), true)
  assert.equal(presentation.stageProgress('summarize'), 100)
  assert.equal(presentation.progressStatus('running', 'summarize'), 'success')
  assert.equal(presentation.stepLabel('download'), '下载')
  assert.equal(presentation.modelLabel('small'), '小模型')
  assert.equal(presentation.promptTaskLabel('summary'), '摘要')
})

test('classifies durable log levels without treating invalid times as real entries', () => {
  const presentation = createPresentation()
  assert.equal(presentation.logTypeFromMessage('任务失败'), 'error')
  assert.equal(presentation.logTypeFromMessage('处理成功'), 'success')
  assert.equal(presentation.logTypeFromMessage('WARNING: retry'), 'warn')
  assert.equal(presentation.logTypeFromMessage('正在处理'), 'info')
  assert.equal(presentation.formatProcessLogTime('not-a-date'), '—')
})
