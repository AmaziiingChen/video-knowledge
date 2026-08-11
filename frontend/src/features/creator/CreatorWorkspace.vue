<template>
  <section class="creator-workspace manager-surface" aria-label="创作者采集">
    <form class="creator-form" @submit.prevent="preview">
      <label class="creator-field creator-url-field">
        <span>订阅链接</span>
        <div class="creator-url-row">
          <el-input
            v-model.trim="sourceUrl"
            type="url"
            name="creator-source-url"
            autocomplete="url"
            spellcheck="false"
            clearable
            placeholder="粘贴 B站、抖音链接，或小红书个人主页的收藏页链接"
          />
          <el-button type="primary" native-type="submit" :loading="previewing" :disabled="syncingPreview || Boolean(syncingSourceId)">{{ previewing ? '正在搜索' : '搜索' }}</el-button>
        </div>
      </label>
      <div class="creator-form-options">
        <label class="creator-field">
          <span>发布日期</span>
          <div class="creator-date-range" role="group" aria-label="采集发布日期范围">
            <el-date-picker
              v-model="sourceFrom"
              name="creator-published-from"
              type="date"
              clearable
              placeholder="开始日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              placement="bottom-start"
              aria-label="采集开始日期"
            />
            <span aria-hidden="true">至</span>
            <el-date-picker
              v-model="sourceTo"
              name="creator-published-to"
              type="date"
              clearable
              placeholder="结束日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              placement="bottom-start"
              aria-label="采集结束日期"
            />
          </div>
        </label>
        <label class="creator-field">
          <span>首次导入数量</span>
          <el-input-number
            v-model="previewLimit"
            name="creator-preview-limit"
            :min="1"
            :max="500"
            :step="1"
            :controls="false"
            aria-label="首次导入数量"
          />
        </label>
        <label class="creator-field">
          <span>自动检查</span>
          <el-select v-model="syncIntervalMinutes" name="creator-sync-interval" aria-label="自动检查频率">
            <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </label>
        <label class="creator-field">
          <span>新作品处理</span>
          <el-select v-model="processingMode" name="creator-processing-mode" aria-label="发现新作品后的处理方式">
            <el-option v-for="option in processingOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </label>
      </div>
      <p class="creator-policy-note">首次订阅最多读取这里设置的数量；之后每次检查都会从最新作品向前读取，直到遇到本订阅已记录的作品为止。个人喜欢、收藏仅使用当前设备的本地登录态读取；小红书采集目前暂不开放。</p>
    </form>

    <section v-if="previewData" class="creator-preview" aria-labelledby="creator-preview-title">
      <header class="creator-preview-head">
        <div>
          <h2 id="creator-preview-title">{{ previewData.collection_name || previewData.creator_name }}</h2>
          <span>{{ providerLabel(previewData.provider) }} · {{ sourceKindLabel(previewData.source_kind) }}</span>
          <p v-if="previewData.collection_name && previewData.creator_name" class="creator-preview-meta">创作者：{{ previewData.creator_name }}</p>
          <p v-if="previewData.creator_description" class="creator-preview-meta">{{ previewData.creator_description }}</p>
        </div>
        <div class="creator-preview-actions">
          <span>{{ previewModeLabel }} · 已加载 {{ previewData.videos.length }} 条 · 已选 {{ selectedVideoIds.length }} 条</span>
          <el-button type="primary" :loading="syncingPreview" :disabled="!selectedVideoIds.length || previewing || Boolean(syncingSourceId)" @click="sync">{{ primaryActionLabel }}</el-button>
        </div>
      </header>

      <div v-if="previewData.videos.length" class="creator-filter-bar">
        <div class="creator-filter-controls">
          <el-input v-model.trim="titleFilter" clearable name="creator-title-filter" autocomplete="off" placeholder="筛选标题关键词" aria-label="筛选标题关键词" />
          <el-date-picker
            v-model="previewDateRange"
            type="daterange"
            unlink-panels
            clearable
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            aria-label="作品发布时间范围"
          />
          <el-select v-model="durationFilter" aria-label="视频时长">
            <el-option v-for="option in durationOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-input v-model.trim="excludeTitleTerms" clearable name="creator-exclude-terms" autocomplete="off" placeholder="排除词，如广告、推广" aria-label="排除标题关键词" />
        </div>
        <div class="creator-filter-actions">
          <el-button size="small" @click="selectOnlyFilteredVideos">仅选筛选结果</el-button>
          <el-button size="small" text @click="selectFilteredVideos">追加筛选结果</el-button>
          <el-button size="small" text :disabled="!selectedVideoIds.length" @click="clearVideoSelection">清空选择</el-button>
        </div>
      </div>

      <div v-if="previewData.videos.length" class="creator-queue-estimate">
        <strong>本次计划</strong>
        <span>已选 {{ selectedVideoIds.length }} 条 · 素材总时长 {{ selectedDurationLabel }}</span>
        <span>{{ processingMode === 'metadata' ? '将进入收件箱' : '将按顺序进入处理队列' }}</span>
        <span>当前处理队列 {{ activeTaskCount }} 条</span>
      </div>

      <p v-if="!previewData.videos.length" class="creator-empty">没有取得符合当前筛选条件的候选作品。</p>
      <ol v-else class="creator-video-list">
        <li v-for="video in filteredVideos" :key="video.canonical_id" :class="{ 'is-selected': isVideoSelected(video.canonical_id) }">
          <el-checkbox
            class="creator-video-select"
            :model-value="isVideoSelected(video.canonical_id)"
            :aria-label="`选择 ${video.title}`"
            @update:model-value="setVideoSelected(video.canonical_id, $event)"
          />
          <img v-if="video.cover_url" :src="video.cover_url" alt="" loading="lazy">
          <div>
            <strong>{{ video.title }}</strong>
            <span>{{ video.canonical_id }}<template v-if="video.published_at"> · {{ formatDate(video.published_at) }}</template><template v-if="video.duration_seconds"> · {{ formatDuration(video.duration_seconds) }}</template></span>
            <small v-if="video.description && video.description !== video.title">{{ video.description }}</small>
            <small v-if="statsLabel(video.stats)">{{ statsLabel(video.stats) }}</small>
          </div>
        </li>
      </ol>
      <p v-if="previewData.videos.length && !filteredVideos.length" class="creator-empty">没有符合当前筛选条件的作品。</p>
    </section>

    <section v-if="sources.length" class="creator-sources" aria-labelledby="creator-sources-title">
      <header class="creator-sources-head"><h2 id="creator-sources-title">已订阅来源</h2></header>
      <div class="creator-sources-table-scroll vk-scroll-area">
        <div class="creator-sources-table-head" role="row">
          <span class="column-source">来源</span><span class="column-activity">活动</span><span class="column-analysis">处理方式</span><span class="column-enabled">自动检查</span><span class="column-frequency">检查频率</span><span class="column-actions">操作</span>
        </div>
        <article v-for="source in sources" :key="source.id" class="creator-source-row" role="row">
          <span class="creator-source-cell column-source">
            <button type="button" class="creator-source-main" :aria-label="`使用 ${source.creator_name || '未命名创作者'} 的设置`" @click="reuseSource(source)">
              <strong>{{ source.creator_name || '未命名创作者' }}</strong>
              <small>{{ providerLabel(source.provider) }} · {{ sourceKindLabel(source.source_kind) }}</small>
            </button>
          </span>
          <span class="creator-source-activity column-activity">
            <el-tooltip v-if="source.last_error" placement="top" :show-after="160" popper-class="creator-source-error-tooltip">
              <template #content><div class="creator-source-error-tooltip-copy">{{ source.last_error }}</div></template>
              <button type="button" class="creator-source-error-trigger" :aria-label="`查看 ${source.creator_name || '创作者'} 的同步失败原因`">
                <strong class="is-error">同步失败</strong>
              </button>
            </el-tooltip>
            <strong v-else>新增 {{ source.last_created_count || 0 }} 条</strong>
            <small>{{ source.last_error ? '悬浮查看原因' : `上次 ${formatTime(source.last_sync_at)}` }}</small>
          </span>
          <span class="creator-source-setting-cell column-analysis">
            <el-select :model-value="source.processing_mode || (source.auto_process ? 'full' : 'metadata')" size="small" :disabled="sourceBusy(source)" :aria-label="`${source.creator_name || '创作者'}的处理方式`" @update:model-value="updateSource(source, { processing_mode: $event })">
              <el-option v-for="option in processingOptions" :key="option.value" :label="option.shortLabel" :value="option.value" />
            </el-select>
          </span>
          <span class="creator-source-setting-cell column-enabled">
            <el-switch :model-value="source.enabled" :disabled="sourceBusy(source)" :aria-label="`${source.creator_name || '创作者'}自动检查`" @update:model-value="updateSource(source, { enabled: $event })" />
          </span>
          <span class="creator-source-setting-cell column-frequency">
            <el-select :model-value="source.sync_interval_minutes" size="small" :disabled="sourceBusy(source)" :aria-label="`${source.creator_name || '创作者'}的检查频率`" @update:model-value="updateSource(source, { sync_interval_minutes: Number($event) })">
              <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </span>
          <span class="creator-source-actions column-actions">
            <el-button text size="small" :loading="syncingSourceId === source.id" :disabled="!source.enabled || previewing || syncingPreview || Boolean(syncingSourceId)" @click="syncSource(source)">检查</el-button>
            <el-dropdown trigger="click" placement="bottom-end" @command="handleSourceAction($event, source)">
              <button type="button" class="creator-source-more" :disabled="sourceBusy(source)" :aria-label="`${source.creator_name || '创作者'}的更多操作`">
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="retry" :disabled="sourceBusy(source)">重试失败项</el-dropdown-item>
                  <el-dropdown-item divided command="remove" :disabled="sourceBusy(source)" class="creator-source-remove-menu-item">取消订阅</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </article>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { MoreFilled } from '../../components/macosSymbolComponents.js'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm'
