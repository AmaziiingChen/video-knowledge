<template>
    <section
    class="process-log-dock"
    :class="{
      'is-collapsed': collapsed && revealHeight === null,
      'is-resizing': resizing,
      'is-snap-animating': snapAnimating,
      'is-revealing': revealHeight !== null
    }"
    :style="{
      height: `${displayHeight}px`,
      flexBasis: `${displayHeight}px`,
      '--log-reveal-progress': revealProgress,
      '--log-content-reveal-progress': revealContentProgress
    }"
    aria-label="处理日志"
  >
    <div
      v-if="!collapsed || resizing"
      class="process-log-resizer"
      role="separator"
      tabindex="0"
      aria-orientation="horizontal"
      aria-label="调整日志面板高度"
      aria-valuemin="150"
      aria-valuemax="360"
      :aria-valuenow="height"
      @pointerdown="startResize"
      @keydown="handleResizeKeydown"
    ></div>
    <div
      v-if="collapsed"
      class="collapsed-process-log-handle"
      role="separator"
      tabindex="0"
      aria-orientation="horizontal"
      aria-label="向上拖拽展开处理日志"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="Math.round(revealProgress * 100)"
      @pointerdown="startReveal"
      @keydown="handleCollapsedKeydown"
    ></div>
    <div v-if="!collapsed || resizing || revealHeight !== null" class="process-log-content">
      <header class="process-log-head">
      <div class="process-log-title">
        <span>日志</span>
        <strong>{{ selectedTask ? batchTaskName(selectedTask) : '选择任务查看完整输出' }}</strong>
      </div>
      <div class="process-log-meta">
        <span v-if="selectedTask">{{ taskHeaderStatus(selectedTask) }}</span>
        <span v-else-if="activeBatchCount">{{ activeBatchCount }} 个任务运行中</span>
        <span v-if="selectedTaskUsage" class="process-log-usage" :title="selectedTaskUsage.detail">
          {{ selectedTaskUsage.label }}
        </span>
        <button
          class="process-log-action"
          type="button"
          :disabled="!copyableLogText"
          aria-label="复制当前任务日志"
          title="复制当前任务日志"
          @click="$emit('copy', copyableLogText)"
        >
          复制
        </button>
        <button
          class="process-log-action"
          type="button"
          :disabled="!hasLogs"
          @click="$emit('clear')"
        >
          清空
        </button>
        <button
          v-if="canCancelSelectedTask"
          class="process-log-action"
          type="button"
          :disabled="selectedTask?.cancel_requested"
          @click="$emit('cancel-task', selectedTask)"
        >
          {{ selectedTask?.cancel_requested ? '正在取消' : '取消' }}
        </button>
        <button
          v-if="needsDouyinLogin"
          class="process-log-action"
          type="button"
          @click="$emit('reconnect-douyin-and-retry', selectedTask)"
        >
          登录后重试
        </button>
        <button
          v-else-if="canRetrySelectedTask"
          class="process-log-action"
          type="button"
          @click="$emit('retry-task', selectedTask)"
        >
          重试
        </button>
        <button
          class="process-log-action"
          type="button"
          aria-label="收起处理日志"
          @click="$emit('collapse')"
        >
          收起
        </button>
      </div>
      </header>

      <div
        ref="processLogBody"
        class="process-log-body"
        :class="{ 'is-task-resizing': taskResizing }"
        :style="{ '--process-log-task-width': `${displayTaskWidth}px` }"
      >
      <aside ref="taskListContainer" class="process-log-tasks">
        <div class="process-log-tasks-inner">
          <button
            v-for="task in visibleTasks"
            :key="task.task_id"
            class="process-task-row"
            :class="{ active: task.task_id === selectedTask?.task_id }"
            type="button"
            @click="selectTask(task.task_id)"
          >
            <span class="process-task-name">{{ batchTaskName(task) }}</span>
            <span class="process-task-stage">
              {{ statusLabel(task.status) }} · {{ taskStageLabel(task) }}<template v-if="task.execution_mode === 'background'"> · 后台</template> · {{ taskProgressLabel(task) }}
            </span>
            <span
              v-if="taskProgressPercent(task) !== null"
              class="process-task-progress"
              role="progressbar"
              :aria-label="`${batchTaskName(task)} 进度`"
              :aria-valuenow="taskProgressPercent(task)"
              aria-valuemin="0"
              aria-valuemax="100"
            ><i :style="{ transform: `scaleX(${taskProgressPercent(task) / 100})` }"></i></span>
          </button>
          <div v-if="!visibleTasks.length" class="process-log-empty">
            暂无可显示的处理记录
          </div>
        </div>
      </aside>

      <div
        class="process-log-task-resizer"
        role="separator"
        tabindex="0"
        aria-orientation="vertical"
        aria-label="调整任务列表宽度"
        :aria-valuemin="MIN_PROCESS_LOG_TASK_WIDTH"
        :aria-valuemax="MAX_PROCESS_LOG_TASK_WIDTH"
        :aria-valuenow="displayTaskWidth"
        @pointerdown="startTaskResize"
        @keydown="handleTaskResizeKeydown"
      ></div>

      <section class="process-log-output" aria-label="所选任务日志">
        <div class="process-log-column-head" aria-hidden="true">
          <span>时间</span>
          <span>阶段</span>
          <span>消息</span>
        </div>
        <div ref="localLogContainer" class="process-log-lines" @scroll="handleLogScroll">
          <div class="process-log-lines-inner">
            <div
              v-for="(item, index) in selectedTaskLogs"
              :key="`${item.time}-${index}-${item.msg}`"
              class="process-log-line"
              :class="`is-${item.type || 'info'}`"
            >
              <span class="process-log-time">{{ item.time }}</span>
              <span class="process-log-step">{{ item.step ? stepLabel(item.step) : '任务' }}</span>
              <span class="process-log-message">
                <span class="process-log-message-text">{{ item.msg }}</span>
                <span
                  v-if="logOutcomeLabel(item, index)"
                  class="process-log-outcome"
                  :class="`is-${item.type || 'info'}`"
                >{{ logOutcomeLabel(item, index) }}</span>
              </span>
            </div>
            <div v-if="selectedTask && !selectedTaskLogs.length" class="process-log-empty">
              这项任务还没有输出处理日志。
            </div>
            <div v-else-if="!selectedTask" class="process-log-empty">
              选择左侧任务查看完整处理输出。
            </div>
          </div>
        </div>
        <button
          v-if="!followingTail && selectedTaskLogs.length"
          type="button"
          class="process-log-follow"
          @click="resumeTailFollow"
        >回到最新</button>
      </section>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  COLLAPSED_PANE_SIZE,
  COLLAPSED_PANE_REVEAL_DISTANCE,
  MAX_PROCESS_LOG_TASK_WIDTH,
  MIN_PROCESS_LOG_TASK_WIDTH,
  clampProcessLogTaskWidth,
  processLogRevealHeight,
  revealProgressForDistance,
  resolveProcessLogDragTransition,
} from './splitterDragState.js'
import {
  boundedTaskProgress as taskProgressPercent,
  processLogEntriesForTask,
  preferredProcessLogTaskId,
  visibleProcessLogTasks,
} from './processLogTaskState.js'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  height: { type: Number, default: 240 },
  logs: { type: Array, default: () => [] },
  result: { type: Object, required: true },
  batchTasks: { type: Array, default: () => [] },
  activeBatchCount: { type: Number, default: 0 },
  statusbarProgress: { type: Object, required: true },
  currentStageLabel: { type: String, default: '等待任务' },
  roundedProgress: { type: Function, required: true },
  statusLabel: { type: Function, required: true },
  stepLabel: { type: Function, required: true },
  batchTaskName: { type: Function, required: true },
  formatSeconds: { type: Function, required: true },
  formatTokenCount: { type: Function, required: true },
})

