import assert from 'node:assert/strict'
import test from 'node:test'

import {
  boundedTaskProgress,
  processLogEntriesForTask,
  preferredProcessLogTaskId,
  visibleProcessLogTasks,
} from './processLogTaskState.js'

test('shows task progress only when the queue reports a finite active-task value', () => {
  assert.equal(boundedTaskProgress({ status: 'running', overall_progress: 48.6 }), 49)
  assert.equal(boundedTaskProgress({ status: 'queued', overall_progress: -4 }), 0)
  assert.equal(boundedTaskProgress({ status: 'running', overall_progress: 140 }), 100)
  assert.equal(boundedTaskProgress({ status: 'running' }), null)
  assert.equal(boundedTaskProgress({ status: 'succeeded', overall_progress: 100 }), null)
})

test('selects copyable logs from one task only', () => {
  const entries = processLogEntriesForTask([
    { task_id: 'video', timestamp: 30, msg: '视频总结完成' },
    { task_id: 'report', timestamp: 20, msg: '栏目规划完成' },
    { task_id: 'report', timestamp: 10, msg: '来源装载完成' },
  ], 'report')

  assert.deepEqual(entries.map((item) => item.msg), ['来源装载完成', '栏目规划完成'])
})

test('orders process-log tasks from oldest to newest by their latest log', () => {
  const tasks = visibleProcessLogTasks([
    { task_id: 'older', task_name: '旧日报', timestamp: 100, task_status: 'succeeded', type: 'success' },
    { task_id: 'active', task_name: '今日日报', timestamp: 200, task_status: 'running' },
    { task_id: 'older', task_name: '旧日报', timestamp: 300, task_status: 'succeeded', type: 'success' },
  ])

  assert.deepEqual(tasks.map((task) => task.task_id), ['active', 'older'])
})

test('prefers the newest running process-log task over later completed history', () => {
  const tasks = visibleProcessLogTasks([
    { task_id: 'report', task_name: '正在生成的日报', timestamp: 200, task_status: 'running' },
    { task_id: 'history', task_name: '历史日报', timestamp: 300, task_status: 'succeeded', type: 'success' },
  ])

  assert.equal(preferredProcessLogTaskId(tasks), 'report')
})

test('keeps queue-task metadata while ordering it by its latest log', () => {
  const tasks = visibleProcessLogTasks(
    [{ task_id: 'queue-1', timestamp: 400, task_status: 'running' }],
    [{ task_id: 'queue-1', display_title: '创作者同步', status: 'running', step: 'download' }]
  )

  assert.deepEqual(tasks, [{
    task_id: 'queue-1',
    display_title: '创作者同步',
    status: 'running',
    step: 'download',
    timestamp: 400,
    sortIndex: 0,
  }])
})

test('keeps compact queue tasks visible before their log details are loaded', () => {
  const tasks = visibleProcessLogTasks([], [{
    task_id: 'queue-summary',
    display_title: '等待查看详情',
    status: 'succeeded',
    updated_at: '2026-07-28T08:00:00+00:00',
    details_included: false,
  }])

  assert.equal(tasks.length, 1)
  assert.equal(tasks[0].task_id, 'queue-summary')
  assert.equal(tasks[0].details_included, false)
})