import { enqueueSourceSyncTask, observeSourceSyncTask } from '../../utils/sourceSyncTask'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const emit = defineEmits(['library-changed', 'processing-started'])
const sourceUrl = ref('')
const allowPersonalSources = ref(true)
const sourceFrom = ref('')
const sourceTo = ref('')
const syncIntervalMinutes = ref(360)
const processingMode = ref('full')
const previewLimit = ref(50)
const previewData = ref(null)
const sources = ref([])
const previewing = ref(false)
const syncingPreview = ref(false)
const syncingSourceId = ref('')
const updatingSourceId = ref('')
const selectedVideoIds = ref([])
const titleFilter = ref('')
const excludeTitleTerms = ref('')
const previewFrom = ref('')
const previewTo = ref('')
const durationFilter = ref('all')
const activeTaskCount = ref(0)

const intervalOptions = [
  { value: 30, label: '每 30 分钟' }, { value: 60, label: '每小时' }, { value: 180, label: '每 3 小时' },
  { value: 360, label: '每 6 小时' }, { value: 720, label: '每 12 小时' }, { value: 1440, label: '每天' },
]
const processingOptions = [
  { value: 'full', label: '完整分析（下载、字幕、AI 总结）', shortLabel: '完整分析' },
  { value: 'transcript', label: '仅字幕（下载、转写，不总结）', shortLabel: '仅字幕' },
  { value: 'metadata', label: '仅元数据（进入收件箱）', shortLabel: '仅元数据' },
]
const durationOptions = [
  { value: 'all', label: '全部时长' }, { value: 'short', label: '短视频（≤ 3 分钟）' }, { value: 'long', label: '长视频（＞ 3 分钟）' },
]

