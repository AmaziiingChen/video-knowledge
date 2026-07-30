<template>
  <section class="reports-workspace manager-surface" aria-labelledby="reports-workspace-title">
    <header class="reports-workspace-head">
      <div>
        <h2 id="reports-workspace-title">生成报告</h2>
      </div>
    </header>

    <section class="reports-workspace-card reports-workspace-groups" aria-labelledby="report-groups-title">
      <header class="reports-workspace-section-head">
        <div>
          <h3 id="report-groups-title">报告分组</h3>
        </div>
        <div class="reports-workspace-create">
          <el-input v-model="groupDraft" name="report-workspace-group" autocomplete="off" aria-label="新建报告分组" placeholder="例如：学术动态…" @keyup.enter="createGroup" />
          <el-button type="primary" :disabled="!groupDraft.trim()" @click="createGroup">新建分组</el-button>
        </div>
      </header>

      <div v-if="!reportGroups.length" class="reports-workspace-empty">
        <strong>还没有报告分组</strong>
        <p>先新建一个分组，再在公众号管理或网页管理中为来源归类。</p>
      </div>

      <div v-else class="reports-workspace-group-list">
        <article v-for="group in reportGroups" :key="group.id" class="reports-workspace-group-card">
          <div class="reports-workspace-group-main">
            <h3>{{ group.name }}</h3>
            <p :class="{ 'is-empty': !hasGroupSources(group) }">
              {{ groupSourceLabel(group) }}
              <template v-if="group.latest_report_content_item_id"> · 最近生成 {{ latestReportLabel(group) }}</template>
            </p>
          </div>
          <div class="reports-workspace-group-actions">
            <el-tooltip :content="group.schedule_enabled ? '关闭定时生成' : '开启定时生成'" placement="top">
              <el-button
                class="reports-schedule-toggle"
                :class="{ 'is-enabled': group.schedule_enabled }"
                size="small"
                circle
                :loading="savingScheduleGroupId === group.id"
                :aria-label="group.schedule_enabled ? `关闭 ${group.name} 的定时生成` : `开启 ${group.name} 的定时生成`"
                :aria-pressed="Boolean(group.schedule_enabled)"
                @click="toggleGroupSchedule(group)"
              ><span class="reports-schedule-clock" aria-hidden="true"></span></el-button>
            </el-tooltip>
            <el-popover
              trigger="click"
              placement="bottom"
              :width="312"
              :visible="scheduleEditorGroupId === group.id"
              popper-class="reports-schedule-popover"
              @update:visible="setScheduleEditorVisible(group, $event)"
            >
              <section class="reports-schedule-editor" aria-label="定时生成计划">
                <header>
                  <strong>定时生成</strong>
                  <span>{{ group.schedule_enabled ? '已开启' : '未开启' }}</span>
                </header>
                <el-radio-group v-model="scheduleDraft.reportType" size="small" aria-label="定时报告类型">
                  <el-radio-button label="weekly">生成周报</el-radio-button>
                  <el-radio-button label="daily">生成日报</el-radio-button>
                </el-radio-group>
                <div class="reports-schedule-days" role="group" aria-label="执行星期">
                  <button
                    v-for="day in weekdayOptions"
                    :key="day.value"
                    type="button"
                    :class="{ 'is-selected': scheduleDraft.weekdays.includes(day.value) }"
                    :aria-pressed="scheduleDraft.weekdays.includes(day.value)"
                    @click="toggleScheduleWeekday(day.value)"
                  >{{ day.label }}</button>
                </div>
                <div class="reports-schedule-time-row" @mousedown.stop @click.stop>
                  <span>执行时间</span>
                  <el-time-picker
                    v-model="scheduleDraft.timeOfDay"
                    format="HH:mm"
                    value-format="HH:mm"
                    :clearable="false"
                    aria-label="定时执行时间"
                    @visible-change="setScheduleTimePickerVisible"
                  />
                </div>
                <small>仅在应用保持运行时执行，不会自动发布公众号。</small>
                <el-button type="primary" size="small" :loading="savingScheduleGroupId === group.id" @click="saveGroupSchedule(group)">保存计划</el-button>
              </section>
              <template #reference>
                <button
                  type="button"
                  class="reports-schedule-display"
                  :class="{ 'is-enabled': group.schedule_enabled }"
                  :aria-label="`编辑 ${group.name} 的定时生成计划`"
                >{{ scheduleLabel(group) }}</button>
              </template>
            </el-popover>
            <el-button v-if="group.latest_report_content_item_id" class="reports-workspace-open-report" size="small" text @click="emit('open-report', group.latest_report_content_item_id)">打开报告</el-button>
            <template v-if="hasGroupSources(group)">
              <el-button size="small" :loading="isReportBusy(`${group.id}:daily`)" :disabled="deletingGroupId === group.id || anyReportBusy" @click="emit('generate-report', group.id, 'daily')">生成今日日报</el-button>
              <el-button size="small" :loading="isReportBusy(`${group.id}:weekly`)" :disabled="deletingGroupId === group.id || anyReportBusy" @click="emit('generate-report', group.id, 'weekly')">生成本周周报</el-button>
            </template>
            <el-popover
              trigger="click"
              placement="bottom-end"
              :width="260"
              :visible="sourceMenuGroupId === group.id"
              popper-class="reports-source-popover"
              @update:visible="sourceMenuGroupId = $event ? group.id : ''"
            >
              <div class="reports-source-menu">
                <button type="button" @click="openSourceManagement(group, 'wechat')">
                  <strong>公众号管理</strong>
                  <span>添加公众号来源</span>
                </button>
                <button type="button" @click="openSourceManagement(group, 'campus')">
                  <strong>网页管理</strong>
                  <span>添加校园来源</span>
                </button>
                <button type="button" @click="openSourceManagement(group, 'rss')">
                  <strong>RSS 订阅</strong>
                  <span>添加 RSS 来源</span>
                </button>
              </div>
              <template #reference>
                <el-button size="small" :type="hasGroupSources(group) ? undefined : 'primary'" :plain="!hasGroupSources(group)">添加来源</el-button>
              </template>
            </el-popover>
            <el-button size="small" :disabled="deletingGroupId === group.id" @click="emit('edit-sources', group)">编辑来源</el-button>
            <el-button class="reports-workspace-danger-action" size="small" text :loading="deletingGroupId === group.id" @click="requestGroupDeletion(group)">删除</el-button>
          </div>
        </article>
      </div>
    </section>

    <section class="reports-workspace-card reports-workspace-manual" aria-labelledby="manual-report-title">
      <header class="reports-workspace-section-head">
        <div><h3 id="manual-report-title">指定范围生成</h3></div>
        <div class="reports-workspace-range-presets" role="group" aria-label="常用时间范围">
          <el-button
            v-for="preset in rangePresets"
            :key="preset.value"
            size="small"
            :class="{ 'is-active': activeRangePreset === preset.value }"
            :aria-pressed="activeRangePreset === preset.value"
            @click="applyRangePreset(preset.value)"
          >{{ preset.label }}</el-button>
        </div>
      </header>
      <div class="reports-workspace-manual-body">
        <div class="reports-workspace-manual-controls">
          <el-select v-model="customReportGroupId" aria-label="区间汇总分组" placeholder="选择分组">
            <el-option v-for="group in reportGroups" :key="group.id" :label="group.name" :value="group.id" />
          </el-select>
          <el-date-picker
            v-model="customReportWindow"
            type="datetimerange"
            unlink-panels
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            format="YYYY-MM-DD HH:mm"
            value-format="x"
            :default-time="customReportDefaultTimes"
            aria-label="区间汇总开始和结束时间"
            @change="commitCustomReportWindow"
          />
          <el-input
            v-model="customReportFileName"
            class="reports-workspace-file-name"
            maxlength="96"
            aria-label="生成文件名"
            @input="customReportFileNameTouched = true"
          >
            <template #prepend>文件名</template>
          </el-input>
          <el-button type="primary" :loading="isReportBusy(`${customReportGroupId}:range`)" :disabled="!canGenerateCustomReport" @click="generateCustomReport">生成区间报告</el-button>
          <span v-if="customReportWindowError || customReportFileNameError" class="reports-workspace-manual-error">{{ customReportWindowError || customReportFileNameError }}</span>
        </div>
      </div>
    </section>

  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm'
