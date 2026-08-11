<template>
  <el-dialog
    :model-value="modelValue"
    class="history-sync-dialog"
    width="min(560px, calc(100vw - 32px))"
    :show-close="false"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header="{ close }">
      <header class="history-sync-dialog-head">
        <div>
          <span>内容回溯</span>
          <h2>回溯历史文章</h2>
          <p>{{ sourceLabel }}</p>
        </div>
        <button type="button" class="history-sync-dialog-close" aria-label="关闭回溯历史文章" @click="close">
          <el-icon><Close /></el-icon>
        </button>
      </header>
    </template>

    <div class="history-sync-dialog-body">
      <section class="history-sync-contract">
        <strong>仅补充尚未入库的内容</strong>
        <span>新文章会按当前来源的处理方式入库，或加入自动分析队列。</span>
      </section>

      <fieldset class="history-sync-scope">
        <legend>检查范围</legend>
        <div class="history-sync-scope-options">
          <label v-for="option in scopeOptions" :key="option.value" :class="{ 'is-active': draft.mode === option.value }">
            <input v-model="draft.mode" type="radio" name="history-sync-mode" :value="option.value">
            <span>
              <strong>{{ option.label }}</strong>
              <small>{{ option.note }}</small>
            </span>
          </label>
        </div>
      </fieldset>

      <section v-if="draft.mode === 'count'" class="history-sync-setting" aria-label="最多检查文章数量">
        <label for="history-sync-max-items">最多检查</label>
        <div class="history-sync-number-control">
          <el-input-number id="history-sync-max-items" v-model="draft.maxItems" :min="1" :max="maxItems" controls-position="right" />
          <span>篇</span>
        </div>
      </section>

      <section v-else-if="draft.mode === 'date_range'" class="history-sync-setting" aria-label="发布日期范围">
        <span>发布日期范围</span>
        <div class="history-sync-date-presets" aria-label="常用日期范围">
          <button
            v-for="preset in datePresets"
            :key="preset.id"
            type="button"
            :class="{ 'is-active': activeDatePreset === preset.id }"
            @click="applyDatePreset(preset.id)"
          >{{ preset.label }}</button>
        </div>
        <el-date-picker
          v-model="draft.dateRange"
          class="history-sync-date-picker"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          aria-label="发布日期范围"
        />
        <p class="history-sync-range-summary" :class="{ 'is-invalid': dateRangeError }">
          {{ dateRangeError || dateRangeSummary }}
        </p>
      </section>

      <p v-else class="history-sync-all-note">会依次检查当前来源可访问的历史列表，单次最多 {{ maxItems }} 篇。</p>
    </div>

    <template #footer>
      <footer class="history-sync-dialog-footer">
        <span>范围越大，检查耗时越长。</span>
        <div>
          <el-button @click="emit('update:modelValue', false)">取消</el-button>
          <el-button type="primary" :disabled="!canConfirm" @click="confirm">开始回溯</el-button>
        </div>
      </footer>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { Close } from './macosSymbolComponents.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  sourceLabel: { type: String, default: '当前来源' },
  maxItems: { type: Number, default: 1000 }
})

const emit = defineEmits(['update:modelValue', 'confirm'])

const scopeOptions = [
  { value: 'count', label: '按文章数量', note: '从最新文章开始回溯' },
  { value: 'date_range', label: '按发布日期', note: '限定一段明确时间范围' },
  { value: 'all', label: '检查全部历史', note: '检查当前可访问的历史列表' }
]

const datePresets = [
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
  { id: 'month', label: '本月' },
  { id: 'last-month', label: '上月' },
]
const draft = reactive({ mode: 'count', maxItems: 50, dateRange: [] })
const publishedAfter = computed(() => draft.dateRange?.[0] || '')
const publishedBefore = computed(() => draft.dateRange?.[1] || '')
const dateRangeError = computed(() => {
  if (!publishedAfter.value || !publishedBefore.value) return '请选择开始和结束日期。'
  if (publishedAfter.value > publishedBefore.value) return '结束日期应晚于开始日期。'
  return ''
})
const dateRangeSummary = computed(() => {
  if (!publishedAfter.value || !publishedBefore.value) return '请选择要回溯的发布日期范围。'
  const start = parseLocalDate(publishedAfter.value)
  const end = parseLocalDate(publishedBefore.value)
  const days = Math.round((end - start) / 86400000) + 1
  return `${publishedAfter.value} 至 ${publishedBefore.value} · 共 ${days} 天`
})
const activeDatePreset = computed(() => datePresets.find((preset) => rangesEqual(datesForPreset(preset.id)))?.id || '')
const canConfirm = computed(() => draft.mode !== 'date_range' || !dateRangeError.value)

watch(() => props.modelValue, (open) => {
  if (!open) return
  draft.maxItems = Math.min(Math.max(1, Number(draft.maxItems) || 50), props.maxItems)
})

watch(() => draft.mode, (mode) => {
  if (mode === 'date_range' && (!publishedAfter.value || !publishedBefore.value)) applyDatePreset('30d')
})

function formatLocalDate(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseLocalDate(value) {
  const [year, month, day] = String(value).split('-').map(Number)
  return new Date(year, month - 1, day)
}

function datesForPreset(id) {
  const today = new Date()
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const start = new Date(end)
  if (id === '7d') start.setDate(end.getDate() - 6)
  if (id === '30d') start.setDate(end.getDate() - 29)
  if (id === 'month') start.setDate(1)
  if (id === 'last-month') {
    start.setDate(1)
    start.setMonth(start.getMonth() - 1)
    end.setDate(0)
  }
  return [formatLocalDate(start), formatLocalDate(end)]
}

function rangesEqual(range) {
  return Array.isArray(draft.dateRange)
    && draft.dateRange.length === 2
    && draft.dateRange[0] === range[0]
    && draft.dateRange[1] === range[1]
}

function applyDatePreset(id) {
  draft.dateRange = datesForPreset(id)
}

function confirm() {
  if (!canConfirm.value) return
  emit('confirm', {
    mode: draft.mode,
    max_items: draft.mode === 'count' ? draft.maxItems : undefined,
    published_after: draft.mode === 'date_range' ? publishedAfter.value : undefined,
    published_before: draft.mode === 'date_range' ? publishedBefore.value : undefined,
  })
}
</script>

<style src="../styles/historySyncDialog.css"></style>