const previewDateRange = computed({
  get: () => previewFrom.value && previewTo.value ? [previewFrom.value, previewTo.value] : [],
  set: (value) => {
    previewFrom.value = value?.[0] || ''
    previewTo.value = value?.[1] || ''
  },
})

const filteredVideos = computed(() => {
  const videos = previewData.value?.videos || []
  const keyword = titleFilter.value.toLocaleLowerCase()
  const excluded = excludeTitleTerms.value
    .split(/[，,]/)
    .map((item) => item.trim().toLocaleLowerCase())
    .filter(Boolean)
  return videos.filter((video) => {
    const title = String(video.title || '').toLocaleLowerCase()
    if (keyword && !title.includes(keyword)) return false
    if (excluded.some((term) => title.includes(term))) return false
    const published = String(video.published_at || '').slice(0, 10)
    if (previewFrom.value && (!published || published < previewFrom.value)) return false
    if (previewTo.value && (!published || published > previewTo.value)) return false
    const duration = Number(video.duration_seconds || 0)
    if (durationFilter.value === 'short' && duration > 180) return false
    if (durationFilter.value === 'long' && duration <= 180) return false
    return true
  })
})

const selectedVideos = computed(() => {
  const selected = new Set(selectedVideoIds.value)
  return (previewData.value?.videos || []).filter((video) => selected.has(video.canonical_id))
})