const emit = defineEmits([
  'update:height', 'clear', 'copy', 'collapse', 'expand',
  'reconnect-douyin-and-retry', 'retry-task', 'cancel-task', 'load-task-details',
])
const localLogContainer = ref(null)
const taskListContainer = ref(null)
const processLogBody = ref(null)
const selectedTaskId = ref('')
const followingTail = ref(true)
const resizing = ref(false)
const snapAnimating = ref(false)
const revealProgress = ref(0)
const revealHeight = ref(null)
const resizeHeight = ref(null)
const TASK_WIDTH_KEY = 'knowledgehub.process-log-task-width.v1'
const taskListWidth = ref(readStoredTaskWidth())
const taskResizeWidth = ref(null)
const taskResizing = ref(false)
let startY = 0
let startHeight = 0
let resizeStart = null
let revealStart = null
let taskResizeStart = null
let snapAnimationTimer = 0

const displayHeight = computed(() => {
  if (revealHeight.value !== null) return revealHeight.value
  if (resizeHeight.value !== null) return resizeHeight.value
  return props.collapsed ? COLLAPSED_PANE_SIZE : props.height
})
const revealContentProgress = computed(() => {
  if (revealHeight.value === null) return props.collapsed ? 0 : 1
  return Math.min(1, Math.max(0, (revealHeight.value - 20) / 72))
})
const displayTaskWidth = computed(() => clampTaskWidth(taskResizeWidth.value ?? taskListWidth.value))

