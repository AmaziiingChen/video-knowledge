<template>
  <section class="rss-manager manager-surface" aria-label="RSS 订阅" :aria-busy="loading">
    <header class="rss-manager-head">
      <div class="rss-manager-title">
        <h2>RSS 订阅</h2>
        <div class="rss-manager-title-meta">
          <span>{{ sources.length }} 个订阅</span>
          <span>{{ enabledSourceCount }} 个自动检查</span>
        </div>
      </div>
      <div class="rss-manager-head-actions">
        <el-button :disabled="!enabledSourceCount || checkingAll" :loading="checkingAll" @click="checkAll">
          <el-icon><Refresh /></el-icon>检查全部
        </el-button>
        <el-button type="primary" @click="subscriptionDialogOpen = true">
          <el-icon><Plus /></el-icon>新增订阅
        </el-button>
      </div>
    </header>

    <section class="rss-manager-card rss-manager-list-card" aria-label="RSS 订阅列表">
      <CollectionState v-if="loading && !sources.length" mode="loading" loading-label="正在读取 RSS 订阅" />
      <CollectionState
        v-else-if="!sources.length"
        title="还没有 RSS 订阅"
        description="点击右上角“新增订阅”，文章会出现在主页文件树的“RSS订阅”文件夹中。"
      />
      <div v-else class="rss-manager-table-scroll vk-scroll-area">
        <div class="rss-manager-table-head" role="row">
          <span class="column-source">订阅源</span><span class="column-group">分组</span><span class="column-activity">活动</span><span class="column-analysis">自动分析</span><span class="column-notification">通知</span><span class="column-enabled">自动检查</span><span class="column-frequency">检查频率</span><span class="rss-manager-table-actions-label column-actions">操作</span>
        </div>
        <div v-for="source in sources" :key="source.id" class="rss-manager-table-row" role="row">
          <span class="rss-manager-source-cell column-source">
            <img class="rss-manager-source-mark" :src="rssHubIcon" alt="">
            <span class="rss-manager-source-copy">
              <strong>{{ source.title || '未命名 RSS 订阅' }}</strong>
              <a :href="source.site_url || source.feed_url" target="_blank" rel="noreferrer" :title="source.feed_url">{{ source.feed_url }}</a>
            </span>
          </span>
          <span class="rss-manager-group-cell column-group">
            <ReportGroupMultiSelect
              :model-value="source.group_ids || []"
              :groups="reportGroups"
              :disabled="isBusy(source.id)"
              :aria-label="`${source.title || 'RSS 订阅'} 的报告分组`"
              @update:model-value="updateSource(source, { group_ids: $event })"
            />
          </span>
          <span class="rss-manager-activity-cell column-activity">
            <strong :class="sourceActivityClass(source)">{{ sourceActivityLabel(source) }}</strong>
            <small :title="source.last_error || ''">{{ sourceActivityMeta(source) }}</small>
          </span>
          <span class="rss-manager-source-setting-cell column-analysis">
            <el-switch :model-value="source.auto_analyze" :disabled="isBusy(source.id)" :aria-label="`${source.auto_analyze ? '关闭' : '开启'} ${source.title || 'RSS 订阅'} 的自动分析`" @update:model-value="updateSource(source, { auto_analyze: $event })" />
          </span>
          <span class="rss-manager-source-setting-cell column-notification">
            <el-switch :model-value="source.notify_on_new" :disabled="isBusy(source.id)" :aria-label="`${source.notify_on_new ? '关闭' : '开启'} ${source.title || 'RSS 订阅'} 的新文章通知`" @update:model-value="updateSource(source, { notify_on_new: $event })" />
          </span>
          <span class="rss-manager-source-setting-cell column-enabled">
            <el-switch :model-value="source.enabled" :disabled="isBusy(source.id)" :aria-label="`${source.enabled ? '暂停' : '启用'} ${source.title || 'RSS 订阅'} 的自动检查`" @update:model-value="updateSource(source, { enabled: $event })" />
          </span>
          <span class="rss-manager-source-setting-cell column-frequency">
            <el-select :model-value="source.sync_interval_minutes" size="small" :disabled="isBusy(source.id)" :aria-label="`${source.title || 'RSS 订阅'} 的检查频率`" @update:model-value="updateSource(source, { sync_interval_minutes: Number($event) })">
              <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </span>
          <span class="rss-manager-operation-cell column-actions">
            <el-button text size="small" :loading="checkingId === source.id" :disabled="isBusy(source.id) || !source.enabled" @click="checkSource(source)">
              {{ checkingId === source.id ? '检查中' : '检查' }}
            </el-button>
            <el-button text type="danger" size="small" class="manager-row-danger" :disabled="isBusy(source.id)" @click="removeSource(source)">取消订阅</el-button>
          </span>
        </div>
      </div>
    </section>

    <el-dialog v-model="subscriptionDialogOpen" title="新增订阅" width="min(620px, calc(100vw - 32px))" append-to-body class="rss-manager-subscribe-dialog" @closed="resetSubscriptionDialog">
      <form class="rss-subscribe-dialog-body" @submit.prevent="subscribe">
        <p class="rss-subscribe-dialog-note">输入 RSS 或 Atom 地址。首次会读取订阅源当前可用的条目，新增文章仅入库。</p>
        <label class="rss-subscribe-url-field">
          <span>订阅地址</span>
          <el-input v-model.trim="feedUrl" type="url" name="rss-feed-url" autocomplete="url" spellcheck="false" clearable placeholder="https://example.com/feed.xml" />
        </label>
        <div class="rss-subscribe-config-fields">
          <label>
            <span>自动检查</span>
            <el-select v-model="syncIntervalMinutes" name="rss-sync-interval" aria-label="RSS 自动检查频率">
              <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
          </label>
        </div>
        <label class="rss-subscribe-auto-analyze">
          <el-switch v-model="autoAnalyze" />
          <span>新增文章自动生成 AI 总结</span>
        </label>
        <div class="rss-subscribe-dialog-actions">
          <el-button @click="subscriptionDialogOpen = false">取消</el-button>
          <el-button type="primary" native-type="submit" :loading="subscribing">{{ subscribing ? '正在添加' : '添加订阅' }}</el-button>
        </div>
      </form>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import ReportGroupMultiSelect from '../../components/ReportGroupMultiSelect.vue'
