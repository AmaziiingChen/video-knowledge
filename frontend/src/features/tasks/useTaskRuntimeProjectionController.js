import { computed } from 'vue'

export function useTaskRuntimeProjectionController({
  result,
  running,
  currentStep,
  taskStatus,
  parsedUrl,
  batchTasks,
  availableModels,
  preferredModelOrder,
  modelProfiles,
  shouldDisplayTask,
  isActiveTask,
  statusbarStageLabel,
  statusbarTransferDetail,
  statusbarTaskContext,
  roundedProgress,
  stepLabel,
} = {}) {
  const totalElapsed = computed(() => {
    const value = result.timings?.total
    return typeof value === 'number' ? value : null
  })

  const hasTaskProgress = computed(() => {
    return ['queued', 'running', 'paused'].includes(taskStatus.value)
  })

  const visibleBatchTasks = computed(() => {
    return batchTasks.value.filter((task) => shouldDisplayTask(task))
  })

  const activeBatchCount = computed(() => {
    return visibleBatchTasks.value.filter((task) => ['queued', 'running'].includes(task.status)).length
  })

  const statusbarProgress = computed(() => {
    const activeTasks = batchTasks.value.filter((task) => isActiveTask(task))
    const activeTask = activeTasks.find((task) => task.status === 'running') || activeTasks[0]
    if (activeTask) {
      const transfer = activeTask.step === 'download' ? activeTask.download_transfer : null
      return {
        visible: true,
        label: statusbarStageLabel(activeTask),
        detail: statusbarTransferDetail(transfer, statusbarTaskContext(activeTask)),
        // A percentage is shown only when the provider supplied a real media
        // denominator (or yt-dlp reported an actual stream percentage).
        percent: transfer?.percent === null || transfer?.percent === undefined
          ? null
          : roundedProgress(transfer.percent),
        transfer,
      }
    }

    const transfer = currentStep.value === 'download' ? result.download_transfer : null
    return {
      // A single-task poll can finish before its final log reaches the dock.
      // Tie this fallback to the live runner as well, so a terminal log never
      // leaves a stale download/transcription progress bar in the status bar.
      visible: running.value && hasTaskProgress.value,
      label: statusbarStageLabel(),
      detail: statusbarTransferDetail(transfer, statusbarTaskContext()),
      percent: transfer?.percent === null || transfer?.percent === undefined
        ? null
        : roundedProgress(transfer.percent),
      transfer,
    }
  })

  const modelProfileOptions = computed(() => {
    return preferredModelOrder
      .filter((model) => availableModels.value.includes(model))
      .map((model) => modelProfiles.find((profile) => profile.model === model))
      .filter(Boolean)
  })

  const currentStageLabel = computed(() => {
    if (taskStatus.value === 'idle') {
      return parsedUrl.value ? '准备处理' : '等待链接'
    }
    if (taskStatus.value === 'queued') return '排队中'
    if (taskStatus.value === 'paused') return '已暂停'
    if (taskStatus.value === 'succeeded') return '处理完成'
    if (taskStatus.value === 'failed') return '处理失败'
    if (taskStatus.value === 'cancelled') return '任务已取消'
    return currentStep.value ? `${stepLabel(currentStep.value)}中` : '处理中'
  })

  return {
    totalElapsed,
    hasTaskProgress,
    activeBatchCount,
    statusbarProgress,
    modelProfileOptions,
    currentStageLabel,
  }
}