const visibleTasks = computed(() => {
  if (props.collapsed && revealHeight.value === null) return []
  return visibleProcessLogTasks(props.logs, props.batchTasks)
})
const selectedTask = computed(() => visibleTasks.value.find((task) => task.task_id === selectedTaskId.value) || visibleTasks.value.at(-1) || null)
const preferredTaskId = computed(() => preferredProcessLogTaskId(visibleTasks.value))
const selectedTaskLogs = computed(() => processLogEntriesForTask(
  props.logs,
  selectedTask.value?.task_id,
))
const canRetrySelectedTask = computed(() => ['failed', 'cancelled'].includes(selectedTask.value?.status))
const canCancelSelectedTask = computed(() => ['queued', 'running', 'paused'].includes(selectedTask.value?.status))
const needsDouyinLogin = computed(() => {
  const task = selectedTask.value
  if (!canRetrySelectedTask.value || task?.platform !== 'douyin') return false
  const diagnostic = `${task.error || ''}\n${(task.logs || []).map((item) => item?.message || item).join('\n')}`.toLowerCase()
  return /登录|cookie|验证|安全|captcha|媒体请求/.test(diagnostic)
})
const hasLogs = computed(() => props.logs.length > 0 || props.batchTasks.length > 0)
// The panel only renders ``selectedTaskLogs``.  Copy exactly that same scope:
// exporting the full global stream would silently mix unrelated downloads,
// reports, and historical tasks into a user's diagnostic log.
const copyableLogText = computed(() => selectedTaskLogs.value.map((item) => {
  const parts = []
  if (item.time) parts.push(`[${item.time}]`)
  if (item.step) parts.push(`[${props.stepLabel(item.step)}]`)
  if (item.msg) parts.push(item.msg)
  if (item.task_name) parts.push(`(${item.task_name})`)
  const metrics = formatLogMetrics(item)
  if (metrics) parts.push(metrics)
  return parts.join(' ')
}).filter(Boolean).join('\n'))
const selectedTaskUsage = computed(() => {
  const taskCalls = Array.isArray(selectedTask.value?.ai_calls) ? selectedTask.value.ai_calls : []
  const reportedCalls = taskCalls.filter((call) => (
    finiteMetric(call?.prompt_tokens) !== null || finiteMetric(call?.completion_tokens) !== null
  ))
  if (taskCalls.length) {
    return summarizeUsage({
      callCount: taskCalls.length,
      promptTokens: reportedCalls.reduce((sum, call) => sum + (finiteMetric(call.prompt_tokens) || 0), 0),
      completionTokens: reportedCalls.reduce((sum, call) => sum + (finiteMetric(call.completion_tokens) || 0), 0),
      estimatedCost: taskCalls.reduce((sum, call) => sum + (finiteMetric(call.estimated_cost) || 0), 0),
      unreportedCount: taskCalls.length - reportedCalls.length,
    })
  }

  const metricLogs = selectedTaskLogs.value.filter((item) => (
    finiteMetric(item.call_count) !== null
    || finiteMetric(item.prompt_tokens) !== null
    || finiteMetric(item.completion_tokens) !== null
  ))
  if (!metricLogs.length) return null
  const latest = metricLogs.at(-1)
  const costLog = [...metricLogs].reverse().find((item) => finiteMetric(item.estimated_cost) !== null)
  return summarizeUsage({
    callCount: finiteMetric(latest.call_count) || 0,
    promptTokens: finiteMetric(latest.prompt_tokens) || 0,
    completionTokens: finiteMetric(latest.completion_tokens) || 0,
    estimatedCost: finiteMetric(costLog?.estimated_cost),
  })
})

function formatLogMetrics(item, includeModel = true) {
  const parts = []
  if (includeModel && item.model) parts.push(item.model)
  const callCount = finiteMetric(item.call_count)
  if (callCount !== null && callCount > 0) {
    const prefix = String(item.task_id || '').startsWith('report:') ? '累计 ' : ''
    parts.push(`${prefix}${callCount} 次调用`)
  }
  const reportedTotal = finiteMetric(item.total_tokens)
  const promptTokens = finiteMetric(item.prompt_tokens)
  const completionTokens = finiteMetric(item.completion_tokens)
  const derivedTotal = promptTokens !== null && completionTokens !== null
    ? promptTokens + completionTokens
    : null
  const totalTokens = reportedTotal ?? derivedTotal
  if (promptTokens !== null || completionTokens !== null) {
    const input = promptTokens !== null ? props.formatTokenCount(promptTokens) : '—'
    const output = completionTokens !== null ? props.formatTokenCount(completionTokens) : '—'
    parts.push(`输入 ${input} · 输出 ${output}`)
  } else if (totalTokens !== null && totalTokens > 0) {
    parts.push(`${props.formatTokenCount(totalTokens)} token`)
  }
  // 复制文本保留原始指标，界面则把累计指标收敛到任务标题栏。
  if (!includeModel && !parts.length && item.model) return item.model
  return parts.join(' · ')
}