import { shouldKeepScheduleEditorOpen } from './reportSchedulePopoverState.js'
import {
  defaultCustomReportWindow,
  normalizeReportWindow,
  reportWindowDates,
  validateCustomReportWindow,
} from '../wechat/reportWindow.js'

const props = defineProps({
  reportGroups: { type: Array, default: () => [] },
  generatingGroupId: { type: String, default: '' },
  preparingGroupId: { type: String, default: '' },
  deletingGroupId: { type: [String, Number], default: '' },
  savingScheduleGroupId: { type: String, default: '' },
})

const emit = defineEmits(['create-report-group', 'delete-report-group', 'generate-report', 'open-report', 'open-sources', 'edit-sources', 'save-report-schedule'])

const groupDraft = ref('')
const customReportGroupId = ref('')
const customReportWindow = ref(defaultCustomReportWindow())
const customReportFileName = ref('')
const customReportFileNameTouched = ref(false)
const customReportDefaultTimes = [new Date(2000, 0, 1, 0, 0, 0), new Date(2000, 0, 1, 23, 59, 59)]
const activeRangePreset = ref('today')
const sourceMenuGroupId = ref('')
const scheduleEditorGroupId = ref('')
const scheduleDraft = ref({ reportType: 'weekly', weekdays: [1], timeOfDay: '09:00' })
const scheduleTimePickerOpen = ref(false)
const scheduleTimePickerClosing = ref(false)
let scheduleTimePickerCloseGuardTimer = 0
const rangePresets = [
  { value: 'today', label: '今天' },
  { value: 'this-week', label: '本周' },
  { value: 'last-7-days', label: '近 7 天' },
  { value: 'last-week', label: '上周' },
]
const weekdayOptions = [
  { value: 1, label: '一' }, { value: 2, label: '二' }, { value: 3, label: '三' },
  { value: 4, label: '四' }, { value: 5, label: '五' }, { value: 6, label: '六' }, { value: 7, label: '日' },
]

