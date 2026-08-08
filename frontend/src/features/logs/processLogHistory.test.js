import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_REPORT_LOG_HISTORY,
  REPORT_LOG_HISTORY_KEY,
  clearReportLogHistory,
  loadReportLogHistory,
  markInterruptedReportLogs,
  persistReportLogHistory,
} from './processLogHistory.js'


function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}


test('report process logs survive reload while unrelated logs stay transient', () => {
  const storage = memoryStorage()
  const reportLog = {
    task_id: 'report:daily:1',
    task_name: '校园生活 · 日报',
    msg: '栏目已生成',
    timestamp: 100,
  }
  persistReportLogHistory([
    { task_id: 'manual:other', msg: '普通任务', timestamp: 90 },
    reportLog,
  ], storage)

  assert.deepEqual(loadReportLogHistory(storage), [reportLog])
  clearReportLogHistory(storage)
  assert.equal(storage.getItem(REPORT_LOG_HISTORY_KEY), null)
})


test('report process log history is bounded and malformed storage is ignored', () => {
  const storage = memoryStorage()
  const entries = Array.from({ length: MAX_REPORT_LOG_HISTORY + 5 }, (_, index) => ({
    task_id: 'report:weekly:1',
    msg: `日志 ${index}`,
    timestamp: index + 1,
  }))
  persistReportLogHistory(entries, storage)

  const loaded = loadReportLogHistory(storage)
  assert.equal(loaded.length, MAX_REPORT_LOG_HISTORY)
  assert.equal(loaded[0].msg, '日志 5')

  storage.setItem(REPORT_LOG_HISTORY_KEY, '{not-json')
  assert.deepEqual(loadReportLogHistory(storage), [])
})


test('marks an unfinished persisted report as interrupted after an app restart', () => {
  const entries = markInterruptedReportLogs([
    {
      task_id: 'report:range:1',
      task_name: '校园生活 · 区间汇总',
      task_status: 'running',
      task_progress: 70,
      step: 'report_section_write',
      msg: '栏目正文完成 5/7',
      timestamp: 100,
    },
    {
      task_id: 'report:daily:2',
      task_status: 'succeeded',
      msg: '生成完成',
      timestamp: 200,
    },
  ], 300)

  assert.equal(entries.length, 3)
  assert.deepEqual(entries.at(-1), {
    task_id: 'report:range:1',
    task_name: '校园生活 · 区间汇总',
    task_status: 'failed',
    task_progress: 70,
    time: new Date(300).toLocaleTimeString(),
    msg: '报告任务已中断：应用或报告服务在完成前重新启动，请重新生成。',
    type: 'error',
    step: 'report_section_write',
    elapsed_seconds: null,
    timestamp: 300,
  })
})