function summarizeUsage({ callCount, promptTokens, completionTokens, estimatedCost, unreportedCount = 0 }) {
  if (!callCount && !promptTokens && !completionTokens) return null
  const labelParts = []
  if (callCount) labelParts.push(`AI ${callCount} 次`)
  if (promptTokens || completionTokens) {
    labelParts.push(`输入 ${props.formatTokenCount(promptTokens || 0)}`)
    labelParts.push(`输出 ${props.formatTokenCount(completionTokens || 0)}`)
  }
  if (estimatedCost !== null && estimatedCost !== undefined) labelParts.push(`¥${formatLogCost(estimatedCost)}`)
  const detailParts = [
    callCount ? `${callCount} 次 AI 调用` : '',
    `输入 ${props.formatTokenCount(promptTokens || 0)}`,
    `输出 ${props.formatTokenCount(completionTokens || 0)}`,
  ].filter(Boolean)
  if (estimatedCost !== null && estimatedCost !== undefined) detailParts.push(`本机估算 ¥${formatLogCost(estimatedCost)}`)
  if (unreportedCount) detailParts.push(`${unreportedCount} 次未返回用量`)
  return { label: labelParts.join(' · '), detail: detailParts.join(' · ') }
}

function formatLogCost(value) {
  const cost = finiteMetric(value)
  if (cost === null || cost <= 0) return '0.0000'
  return cost < 0.0001 ? '<0.0001' : cost.toFixed(4)
}

function logOutcomeLabel(item, index) {
  if (item.type === 'error') return '失败'
  if (item.type === 'warn') return /重试|retry/i.test(String(item.msg || '')) ? '重试' : '警告'
  if (index === selectedTaskLogs.value.length - 1 && selectedTask.value?.status === 'succeeded') return '完成'
  return ''
}

function taskHeaderStatus(task) {
  const status = props.statusLabel(task?.status)
  const progress = taskProgressLabel(task)
  return status === progress ? status : `${status} · ${progress}`
}