const selectedDurationLabel = computed(() => {
  const seconds = selectedVideos.value.reduce((total, video) => total + Math.max(0, Number(video.duration_seconds || 0)), 0)
  return seconds ? formatDuration(seconds) : '时长待采集'
})
const primaryActionLabel = computed(() => '订阅')
const previewModeLabel = computed(() => `首次最多读取 ${previewLimit.value} 条`)

function sourceKindLabel(kind) {
  return ({ profile: '主页作品', profile_compilations: '主页合集', collection: '合集', series: '系列', channel_series: '频道系列', channel_collection: '频道合集', favorites: '收藏夹', likes: '喜欢' })[kind] || '作品来源'
}

function providerLabel(provider) {
  return ({ douyin: '抖音', bilibili: 'B站', xiaohongshu: '小红书' })[provider] || '内容来源'
}

function statsLabel(stats) {
  const labels = { play: '播放', like: '赞', favorite: '收藏', comment: '评', share: '转发', coin: '投币', danmaku: '弹幕' }
  return Object.entries(stats || {})
    .filter(([, value]) => Number(value) > 0)
    .slice(0, 4)
    .map(([key, value]) => `${labels[key] || key} ${Number(value).toLocaleString()}`)
    .join(' · ')
}

function requestPayload({ includeSelection = false } = {}) {
  if (!sourceUrl.value) throw new Error('请先粘贴订阅链接')
  return {
    source_url: sourceUrl.value,
    limit: previewLimit.value,
    published_after: sourceFrom.value || null,
    published_before: sourceTo.value || null,
    auto_process: processingMode.value !== 'metadata',
    sync_interval_minutes: syncIntervalMinutes.value,
    processing_mode: processingMode.value,
    allow_personal_sources: allowPersonalSources.value,
    ...(includeSelection ? { selected_video_ids: [...selectedVideoIds.value] } : {}),
  }
}

async function preview() {
  try {
    previewing.value = true
    // Preview is an interactive discovery step rather than a queued sync, but
    // it can legitimately read a large creator archive. Do not present a
    // healthy server-side lookup as a client failure at an arbitrary minute.
    const response = await axios.post(`${API}/creator-sources/preview`, requestPayload(), { timeout: 0 })
    previewData.value = response.data
    selectedVideoIds.value = response.data.videos.map((video) => video.canonical_id)
    await loadQueuePressure()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '预览失败')
  } finally {
    previewing.value = false
  }
}

function handleSourceAction(command, source) {
  if (command === 'retry') return syncSource(source, { retryFailedItems: true })
  if (command === 'remove') return removeSource(source)
}

async function sync() {
  try {
    syncingPreview.value = true
    const task = await enqueueSourceSyncTask({
      kind: 'creator_new',
      source_title: '创作者同步',
      source_url: sourceUrl.value,
      payload: requestPayload({ includeSelection: true }),
    })
    ElMessage.success('已开始订阅并同步来源')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`同步完成：新增 ${result.created_count || 0} 条；入队 ${result.queued_count || 0} 条，收件箱 ${result.inbox_count || 0} 条`)
        await loadSources()
        emit('library-changed')
        if (result.task_ids?.length) emit('processing-started', { taskIds: result.task_ids, contentItemIds: result.content_item_ids || [] })
      },
      onFailed: (message) => ElMessage.error(message || '创作者同步失败'),
    })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '创建同步任务失败')
  } finally {
    syncingPreview.value = false
  }
}

async function loadQueuePressure() {
  try {
    const response = await axios.get(`${API}/tasks`, { timeout: 10000 })
    activeTaskCount.value = (response.data || []).filter((task) => ['queued', 'running'].includes(task.status)).length
  } catch {
    activeTaskCount.value = 0
  }
}

function selectFilteredVideos() {
  const selected = new Set(selectedVideoIds.value)
  filteredVideos.value.forEach((video) => selected.add(video.canonical_id))
  selectedVideoIds.value = [...selected]
}

function selectOnlyFilteredVideos() {
  selectedVideoIds.value = filteredVideos.value.map((video) => video.canonical_id)
}

function clearVideoSelection() {
  selectedVideoIds.value = []
}

function isVideoSelected(videoId) {
  return selectedVideoIds.value.includes(videoId)
}