import CollectionState from '../../components/CollectionState.vue'
import rssHubIcon from '../../../assets/rsshub.svg'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm'
import { enqueueSourceSyncTask, observeSourceSyncTask } from '../../utils/sourceSyncTask'

const props = defineProps({ reportGroups: { type: Array, default: () => [] } })
const emit = defineEmits(['library-changed'])
const API = 'http://127.0.0.1:8000/api/rss-sources'
const feedUrl = ref('')
const syncIntervalMinutes = ref(180)
const autoAnalyze = ref(false)
const notifyOnNew = ref(false)
const sources = ref([])
const loading = ref(false)
const subscribing = ref(false)
const checkingId = ref('')
const checkingAll = ref(false)
const savingId = ref('')
const subscriptionDialogOpen = ref(false)

const intervalOptions = [
  { value: 30, label: '每 30 分钟' }, { value: 60, label: '每小时' }, { value: 180, label: '每 3 小时' },
  { value: 360, label: '每 6 小时' }, { value: 720, label: '每 12 小时' }, { value: 1440, label: '每天' },
]
const enabledSourceCount = computed(() => sources.value.filter((source) => source.enabled).length)

function errorMessage(error, fallback) { return error?.response?.data?.detail || error?.message || fallback }
function intervalLabel(value) { return intervalOptions.find((option) => option.value === Number(value))?.label || `每 ${value} 分钟` }
function formatTime(value) {
  if (!value) return '尚未检查'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '尚未检查' : new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function sourceActivityLabel(source) {
  if (checkingId.value === source.id) return '正在检查'
  if (!source.enabled) return '已暂停'
  if (source.last_error) return '检查失败'
  if (!source.last_sync_at) return '尚未检查'
  return Number(source.last_created_count || 0) > 0 ? `新增 ${source.last_created_count} 篇` : '无新增'
}
function sourceActivityClass(source) {
  if (checkingId.value === source.id) return 'is-running'
  if (source.last_error) return 'is-error'
  if (Number(source.last_created_count || 0) > 0) return 'has-new'
  return 'is-muted'
}
function sourceActivityMeta(source) {
  if (source.last_error) return source.last_error
  if (!source.last_sync_at) return source.enabled ? '等待自动检查' : '自动检查已暂停'
  return `${formatTime(source.last_sync_at)} · 下次 ${formatTime(source.next_sync_at)}`
}
function isBusy(sourceId) { return checkingId.value === sourceId || savingId.value === sourceId || checkingAll.value }
function resetSubscriptionDialog() { feedUrl.value = ''; syncIntervalMinutes.value = 180; autoAnalyze.value = false; notifyOnNew.value = false }

async function loadSources() {
  loading.value = true
  try { const response = await axios.get(API, { timeout: 15000 }); sources.value = Array.isArray(response.data) ? response.data : [] }
  catch (error) { ElMessage.error(errorMessage(error, '无法读取 RSS 订阅')) }
  finally { loading.value = false }
}
async function subscribe() {
  if (!feedUrl.value) { ElMessage.warning('请先粘贴 RSS 或 Atom 地址'); return }
  subscribing.value = true
  try {
    const payload = { feed_url: feedUrl.value, sync_interval_minutes: syncIntervalMinutes.value, auto_analyze: autoAnalyze.value, notify_on_new: notifyOnNew.value }
    const task = await enqueueSourceSyncTask({ kind: 'rss_create', source_title: 'RSS 订阅', source_url: feedUrl.value, payload })
    ElMessage.success('已开始订阅并检查 RSS 源')
    subscriptionDialogOpen.value = false
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`RSS 检查完成：新增 ${result.created_count || 0} 篇文章`)
        await loadSources()
        emit('library-changed')
      },
      onFailed: (message) => ElMessage.error(message || 'RSS 订阅添加失败'),
    })
  } catch (error) { ElMessage.error(errorMessage(error, 'RSS 订阅添加失败')) }
  finally { subscribing.value = false }
}
async function checkSource(source) {
  checkingId.value = source.id
  try {
    const task = await enqueueSourceSyncTask({ kind: 'rss_saved', source_title: source.title || 'RSS 检查', source_url: source.feed_url, source_id: source.id })
    ElMessage.success('已开始检查 RSS 源')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`检查完成：新增 ${result.created_count || 0} 篇文章`)
        await loadSources(); emit('library-changed')
      },
      onFailed: (message) => ElMessage.error(message || 'RSS 检查失败'),
    })
  } catch (error) { ElMessage.error(errorMessage(error, 'RSS 检查失败')) }
  finally { checkingId.value = '' }
}
async function checkAll() {
  checkingAll.value = true
  try {
    const enabled = sources.value.filter((item) => item.enabled)
    for (const source of enabled) {
      const task = await enqueueSourceSyncTask({ kind: 'rss_saved', source_title: source.title || 'RSS 检查', source_url: source.feed_url, source_id: source.id })
      observeSourceSyncTask(task.task_id, {
        onSucceeded: async () => { await loadSources(); emit('library-changed') },
        onFailed: (message) => ElMessage.warning(message || `${source.title || 'RSS'} 检查失败`),
      })
    }
    ElMessage.success(`已开始检查 ${enabled.length} 个 RSS 订阅`)
  } catch (error) { ElMessage.error(errorMessage(error, '部分 RSS 订阅检查失败')); await loadSources() }
  finally { checkingAll.value = false }
}
async function updateSource(source, changes) {
  savingId.value = source.id
  try { await axios.patch(`${API}/${source.id}`, changes, { timeout: 15000 }); await loadSources() }
  catch (error) { ElMessage.error(errorMessage(error, 'RSS 订阅设置保存失败')) }
  finally { savingId.value = '' }
}
async function removeSource(source) {
  const confirmed = await requestDestructiveConfirmation({
    title: '取消订阅',
    message: `取消订阅“${source.title || '该 RSS 源'}”不会删除已经入库的文章。`,
    confirmLabel: '取消订阅',
  })
  if (!confirmed) return
  savingId.value = source.id
  try { await axios.delete(`${API}/${source.id}`, { timeout: 15000 }); await loadSources(); ElMessage.success('RSS 订阅已取消，已入库文章仍保留') }
  catch (error) { ElMessage.error(errorMessage(error, '取消 RSS 订阅失败')) }
  finally { savingId.value = '' }
}

onMounted(loadSources)
</script>

<style scoped src="../../styles/rssManager.css"></style>