function finiteMetric(value) {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function taskProgressLabel(task) {
  if (task?.persistence_error) return '本地保存失败'
  if (task?.status === 'succeeded') return '已完成'
  if (task?.status === 'failed') return '失败'
  if (task?.status === 'cancelled') return '已取消'
  if (task?.status === 'paused') return '已暂停'
  if (task?.status === 'queued') return '等待中'
  const percent = taskProgressPercent(task)
  if (percent !== null) return `${percent}%`
  return '处理中'
}

function taskStageLabel(task) {
  if (task?.status === 'succeeded' && (!task.step || task.step === 'queued')) return '完成'
  if (task?.status === 'failed' && (!task.step || task.step === 'queued')) return '失败'
  return props.stepLabel(task?.step || 'queued')
}

function selectTask(taskId) {
  if (!taskId || selectedTaskId.value === taskId) return
  selectedTaskId.value = taskId
  followingTail.value = true
}

function isAtLogTail(element = localLogContainer.value) {
  if (!element) return true
  return element.scrollHeight - element.scrollTop - element.clientHeight <= 20
}

function handleLogScroll() {
  followingTail.value = isAtLogTail()
}

async function scrollToLogTail() {
  await nextTick()
  const element = localLogContainer.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

async function scrollToTaskTail() {
  await nextTick()
  const element = taskListContainer.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

async function focusNewestTask() {
  const taskId = preferredTaskId.value
  if (!taskId) return
  selectedTaskId.value = taskId
  followingTail.value = true
  await Promise.all([scrollToTaskTail(), scrollToLogTail()])
}

function resumeTailFollow() {
  followingTail.value = true
  void scrollToLogTail()
}

onBeforeUnmount(() => {
  stopResize()
  stopReveal()
  stopTaskResize()
  stopSnapAnimation()
  window.removeEventListener('resize', fitTaskWidthToAvailableSpace)
})

onMounted(() => {
  fitTaskWidthToAvailableSpace()
  window.addEventListener('resize', fitTaskWidthToAvailableSpace)
})

let knownTaskIds = new Set()
let hasInitializedTaskSelection = false

watch(
  () => [
    visibleTasks.value.map((task) => `${task.task_id}:${task.status}:${task.step}:${task.overall_progress}:${task.timestamp}`).join(','),
    props.logs.map((item) => `${item.task_id}:${item.timestamp}:${item.task_progress ?? ''}`).join(',')
  ],
  async () => {
    const currentTaskIds = new Set(visibleTasks.value.map((task) => task.task_id))
    const newestTaskId = preferredTaskId.value
    const isNewTask = Boolean(
      hasInitializedTaskSelection
      && newestTaskId
      && !knownTaskIds.has(newestTaskId)
    )
    const selectedTaskStillExists = currentTaskIds.has(selectedTaskId.value)

    // A report creates a new task id. Selecting it here prevents an existing
    // history selection from masking the live report that just started.
    if (!selectedTaskStillExists || isNewTask) {
      await focusNewestTask()
    } else if (followingTail.value) {
      await scrollToLogTail()
    }
    knownTaskIds = currentTaskIds
    hasInitializedTaskSelection = true
  },
  { immediate: true, flush: 'post' }
)

watch(selectedTaskId, () => {
  followingTail.value = true
  void scrollToLogTail()
})

watch(
  () => [
    selectedTask.value?.task_id || '',
    selectedTask.value?.updated_at || '',
    selectedTask.value?.details_included,
    props.collapsed,
  ],
  ([taskId, , detailsIncluded, collapsed]) => {
    if (!collapsed && taskId && detailsIncluded === false) {
      emit('load-task-details', selectedTask.value)
    }
  },
  { immediate: true }
)

watch(() => props.collapsed, (collapsed) => {
  if (!collapsed) {
    revealHeight.value = null
    revealProgress.value = 0
    void focusNewestTask()
  }
})

function startResize(event) {
  event.preventDefault()
  stopResize()
  stopSnapAnimation()
  lockTextSelection()
  resizing.value = true
  startY = event.clientY
  startHeight = props.height
  resizeHeight.value = props.height
  resizeStart = {
    pointerId: event.pointerId,
    element: event.currentTarget,
    collapsed: false,
  }
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handleResize)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function handleResize(event) {
  if (!resizeStart || event.pointerId !== resizeStart.pointerId) return
  event.preventDefault()
  const rawHeight = startHeight + startY - event.clientY
  const transition = resolveProcessLogDragTransition(resizeStart, rawHeight)
  resizeStart.collapsed = transition.collapsed
  if (transition.action === 'collapse') {
    startSnapAnimation()
    resizeHeight.value = null
    emit('collapse')
    return
  }
  if (transition.action === 'none') return
  if (transition.action === 'open') {
    startSnapAnimation()
    emit('expand')
  } else {
    stopSnapAnimation()
  }
  resizeHeight.value = Math.max(150, Math.min(360, rawHeight))
}

function startSnapAnimation() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
  if (snapAnimationTimer) window.clearTimeout(snapAnimationTimer)
  snapAnimating.value = true
  snapAnimationTimer = window.setTimeout(() => {
    snapAnimationTimer = 0
    snapAnimating.value = false
  }, 220)
}

function stopSnapAnimation() {
  if (snapAnimationTimer) {
    window.clearTimeout(snapAnimationTimer)
    snapAnimationTimer = 0
  }
  snapAnimating.value = false
}

function stopResize(event, shouldCommit = event?.type === 'pointerup') {
  if (event?.pointerId !== undefined && resizeStart && event.pointerId !== resizeStart.pointerId) return
  window.removeEventListener('pointermove', handleResize)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  if (resizeStart?.element?.hasPointerCapture?.(resizeStart.pointerId)) {
    resizeStart.element.releasePointerCapture?.(resizeStart.pointerId)
  }
  const nextHeight = resizeHeight.value
  const wasCollapsed = Boolean(resizeStart?.collapsed)
  resizeStart = null
  resizeHeight.value = null
  resizing.value = false
  unlockTextSelection()
  if (shouldCommit && !wasCollapsed && nextHeight !== null) emit('update:height', Math.round(nextHeight))
}

function readStoredTaskWidth() {
  try {
    return clampProcessLogTaskWidth(Number(localStorage.getItem(TASK_WIDTH_KEY) || 280))
  } catch {
    return 280
  }
}

function clampTaskWidth(width) {
  return clampProcessLogTaskWidth(width, processLogBody.value?.clientWidth)
}

function fitTaskWidthToAvailableSpace() {
  taskListWidth.value = clampTaskWidth(taskListWidth.value)
}

function saveTaskWidth(width) {
  try {
    localStorage.setItem(TASK_WIDTH_KEY, String(width))
  } catch {
    // Local width persistence is a convenience; dragging still works without it.
  }
}

function startTaskResize(event) {
  if (window.matchMedia?.('(max-width: 760px)').matches) return
  event.preventDefault()
  stopTaskResize()
  lockTextSelection()
  taskResizing.value = true
  taskResizeWidth.value = displayTaskWidth.value
  taskResizeStart = {
    pointerId: event.pointerId,
    element: event.currentTarget,
    startX: event.clientX,
    startWidth: displayTaskWidth.value,
  }
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', handleTaskResize)
  window.addEventListener('pointerup', stopTaskResize)
  window.addEventListener('pointercancel', stopTaskResize)
}

function handleTaskResize(event) {
  if (!taskResizeStart || event.pointerId !== taskResizeStart.pointerId) return
  event.preventDefault()
  taskResizeWidth.value = clampTaskWidth(taskResizeStart.startWidth + event.clientX - taskResizeStart.startX)
}

function stopTaskResize(event, shouldCommit = event?.type === 'pointerup') {
  if (event?.pointerId !== undefined && taskResizeStart && event.pointerId !== taskResizeStart.pointerId) return
  window.removeEventListener('pointermove', handleTaskResize)
  window.removeEventListener('pointerup', stopTaskResize)
  window.removeEventListener('pointercancel', stopTaskResize)
  if (taskResizeStart?.element?.hasPointerCapture?.(taskResizeStart.pointerId)) {
    taskResizeStart.element.releasePointerCapture?.(taskResizeStart.pointerId)
  }
  const nextWidth = taskResizeWidth.value
  taskResizeStart = null
  taskResizeWidth.value = null
  taskResizing.value = false
  unlockTextSelection()
  if (shouldCommit && nextWidth !== null) {
    taskListWidth.value = clampTaskWidth(nextWidth)
    saveTaskWidth(taskListWidth.value)
  }
}

function startReveal(event) {
  event.preventDefault()
  stopReveal()
  lockTextSelection()
  revealStart = {
    y: event.clientY,
    pointerId: event.pointerId,
    distance: 0,
    element: event.currentTarget,
  }
  revealProgress.value = 0
  revealHeight.value = COLLAPSED_PANE_SIZE
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', trackReveal)
  window.addEventListener('pointerup', stopReveal)
  window.addEventListener('pointercancel', stopReveal)
}

function trackReveal(event) {
  if (!revealStart || event.pointerId !== revealStart.pointerId) return
  event.preventDefault()
  revealStart.distance = Math.max(0, revealStart.y - event.clientY)
  revealProgress.value = revealProgressForDistance(revealStart.distance)
  revealHeight.value = processLogRevealHeight(revealStart.distance)
}

function stopReveal(event) {
  if (event?.pointerId !== undefined && revealStart && event.pointerId !== revealStart.pointerId) return
  const shouldExpand = event?.type === 'pointerup'
    && revealStart?.distance >= COLLAPSED_PANE_REVEAL_DISTANCE
  window.removeEventListener('pointermove', trackReveal)
  window.removeEventListener('pointerup', stopReveal)
  window.removeEventListener('pointercancel', stopReveal)
  if (revealStart?.element?.hasPointerCapture?.(revealStart.pointerId)) {
    revealStart.element.releasePointerCapture?.(revealStart.pointerId)
  }
  unlockTextSelection()
  revealStart = null
  const nextHeight = revealHeight.value
  if (shouldExpand) {
    if (nextHeight >= 150) emit('update:height', Math.round(nextHeight))
    emit('expand')
    nextTick(() => {
      revealHeight.value = null
      revealProgress.value = 0
    })
    return
  }
  revealHeight.value = null
  revealProgress.value = 0
}

function handleResizeKeydown(event) {
  let next = props.height
  if (event.key === 'ArrowUp') next += 20
  else if (event.key === 'ArrowDown') next -= 20
  else if (event.key === 'Home') next = 150
  else if (event.key === 'End') next = 360
  else return
  event.preventDefault()
  emit('update:height', Math.max(150, Math.min(360, next)))
}

function handleTaskResizeKeydown(event) {
  let next = displayTaskWidth.value
  if (event.key === 'ArrowLeft') next -= 16
  else if (event.key === 'ArrowRight') next += 16
  else if (event.key === 'Home') next = MIN_PROCESS_LOG_TASK_WIDTH
  else if (event.key === 'End') next = MAX_PROCESS_LOG_TASK_WIDTH
  else return
  event.preventDefault()
  taskListWidth.value = clampTaskWidth(next)
  saveTaskWidth(taskListWidth.value)
}

function handleCollapsedKeydown(event) {
  if (!['Enter', ' ', 'ArrowUp'].includes(event.key)) return
  event.preventDefault()
  emit('expand')
}

function lockTextSelection() {
  window.getSelection?.()?.removeAllRanges()
  document.body.classList.add('workspace-resizing')
}

function unlockTextSelection() {
  document.body.classList.remove('workspace-resizing')
}
</script>

<style scoped>
.process-log-dock {
  position: relative;
  z-index: 6;
  flex: 0 0 auto;
  min-height: 0;
  max-height: 360px;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--vk-border);
  background: color-mix(in srgb, var(--vk-bg-center) 92%, var(--vk-bg-panel));
  box-shadow: none;
  contain: paint;
  overflow: hidden;
  transition:
    height var(--vk-motion-panel) var(--vk-ease-drawer),
    flex-basis var(--vk-motion-panel) var(--vk-ease-drawer);
}

.process-log-dock.is-collapsed {
  min-height: 0;
  border-top-width: 0;
  box-shadow: none;
  contain: none;
  overflow: visible;
}

.process-log-dock.is-collapsed.is-revealing {
  overflow: visible;
}

.process-log-dock.is-revealing {
  min-height: 0;
  max-height: 360px;
  box-shadow: none;
  transition: none;
}

.process-log-dock.is-resizing {
  transition: none;
}

/* Keep direct drag responsive, but give the collapse / reopen threshold the
   same short drawer transition used by the side panes. */
.process-log-dock.is-snap-animating {
  transition:
    height var(--vk-motion-panel) var(--vk-ease-drawer),
    flex-basis var(--vk-motion-panel) var(--vk-ease-drawer) !important;
}

.process-log-content {
  min-height: 0;
  height: 100%;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  opacity: 1;
  transform: translateY(0);
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    transform var(--vk-motion-panel) var(--vk-ease-drawer);
}

.is-collapsed .process-log-content {
  opacity: 0;
  pointer-events: none;
  transform: translateY(16px);
}

.is-revealing .process-log-content {
  opacity: var(--log-content-reveal-progress, 0);
  pointer-events: none;
  transform: translateY(calc((1 - var(--log-content-reveal-progress, 0)) * 16px));
  transition: none;
}

.process-log-resizer {
  position: absolute;
  z-index: 3;
  top: 0;
  left: 0;
  right: 0;
  height: 8px;
  cursor: ns-resize;
}

.process-log-resizer::before {
  content: "";
  position: absolute;
  top: 3px;
  left: 50%;
  width: 42px;
  height: 2px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--vk-border) 78%, var(--vk-text));
  transform: translateX(-50%);
}

