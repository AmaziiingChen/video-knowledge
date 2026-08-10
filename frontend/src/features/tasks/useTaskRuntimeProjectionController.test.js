import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'

import { useTaskRuntimeProjectionController } from './useTaskRuntimeProjectionController.js'

function createController({
  tasks = [],
  status = 'idle',
  step = null,
  isRunning = false,
  result = { timings: {} },
  parsed = null,
  models = ['small'],
} = {}) {
  const refs = {
    result: reactive(result),
    running: ref(isRunning),
    currentStep: ref(step),
    taskStatus: ref(status),
    parsedUrl: ref(parsed),
    batchTasks: ref(tasks),
    availableModels: ref(models),
  }
  const controller = useTaskRuntimeProjectionController({
    ...refs,
    preferredModelOrder: ['tiny', 'base', 'small'],
    modelProfiles: [
      { model: 'tiny', label: 'Tiny' },
      { model: 'small', label: 'Small' },
    ],
    shouldDisplayTask: (task) => task.visible !== false,
    isActiveTask: (task) => task.active === true,
    statusbarStageLabel: (task) => task ? `stage:${task.task_id}` : 'stage:single',
    statusbarTransferDetail: (transfer, context) => `${context}:${transfer?.bytes || 0}`,
    statusbarTaskContext: (task) => task ? `context:${task.task_id}` : 'context:single',
    roundedProgress: (value) => Math.round(Number(value)),
    stepLabel: (value) => ({ transcribe: '转写', summarize: '总结' })[value] || value,
  })
  return { controller, refs }
}

test('counts only visible active queue tasks and preserves configured model order', () => {
  const { controller } = createController({
    result: { timings: { total: 12.5 } },
    models: ['small', 'tiny', 'unknown'],
    tasks: [
      { task_id: 'one', status: 'queued' },
      { task_id: 'two', status: 'running' },
      { task_id: 'hidden', status: 'running', visible: false },
      { task_id: 'paused', status: 'paused' },
    ],
  })

  assert.equal(controller.totalElapsed.value, 12.5)
  assert.equal(controller.activeBatchCount.value, 2)
  assert.deepEqual(controller.modelProfileOptions.value, [
    { model: 'tiny', label: 'Tiny' },
    { model: 'small', label: 'Small' },
  ])
})

test('prefers the running active task and exposes real download transfer progress', () => {
  const transfer = { percent: 42.6, bytes: 2048 }
  const { controller } = createController({
    tasks: [
      { task_id: 'queued', status: 'queued', active: true, step: 'download' },
      { task_id: 'running', status: 'running', active: true, step: 'download', download_transfer: transfer },
    ],
  })

  assert.deepEqual(controller.statusbarProgress.value, {
    visible: true,
    label: 'stage:running',
    detail: 'context:running:2048',
    percent: 43,
    transfer,
  })
})

test('single-task fallback is visible only while the runner and progress state are both active', () => {
  const transfer = { percent: null, bytes: 512 }
  const { controller, refs } = createController({
    status: 'queued',
    step: 'download',
    isRunning: true,
    result: { timings: {}, download_transfer: transfer },
  })

  assert.equal(controller.hasTaskProgress.value, true)
  assert.deepEqual(controller.statusbarProgress.value, {
    visible: true,
    label: 'stage:single',
    detail: 'context:single:512',
    percent: null,
    transfer,
  })

  refs.taskStatus.value = 'succeeded'
  assert.equal(controller.hasTaskProgress.value, false)
  assert.equal(controller.statusbarProgress.value.visible, false)
  refs.running.value = false
  refs.taskStatus.value = 'running'
  assert.equal(controller.statusbarProgress.value.visible, false)
})

test('maps idle, terminal and in-progress task states without inventing a step', () => {
  const { controller, refs } = createController()
  assert.equal(controller.currentStageLabel.value, '等待链接')

  refs.parsedUrl.value = { url: 'https://source.test' }
  assert.equal(controller.currentStageLabel.value, '准备处理')

  const expected = {
    queued: '排队中',
    paused: '已暂停',
    succeeded: '处理完成',
    failed: '处理失败',
    cancelled: '任务已取消',
  }
  for (const [status, label] of Object.entries(expected)) {
    refs.taskStatus.value = status
    assert.equal(controller.currentStageLabel.value, label)
  }

  refs.taskStatus.value = 'running'
  assert.equal(controller.currentStageLabel.value, '处理中')
  refs.currentStep.value = 'transcribe'
  assert.equal(controller.currentStageLabel.value, '转写中')
})