function setVideoSelected(videoId, selected) {
  const selection = new Set(selectedVideoIds.value)
  if (selected) selection.add(videoId)
  else selection.delete(videoId)
  selectedVideoIds.value = [...selection]
}

async function loadSources() {
  try {
    const response = await axios.get(`${API}/creator-sources`, { timeout: 10000 })
    sources.value = Array.isArray(response.data) ? response.data : []
  } catch {
    sources.value = []
  }
}

function reuseSource(source) {
  sourceUrl.value = source.source_url
  allowPersonalSources.value = true
  syncIntervalMinutes.value = source.sync_interval_minutes || 360
  processingMode.value = source.processing_mode || (source.auto_process ? 'full' : 'metadata')
  previewLimit.value = 50
  sourceFrom.value = ''
  sourceTo.value = ''
  previewData.value = null
}

async function syncSource(source, { retryFailedItems = false } = {}) {
  try {
    syncingSourceId.value = source.id
    const task = await enqueueSourceSyncTask({
      kind: 'creator_saved',
      source_title: source.creator_name || '创作者同步',
      source_url: source.source_url,
      source_id: source.id,
      retry_existing_items: retryFailedItems,
    })
    ElMessage.success(retryFailedItems ? '已开始检查更新并重试失败项' : '已开始检查创作者更新')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`同步完成：新增 ${result.created_count || 0} 条，跳过 ${result.duplicate_count || 0} 条已有作品`)
        await loadSources()
        emit('library-changed')
        if (result.task_ids?.length) emit('processing-started', { taskIds: result.task_ids, contentItemIds: result.content_item_ids || [] })
      },
      onFailed: (message) => ElMessage.error(message || '同步失败'),
    })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '同步失败')
  } finally {
    syncingSourceId.value = ''
  }
}

async function updateSource(source, patch) {
  try {
    updatingSourceId.value = source.id
    await axios.patch(`${API}/creator-sources/${encodeURIComponent(source.id)}`, patch, { timeout: 20000 })
    await loadSources()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '更新订阅失败')
  } finally {
    updatingSourceId.value = ''
  }
}

async function removeSource(source) {
  const confirmed = await requestDestructiveConfirmation({
    title: '取消订阅',
    message: `取消订阅“${source.creator_name || '该创作者'}”不会删除已经入库的内容。`,
    confirmLabel: '取消订阅',
  })
  if (!confirmed) return
  try {
    updatingSourceId.value = source.id
    await axios.delete(`${API}/creator-sources/${encodeURIComponent(source.id)}`, { timeout: 20000 })
    await loadSources()
    ElMessage.success('已取消订阅，已入库内容未删除')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消订阅失败')
  } finally {
    updatingSourceId.value = ''
  }
}

function sourceBusy(source) {
  return previewing.value || syncingPreview.value || syncingSourceId.value === source.id || updatingSourceId.value === source.id
}

function formatTime(value) {
  if (!value) return '尚未同步'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function formatDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value).slice(0, 10) : date.toLocaleDateString()
}

function processingModeLabel(mode) {
  return ({ metadata: '仅元数据', transcript: '仅字幕', full: '完整分析' })[mode] || '完整分析'
}

onMounted(loadSources)
</script>