.process-log-resizer:focus-visible,
.collapsed-process-log-handle:focus-visible {
  outline: none;
}

.process-log-resizer:focus-visible::before,
.collapsed-process-log-handle:focus-visible::before {
  background: var(--vk-accent-strong);
  opacity: 1;
  transform: scaleY(1);
}

.collapsed-process-log-handle {
  position: absolute;
  z-index: 2;
  right: 0;
  bottom: 0;
  left: 0;
  height: 12px;
  cursor: ns-resize;
  touch-action: none;
}

.collapsed-process-log-handle::before {
  content: "";
  position: absolute;
  top: auto;
  right: 0;
  bottom: 0;
  left: 0;
  height: 3px;
  background: var(--vk-border);
  opacity: 0;
  transform: scaleY(0.333);
  transition:
    opacity var(--vk-motion-standard) var(--vk-ease-out),
    background-color var(--vk-motion-standard) ease,
    transform var(--vk-motion-standard) ease;
}

.collapsed-process-log-handle::after {
  content: "";
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 100%;
  pointer-events: none;
  opacity: var(--log-reveal-progress, 0);
  background: linear-gradient(0deg, color-mix(in srgb, var(--vk-accent) 10%, var(--vk-bg-panel)), transparent 72%);
  transform: scaleY(var(--log-reveal-progress, 0));
  transform-origin: bottom center;
}