const customReportWindowError = computed(() => validateCustomReportWindow(customReportWindow.value))
const customReportFileNameError = computed(() => customReportFileName.value.trim() ? '' : '请输入生成文件名')
const anyReportBusy = computed(() => Boolean(props.generatingGroupId || props.preparingGroupId))
const canGenerateCustomReport = computed(() => (
  Boolean(customReportGroupId.value)
  && !customReportWindowError.value
  && !customReportFileNameError.value
  && !anyReportBusy.value
))

watch(() => props.reportGroups, (groups) => {
  if (groups.some((group) => group.id === customReportGroupId.value)) return
  customReportGroupId.value = groups[0]?.id || ''
}, { immediate: true })

watch([customReportGroupId, customReportWindow], () => {
  if (!customReportFileNameTouched.value) customReportFileName.value = defaultReportFileName()
}, { immediate: true })

function createGroup() {
  const name = groupDraft.value.trim()
  if (!name) return
  emit('create-report-group', { name }, () => { groupDraft.value = '' })
}

function commitCustomReportWindow(value) {
  customReportWindow.value = normalizeReportWindow(value)
  activeRangePreset.value = ''
}

function applyRangePreset(preset) {
  activeRangePreset.value = preset
  customReportWindow.value = reportWindowForPreset(preset)
}

function reportWindowForPreset(preset, now = new Date()) {
  const end = new Date(now)
  const start = startOfDay(now)
  if (preset === 'this-week') return [startOfWeek(now).getTime(), end.getTime()]
  if (preset === 'last-7-days') {
    start.setDate(start.getDate() - 6)
    return [start.getTime(), end.getTime()]
  }
  if (preset === 'last-week') {
    const currentWeek = startOfWeek(now)
    const previousWeek = new Date(currentWeek)
    previousWeek.setDate(previousWeek.getDate() - 7)
    const previousWeekEnd = new Date(currentWeek)
    previousWeekEnd.setMilliseconds(previousWeekEnd.getMilliseconds() - 1)
    return [previousWeek.getTime(), previousWeekEnd.getTime()]
  }
  return [start.getTime(), end.getTime()]
}

function startOfDay(value) {
  const date = new Date(value)
  date.setHours(0, 0, 0, 0)
  return date
}

function startOfWeek(value) {
  const date = startOfDay(value)
  const day = date.getDay() || 7
  date.setDate(date.getDate() - day + 1)
  return date
}

function hasGroupSources(group) {
  if (Number.isFinite(Number(group?.source_count))) return Number(group.source_count) > 0
  return Number(group?.subscription_count || 0) > 0
}

function isReportBusy(reportKey) {
  return props.generatingGroupId === reportKey || props.preparingGroupId === reportKey
}

function groupSourceLabel(group) {
  const count = Number(group?.source_count ?? group?.subscription_count ?? 0)
  return count ? `${count} 个来源` : '尚未添加来源'
}

function latestReportLabel(group) {
  const timestamp = new Date(group?.latest_report_created_at || '')
  const type = { daily: '日报', weekly: '周报', range: '区间报告' }[group?.latest_report_type] || '报告'
  if (Number.isNaN(timestamp.getTime())) return type
  const date = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(timestamp)
  return `${date} ${type}`
}

function generateCustomReport() {
  if (!canGenerateCustomReport.value) return
  const [windowStart, windowEnd] = reportWindowDates(customReportWindow.value)
  emit('generate-report', customReportGroupId.value, 'range', {
    windowStart: windowStart.toISOString(),
    windowEnd: windowEnd.toISOString(),
    includeHistoryContext: false,
    fileName: customReportFileName.value.trim(),
  })
}

function scheduleWeekdays(group) {
  const weekdays = Array.isArray(group?.schedule_weekdays) ? group.schedule_weekdays : [1]
  return [...new Set(weekdays.map(Number).filter((day) => day >= 1 && day <= 7))].sort((a, b) => a - b)
}