<style scoped>
.creator-workspace { box-sizing: border-box; width: min(100%, 1060px); height: 100%; min-height: 0; margin: 0 auto; padding: 24px clamp(22px, 4vw, 38px) 38px; overflow-y: auto; overscroll-behavior: contain; color: var(--vk-text); }
.creator-form, .creator-preview, .creator-sources { overflow: hidden; border: 1px solid var(--vk-border); border-radius: var(--vk-radius-feature); background: var(--vk-bg-panel); }
.creator-form { display: grid; gap: var(--vk-space-panel); padding: 18px; }
.creator-policy-note { margin: 0; padding: 9px 11px; color: var(--vk-muted); background: color-mix(in srgb, var(--vk-bg-hover) 42%, transparent); border-left: 2px solid var(--vk-accent); font-size: var(--vk-type-meta-size); line-height: 1.55; }
.creator-field { display: grid; min-width: 0; gap: var(--vk-space-sm); color: var(--vk-muted); font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-medium); line-height: var(--vk-leading-label); }
.creator-url-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--vk-space-control); }
.creator-form-options { display: grid; grid-template-columns: minmax(230px, 1.35fr) minmax(120px, .65fr) repeat(2, minmax(130px, .8fr)); gap: var(--vk-space-cluster); }
.creator-date-range { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: var(--vk-space-xs); min-width: 0; }
.creator-date-range > span { color: var(--vk-muted); font-size: var(--vk-type-label-size); }
.creator-workspace :deep(.el-input), .creator-workspace :deep(.el-select), .creator-workspace :deep(.el-date-editor) { width: 100%; }
.creator-workspace :deep(.el-input-number) { width: 100%; }
.creator-workspace :deep(.el-input__wrapper), .creator-workspace :deep(.el-select__wrapper) { min-height: var(--vk-control-height-default); border-radius: var(--vk-radius-input); }
.creator-workspace :deep(.el-input-number .el-input__wrapper) { min-height: var(--vk-control-height-default); border: 1px solid var(--vk-border); border-radius: var(--vk-radius-input); box-shadow: none; }
.creator-workspace :deep(.el-date-editor.el-input), .creator-workspace :deep(.el-date-editor--daterange) { min-height: var(--vk-control-height-default); border-radius: var(--vk-radius-input); }
.creator-workspace :deep(.el-button) { border-radius: var(--vk-radius-control); transition: background-color var(--vk-motion-fast) var(--vk-ease-out), border-color var(--vk-motion-fast) var(--vk-ease-out), color var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out); }
.creator-workspace :deep(.el-button:active:not(.is-disabled)) { transform: scale(.985); }
.creator-url-row :deep(.el-button), .creator-preview-actions :deep(.el-button) { min-height: var(--vk-control-height-default); }
.creator-filter-actions :deep(.el-button) { min-height: var(--vk-control-height-compact); }
.creator-preview, .creator-sources { margin-top: var(--vk-space-section); }
.creator-sources { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; }
.creator-preview-head, .creator-sources-head { display: flex; align-items: center; justify-content: space-between; gap: var(--vk-space-panel); padding: 14px 18px; border-bottom: 1px solid var(--vk-border); }
.creator-preview-head > div:first-child { display: grid; gap: var(--vk-space-xs); min-width: 0; }
.creator-preview-head h2, .creator-sources-head h2 { margin: 0; color: var(--vk-text); font-size: var(--vk-type-heading-size); font-weight: var(--vk-weight-display); letter-spacing: var(--vk-tracking-heading); line-height: var(--vk-leading-heading); text-wrap: balance; }
.creator-preview-head span, .creator-video-list span, .creator-source-main small { color: var(--vk-muted); font-size: var(--vk-type-meta-size); line-height: var(--vk-leading-label); }
.creator-preview-actions { display: inline-flex; flex: 0 0 auto; align-items: center; gap: var(--vk-space-control); color: var(--vk-muted); font-size: var(--vk-type-meta-size); font-variant-numeric: tabular-nums; white-space: nowrap; }
.creator-filter-bar { display: grid; gap: var(--vk-space-control); padding: 12px 18px; border-bottom: 1px solid var(--vk-border); background: color-mix(in srgb, var(--vk-bg-hover) 28%, transparent); }
.creator-filter-controls { display: grid; grid-template-columns: minmax(150px, 1fr) minmax(230px, 1.15fr) minmax(130px, .75fr) minmax(150px, 1fr); gap: var(--vk-space-control); min-width: 0; }
.creator-filter-bar :deep(.el-input__wrapper), .creator-filter-bar :deep(.el-select__wrapper) { min-height: 32px; border-radius: var(--vk-radius-control); }
.creator-filter-bar :deep(.el-date-editor) { min-height: 32px; border-radius: var(--vk-radius-control); }
.creator-filter-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: var(--vk-space-xs); min-width: 0; }
.creator-queue-estimate { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 10px; padding: 10px 18px; border-bottom: 1px solid var(--vk-border); color: var(--vk-muted); font-size: var(--vk-type-meta-size); font-variant-numeric: tabular-nums; line-height: var(--vk-leading-label); }
.creator-queue-estimate strong { color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-strong); }
.creator-empty { margin: 0; padding: 18px; color: var(--vk-muted); font-size: var(--vk-type-body-size); }
.creator-video-list { display: grid; gap: 1px; margin: 0; padding: 0; list-style: none; }
.creator-video-list li { display: flex; align-items: center; gap: var(--vk-space-cluster); min-height: 62px; padding: 8px 18px; background: var(--vk-bg-panel); transition: background-color var(--vk-motion-fast) var(--vk-ease-out); }
.creator-video-list li:hover { background: color-mix(in srgb, var(--vk-bg-hover) 44%, transparent); }
.creator-video-list li.is-selected { background: color-mix(in srgb, var(--vk-accent) 10%, var(--vk-bg-panel)); }
.creator-video-list :deep(.el-checkbox) { display: inline-flex; flex: 0 0 18px; align-items: center; justify-content: center; width: 18px; height: 18px; margin-right: 0; }
.creator-video-list :deep(.el-checkbox__input) { display: inline-flex; align-items: center; justify-content: center; }
.creator-video-list :deep(.el-checkbox__inner) { width: 16px; height: 16px; border-radius: var(--vk-radius-compact); }
.creator-video-list img { width: 74px; height: 44px; flex: 0 0 auto; border-radius: var(--vk-radius-control); outline: 1px solid color-mix(in srgb, var(--vk-text) 10%, transparent); object-fit: cover; background: var(--vk-bg-quiet); }
.creator-video-list div { display: grid; min-width: 0; gap: var(--vk-space-xs); }
.creator-video-list strong { overflow: hidden; color: var(--vk-text); font-size: var(--vk-type-body-size); font-weight: var(--vk-weight-strong); text-overflow: ellipsis; white-space: nowrap; }
.creator-sources-table-scroll { container-type: inline-size; min-width: 0; overflow: auto; scrollbar-gutter: stable; overscroll-behavior: contain; }
.creator-sources-table-head,
.creator-source-row { display: grid; grid-template-columns: minmax(156px, 1.12fr) minmax(116px, .7fr) minmax(104px, .62fr) minmax(74px, .42fr) 112px minmax(112px, .68fr); column-gap: var(--vk-space-cluster); width: 100%; min-width: 830px; padding: 0 18px; transition: grid-template-columns var(--vk-motion-standard) var(--vk-ease-out); }
.creator-sources-table-head { position: sticky; top: 0; z-index: 1; min-height: 40px; background: color-mix(in srgb, var(--vk-bg-hover) 34%, var(--vk-bg-panel)); color: var(--vk-muted); font-size: var(--vk-type-meta-size); font-weight: 650; letter-spacing: var(--vk-tracking-meta); }
.creator-sources-table-head > span { display: flex; align-items: center; justify-content: center; min-width: 0; text-align: center; white-space: nowrap; }
.creator-source-row { min-height: 64px; border-top: 1px solid var(--vk-border); transition: background-color var(--vk-motion-fast) var(--vk-ease-out); }
.creator-source-row:hover { background: color-mix(in srgb, var(--vk-accent) 4%, transparent); }
.creator-source-row > span,
.creator-sources-table-head > span { min-width: 0; transition: opacity var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out), visibility var(--vk-motion-fast) var(--vk-ease-out); }
.creator-source-cell { display: flex; align-items: center; min-width: 0; }
.creator-source-main { display: grid; min-width: 0; gap: var(--vk-space-xs); padding: 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.creator-source-main:hover strong, .creator-source-main:focus-visible strong { color: var(--vk-accent-strong); }
.creator-source-main:focus-visible { outline: none; box-shadow: var(--vk-focus-ring); border-radius: var(--vk-radius-compact); }
.creator-source-main strong { overflow: hidden; color: var(--vk-text); font-size: var(--vk-type-body-size); font-weight: var(--vk-weight-strong); text-overflow: ellipsis; white-space: nowrap; }
.creator-source-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creator-source-error { color: var(--vk-error-text) !important; }
.creator-source-activity { display: grid; align-content: center; justify-items: center; gap: 3px; min-width: 0; text-align: center; }
.creator-source-activity strong, .creator-source-activity small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creator-source-activity strong { color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: var(--vk-weight-strong); }
.creator-source-activity strong.is-error { color: var(--vk-danger); }
.creator-source-activity small { color: var(--vk-muted); font-size: var(--vk-type-meta-size); }
.creator-source-error-trigger { max-width: 100%; padding: 2px 5px; overflow: hidden; border: 0; border-radius: var(--vk-radius-compact); background: transparent; color: inherit; cursor: help; }
.creator-source-error-trigger:hover, .creator-source-error-trigger:focus-visible { background: color-mix(in srgb, var(--vk-danger) 8%, transparent); outline: none; }
.creator-source-error-trigger:focus-visible { box-shadow: var(--vk-focus-ring); }
.creator-source-error-tooltip-copy { max-width: min(360px, calc(100vw - 44px)); color: var(--vk-text); font-size: var(--vk-type-meta-size); line-height: 1.5; overflow-wrap: anywhere; white-space: pre-wrap; }
:global(.creator-source-error-tooltip.el-popper) { max-width: min(380px, calc(100vw - 32px)); padding: 9px 11px; border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent); border-radius: var(--vk-radius-surface); background: color-mix(in srgb, var(--vk-bg-panel) 94%, transparent); box-shadow: 0 14px 30px color-mix(in srgb, var(--vk-text) 13%, transparent), 0 1px 4px color-mix(in srgb, var(--vk-text) 8%, transparent); backdrop-filter: blur(18px) saturate(1.08); }
.creator-source-setting-cell { display: flex; align-items: center; justify-content: center; min-width: 0; }
.creator-source-setting-cell :deep(.el-select) { width: 112px; }
.creator-source-setting-cell :deep(.el-input-number) { width: 70px; }
.creator-source-setting-cell :deep(.el-input-number .el-input__wrapper) { min-height: 30px; }
.creator-source-setting-cell :deep(.el-select__wrapper) { min-height: 30px; border-radius: var(--vk-radius-input); }
.creator-source-actions { display: flex; flex-wrap: nowrap; align-items: center; justify-content: center; gap: var(--vk-space-xs); min-width: 0; white-space: nowrap; }
.creator-source-actions :deep(.el-button) { margin-left: 0; }
.creator-source-more { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; padding: 0; border: 0; border-radius: var(--vk-radius-control); color: var(--vk-muted); background: transparent; cursor: pointer; transition: background-color var(--vk-motion-fast) var(--vk-ease-out), color var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out); }
.creator-source-more:hover:not(:disabled) { color: var(--vk-text); background: color-mix(in srgb, var(--vk-bg-hover) 82%, transparent); }
.creator-source-more:focus-visible { outline: none; color: var(--vk-text); background: color-mix(in srgb, var(--vk-bg-hover) 82%, transparent); box-shadow: var(--vk-focus-ring); }
.creator-source-more:active:not(:disabled) { transform: scale(.985); }
.creator-source-more:disabled { opacity: .48; cursor: not-allowed; }
:global(.creator-source-remove-menu-item) { color: var(--vk-danger); }
:global(.creator-source-remove-menu-item:hover:not(.is-disabled)), :global(.creator-source-remove-menu-item:focus-visible:not(.is-disabled)) { color: var(--vk-danger); background: color-mix(in srgb, var(--vk-danger) 8%, transparent); }
.creator-source-actions :deep(.el-button.is-text), .creator-source-actions :deep(.el-button--text) { border-color: transparent; background: transparent; box-shadow: none; }
.creator-source-actions :deep(.manager-row-danger.el-button--danger) { color: var(--vk-muted); }
.creator-source-actions :deep(.manager-row-danger.el-button--danger:hover:not(.is-disabled)), .creator-source-actions :deep(.manager-row-danger.el-button--danger:focus-visible:not(.is-disabled)) { color: var(--vk-danger); background: color-mix(in srgb, var(--vk-danger) 8%, transparent); }
@media (max-width: 980px) { .creator-form-options { grid-template-columns: repeat(3, minmax(0, 1fr)); } .creator-filter-controls { grid-template-columns: minmax(150px, 1fr) minmax(220px, 1fr) minmax(130px, .75fr); } .creator-filter-controls > :nth-child(4) { grid-column: span 2; } }
@media (max-width: 680px) { .creator-workspace { padding: 18px 16px 28px; } .creator-url-row, .creator-form-options, .creator-filter-controls { grid-template-columns: 1fr; } .creator-preview-head { align-items: flex-start; flex-direction: column; } .creator-preview-actions { width: 100%; justify-content: space-between; } .creator-filter-controls > :nth-child(4) { grid-column: auto; } .creator-filter-actions { justify-content: flex-start; } .creator-video-list li { gap: var(--vk-space-control); padding: 8px 14px; } }

@media (prefers-reduced-motion: reduce) {
  .creator-sources-table-head,
  .creator-source-row,
  .creator-sources-table-head > span,
  .creator-source-row > span { transition: none; }
}
</style>
