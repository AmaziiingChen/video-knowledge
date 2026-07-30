import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatReportCount,
  formatReportDateRange,
  formatReportTaskWindow,
  reportCallPlan,
} from './reportGenerationPresentation.js'

test('formats report quantities without exposing invalid values', () => {
  assert.equal(formatReportCount(1294306), '1,294,306')
  assert.equal(formatReportCount(-4), '0')
  assert.equal(formatReportCount('invalid'), '0')
})

test('formats an invalid report window as a useful fallback', () => {
  assert.equal(formatReportDateRange('', ''), '时间范围待确认')
  assert.equal(formatReportTaskWindow('', ''), '')
})

test('keeps both dates in a multi-day report task label', () => {
  assert.equal(
    formatReportTaskWindow('2026-07-20T00:00:00+08:00', '2026-07-26T23:59:59+08:00'),
    '7/20 00:00–7/26 23:59',
  )
  assert.equal(
    formatReportTaskWindow('2026-07-20T00:00:00+08:00', '2026-07-20T23:59:59+08:00'),
    '7/20 00:00–23:59',
  )
})

test('builds the stable report model chain around the dynamic summary count', () => {
  assert.deepEqual(reportCallPlan({ expected_calls: { summary_calls: 25 } }), [
    { label: '单篇摘要', detail: '25 次 · Flash Thinking' },
    { label: '栏目规划', detail: '固定 1 次；结构问题由代码局部规范化 · Pro Thinking' },
    { label: '分栏写作', detail: '由栏目数决定，每栏 1 次 · Flash Thinking' },
    { label: '概览与校对', detail: '概览 1 次，引用局部校对最多 1 次 · Flash Thinking' },
  ])
})

test('defers the exact summary count until the streamed task loads materials', () => {
  assert.equal(
    reportCallPlan({ expected_calls: { summary_calls: null } })[0].detail,
    '将在任务启动后按缓存状态决定 · Flash Thinking',
  )
})