function scheduleLabel(group) {
  const labels = scheduleWeekdays(group)
    .map((day) => weekdayOptions.find((option) => option.value === day)?.label)
    .filter(Boolean)
  return `周${labels.join('、')} · ${group?.schedule_time_of_day || '09:00'}`
}

function openScheduleEditor(group) {
  if (scheduleEditorGroupId.value !== group.id) resetScheduleTimePickerInteraction()
  scheduleEditorGroupId.value = group.id
  scheduleDraft.value = {
    reportType: group?.schedule_report_type === 'daily' ? 'daily' : 'weekly',
    weekdays: scheduleWeekdays(group),
    timeOfDay: group?.schedule_time_of_day || '09:00',
  }
}

function setScheduleEditorVisible(group, visible) {
  if (visible) openScheduleEditor(group)
  else if (
    scheduleEditorGroupId.value === group.id
    && !shouldKeepScheduleEditorOpen({
      timePickerOpen: scheduleTimePickerOpen.value,
      timePickerClosing: scheduleTimePickerClosing.value,
    })
  ) {
    scheduleEditorGroupId.value = ''
  }
}

function setScheduleTimePickerVisible(visible) {
  scheduleTimePickerOpen.value = Boolean(visible)
  window.clearTimeout(scheduleTimePickerCloseGuardTimer)
  scheduleTimePickerCloseGuardTimer = 0
  if (visible) {
    scheduleTimePickerClosing.value = false
    return
  }
  scheduleTimePickerClosing.value = true
  scheduleTimePickerCloseGuardTimer = window.setTimeout(() => {
    scheduleTimePickerClosing.value = false
    scheduleTimePickerCloseGuardTimer = 0
  }, 0)
}

function resetScheduleTimePickerInteraction() {
  window.clearTimeout(scheduleTimePickerCloseGuardTimer)
  scheduleTimePickerCloseGuardTimer = 0
  scheduleTimePickerOpen.value = false
  scheduleTimePickerClosing.value = false
}

function toggleScheduleWeekday(day) {
  const current = new Set(scheduleDraft.value.weekdays)
  if (current.has(day)) {
    if (current.size === 1) return
    current.delete(day)
  } else current.add(day)
  scheduleDraft.value = { ...scheduleDraft.value, weekdays: [...current].sort((a, b) => a - b) }
}

function schedulePayload(group, enabled) {
  return {
    enabled,
    report_type: group?.schedule_report_type === 'daily' ? 'daily' : 'weekly',
    weekdays: scheduleWeekdays(group),
    time_of_day: group?.schedule_time_of_day || '09:00',
  }
}

function toggleGroupSchedule(group) {
  emit('save-report-schedule', group.id, schedulePayload(group, !group.schedule_enabled))
}

function saveGroupSchedule(group) {
  emit('save-report-schedule', group.id, {
    enabled: Boolean(group.schedule_enabled),
    report_type: scheduleDraft.value.reportType,
    weekdays: scheduleDraft.value.weekdays,
    time_of_day: scheduleDraft.value.timeOfDay,
  }, () => {
    resetScheduleTimePickerInteraction()
    scheduleEditorGroupId.value = ''
  })
}

function defaultReportFileName() {
  const groupName = props.reportGroups.find((group) => group.id === customReportGroupId.value)?.name || '报告'
  const dates = reportWindowDates(customReportWindow.value)
  if (dates.length !== 2) return `${groupName}｜区间汇总`.slice(0, 96)
  const [start, end] = dates
  const format = (date) => {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }
  const startLabel = format(start)
  const endLabel = start.getFullYear() === end.getFullYear()
    ? `${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`
    : format(end)
  return `${groupName}｜${startLabel}${startLabel === format(end) ? '' : `至${endLabel}`}汇总`.slice(0, 96)
}

function openSourceManagement(group, source) {
  sourceMenuGroupId.value = ''
  emit('open-sources', { group, source })
}

async function requestGroupDeletion(group) {
  sourceMenuGroupId.value = ''
  const confirmed = await requestDestructiveConfirmation({
    title: '删除分组',
    message: `删除“${group?.name || '该分组'}”后，${deleteGroupDescription(group)}`,
    confirmLabel: '删除分组',
  })
  if (confirmed) emit('delete-report-group', group)
}

function deleteGroupDescription(group) {
  const count = Number(group?.source_count || 0)
  return `${count ? `将解除 ${count} 个来源的分组关联；` : ''}已生成的报告会保留。`
}

onBeforeUnmount(resetScheduleTimePickerInteraction)
</script>

<style scoped src="../../styles/reportsWorkspace.css"></style>