.process-log-dock.is-revealing .collapsed-process-log-handle::before {
  background: var(--vk-accent);
  opacity: 1;
  transform: scaleY(1);
}

.process-log-dock.is-revealing .collapsed-process-log-handle::after {
  will-change: transform, opacity;
}

@media (hover: hover) and (pointer: fine) {
  .collapsed-process-log-handle:hover::before {
    background: var(--vk-accent);
    opacity: 1;
    transform: scaleY(1);
  }
}

.process-log-head {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-cluster);
  padding: var(--vk-space-control) var(--vk-space-cluster) var(--vk-space-sm);
}

.process-log-title,
.process-log-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.process-log-title {
  flex: 1 1 auto;
}

.process-log-title span {
  flex: 0 0 auto;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  white-space: nowrap;
  writing-mode: horizontal-tb;
}

.process-log-title strong {
  min-width: 0;
  overflow: hidden;
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-log-meta {
  flex: 0 0 auto;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.process-log-usage {
  max-width: min(40vw, 560px);
  overflow: hidden;
  color: var(--vk-text);
  font-size: var(--vk-type-micro-size);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 980px) {
  .process-log-usage {
    max-width: min(30vw, 260px);
  }
}

.process-log-action {
  min-width: 40px;
  height: 28px;
  padding: 0 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  cursor: pointer;
  transition:
    background-color 0.16s ease,
    color 0.16s ease,
    opacity 0.16s ease,
    transform var(--vk-motion-fast) var(--vk-ease-out);
}

.process-log-action:hover:not(:disabled) {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.process-log-action:active:not(:disabled) {
  transform: scale(0.97);
}

.process-log-action:disabled {
  opacity: 0.38;
  cursor: default;
}

@media (prefers-reduced-motion: reduce) {
  .process-log-dock {
    transition: none;
  }

  .process-log-content {
    transform: none;
    transition: opacity var(--vk-motion-fast) ease;
  }

  .collapsed-process-log-handle::before {
    transition: none;
  }
}

.process-log-body {
  --process-log-columns: 72px 84px minmax(0, 1fr);
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: var(--process-log-task-width, 280px) 8px minmax(0, 1fr);
  border-top: 1px solid color-mix(in srgb, var(--vk-border) 58%, transparent);
}

.process-log-tasks,
.process-log-lines {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.process-log-tasks {
  padding: 8px;
  display: grid;
  scrollbar-gutter: stable;
}

.process-log-tasks-inner {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.process-log-tasks-inner::before {
  content: "";
  margin-top: auto;
}

.process-log-task-resizer {
  position: relative;
  z-index: 2;
  min-height: 0;
  cursor: col-resize;
  touch-action: none;
}

.process-log-task-resizer::before {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 1px;
  background: color-mix(in srgb, var(--vk-border) 72%, transparent);
  transition: background-color var(--vk-motion-fast) ease;
}

.process-log-task-resizer:hover::before,
.process-log-task-resizer:focus-visible::before,
.process-log-body.is-task-resizing .process-log-task-resizer::before {
  background: color-mix(in srgb, var(--vk-accent-strong) 62%, var(--vk-border));
}

.process-log-task-resizer:focus-visible {
  outline: none;
}

.process-task-row {
  width: 100%;
  display: grid;
  gap: var(--vk-space-xs);
  padding: var(--vk-space-control) var(--vk-space-sm);
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  cursor: default;
}

.process-task-row.active,
.process-task-row:hover {
  background: color-mix(in srgb, var(--vk-accent) 13%, transparent);
}

.process-task-name,
.process-task-stage {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-task-name {
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-strong);
}

.process-task-stage {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-variant-numeric: tabular-nums;
}

.process-task-progress {
  width: 100%;
  height: 3px;
  overflow: hidden;
  border-radius: var(--vk-radius-pill);
  background: color-mix(in srgb, var(--vk-border) 68%, transparent);
}

.process-task-progress > i {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: var(--vk-accent-strong);
  transform-origin: left center;
  transition: transform var(--vk-motion-standard) var(--vk-ease-out);
}

.process-log-output {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: grid;
  container-type: inline-size;
  grid-template-rows: 28px minmax(0, 1fr);
  overflow: hidden;
}

.process-log-column-head,
.process-log-line {
  display: grid;
  grid-template-columns: var(--process-log-columns);
  gap: var(--vk-space-control);
}

.process-log-column-head {
  align-items: center;
  padding: 0 var(--vk-space-cluster);
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 48%, transparent);
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-weight: var(--vk-weight-strong);
  letter-spacing: var(--vk-tracking-meta);
}

.process-log-lines {
  min-width: 0;
  padding: 0 var(--vk-space-cluster) var(--vk-space-cluster);
  display: grid;
  font-family: var(--vk-font-mono);
  font-size: var(--vk-type-label-size);
  line-height: 1.55;
  scrollbar-gutter: stable;
}

.process-log-lines-inner {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: var(--vk-space-control);
}

.process-log-lines-inner::before {
  content: "";
  margin-top: auto;
}

.process-log-line {
  align-items: baseline;
  padding: 3px 0;
  color: color-mix(in srgb, var(--vk-text) 88%, var(--vk-muted));
}

.process-log-time,
.process-log-step {
  color: var(--vk-muted);
}

.process-log-time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.process-log-step,
.process-log-message {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.process-log-step {
  white-space: nowrap;
}

.process-log-message {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: baseline;
  gap: var(--vk-space-sm);
  white-space: normal;
}

.process-log-message-text {
  min-width: 0;
  overflow-wrap: break-word;
}

.process-log-outcome {
  align-self: start;
  padding: 1px 6px;
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-hover) 82%, transparent);
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-family: var(--vk-font-ui);
  line-height: 1.45;
  white-space: nowrap;
}

.process-log-outcome.is-success {
  background: color-mix(in srgb, var(--vk-accent) 14%, transparent);
  color: var(--vk-accent-strong);
}

.process-log-outcome.is-error {
  background: color-mix(in srgb, var(--vk-danger) 10%, transparent);
  color: var(--vk-danger);
}

.process-log-outcome.is-warn {
  background: color-mix(in srgb, var(--vk-warning) 12%, transparent);
  color: var(--vk-warning);
}

.process-log-line.is-success .process-log-message {
  color: var(--vk-accent-strong);
}

.process-log-line.is-error .process-log-message {
  color: var(--vk-danger);
}

.process-log-line.is-warn .process-log-message {
  color: var(--vk-warning);
}

.process-log-follow {
  position: absolute;
  right: var(--vk-space-panel);
  bottom: var(--vk-space-cluster);
  min-height: 28px;
  padding: 0 var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-border) 82%, transparent);
  border-radius: var(--vk-radius-control);
  background: var(--vk-bg-panel);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-meta-size);
  cursor: pointer;
}

.process-log-follow:hover {
  background: var(--vk-bg-hover);
}

.process-log-follow:focus-visible {
  box-shadow: var(--vk-focus-ring);
  outline: none;
}

.process-log-empty {
  padding: 16px 8px;
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
}

@container (max-width: 680px) {
  .process-log-column-head,
  .process-log-line {
    grid-template-columns: 58px minmax(0, 1fr);
  }

  .process-log-column-head span:nth-child(2),
  .process-log-step {
    display: none;
  }
}

@media (max-width: 760px) {
  .process-log-body {
    --process-log-columns: 58px minmax(0, 1fr);
    grid-template-columns: 1fr;
  }

  .process-log-task-resizer {
    display: none;
  }

  .process-log-tasks {
    max-height: 92px;
    border-right: 0;
    border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  }

  .process-log-output {
    min-height: 120px;
  }

  .process-log-usage {
    display: none;
  }

  .process-log-column-head span:nth-child(2),
  .process-log-step {
    display: none;
  }
}
</style>
