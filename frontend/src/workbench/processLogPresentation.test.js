import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatLogMetrics,
  logOutcomeLabel,
  taskHeaderStatus,
  taskProgressLabel,
  usageForTask,
} from './processLogPresentation.js'

const formatTokenCount = (value) => value.toLocaleString('en-US')

test('formats task metrics without inventing missing token values', () => {
  assert.equal(
    formatLogMetrics({ task_id: 'report:daily', call_count: 2, prompt_tokens: 1200, completion_tokens: 34 }, formatTokenCount),
    '累计 2 次调用 · 输入 1,200 · 输出 34',
  )
  assert.equal(formatLogMetrics({ total_tokens: 9 }, formatTokenCount), '9 token')
})

test('summarizes task AI calls before falling back to task logs', () => {
  const usage = usageForTask(
    { ai_calls: [{ prompt_tokens: 3, completion_tokens: 4, estimated_cost: 0.1 }, {}] },
    [],
    formatTokenCount,
  )

  assert.equal(usage.label, 'AI 2 次 · 输入 3 · 输出 4 · ¥0.1000')
  assert.match(usage.detail, /1 次未返回用量/)
})

test('keeps task outcome and status labels aligned with current task state', () => {
  assert.equal(logOutcomeLabel({ type: 'warn', msg: 'retry later' }, 0, [{}], { status: 'running' }), '重试')
  assert.equal(logOutcomeLabel({ type: 'success' }, 0, [{}], { status: 'succeeded' }), '完成')
  assert.equal(taskProgressLabel({ status: 'running', overall_progress: 42 }), '42%')
  assert.equal(taskHeaderStatus({ status: 'succeeded' }, () => '已完成'), '已完成')
})
