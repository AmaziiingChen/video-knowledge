<template>
  <section class="campus-manager manager-surface">
    <header class="campus-manager-head">
      <div class="campus-manager-title">
        <h2>网页管理</h2>
        <div class="campus-manager-title-meta">
          <span>{{ sources.length }} 个来源</span>
          <span>{{ enabledSourceCount }} 个自动检查</span>
        </div>
      </div>
      <div class="campus-manager-head-actions">
        <el-button
          v-if="activePanel === 'sources'"
          :loading="bulkSyncing"
          :disabled="!enabledSourceCount || campusSyncing"
          :title="bulkSyncProgressTitle"
          @click="emit('sync-all')"
        >{{ bulkSyncButtonLabel }}</el-button>
        <el-button
          v-if="canConnectCampus && !campusAccess.connected"
          type="primary"
          :loading="campusConnecting"
          @click="emit('connect-campus')"
        >{{ campusAccess.state === 'needs_gwt' ? '继续连接' : '连接 WebVPN' }}</el-button>
        <el-dropdown trigger="click" placement="bottom-end" @command="handleHeaderCommand">
          <button type="button" class="campus-manager-head-more" aria-label="更多网页管理操作">
            <el-icon><MoreFilled /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="refresh">刷新来源与访问状态</el-dropdown-item>
              <el-dropdown-item v-if="canConnectCampus && campusAccess.connected" command="connect">重新连接 WebVPN</el-dropdown-item>
              <el-dropdown-item v-if="campusAccess.connected || campusAccess.state === 'needs_gwt'" command="disconnect" divided>移除校园登录态</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="campus-manager-section-bar">
      <nav class="campus-manager-tabs" role="tablist" aria-label="网页管理功能">
        <button
          type="button"
          role="tab"
          :aria-selected="activePanel === 'sources'"
          :class="{ 'is-active': activePanel === 'sources' }"
          @click="activePanel = 'sources'"
        >来源检查</button>
        <button
          v-if="forumCaptureEnabled"
          type="button"
          role="tab"
          :aria-selected="activePanel === 'forum'"
          :class="{ 'is-active': activePanel === 'forum' }"
          @click="activePanel = 'forum'"
        >论坛采集</button>
      </nav>
      <span v-if="forumCaptureEnabled && activePanel === 'forum'" class="campus-manager-section-note">视觉采集期间请暂时不要操作微信</span>
    </div>

    <Transition name="campus-panel-swap" mode="out-in">
      <section v-if="activePanel === 'sources'" key="sources" class="campus-manager-panel campus-manager-source-panel" aria-label="校园来源检查">
        <CollectionState v-if="loadingSources && !sources.length" mode="loading" loading-label="正在读取校园来源" />
        <CollectionState
          v-else-if="!sources.length"
          title="还没有校园来源"
          description="从右上角菜单重新载入；如果仍为空，请检查后端服务状态。"
        />
        <div v-else class="campus-manager-table-scroll vk-scroll-area">
          <div class="campus-manager-table-head" role="row">
            <span class="column-source">来源</span><span class="column-group">分组</span><span class="column-activity">活动</span><span class="column-analysis">自动分析</span><span class="column-notification">通知</span><span class="column-enabled">自动检查</span><span class="column-frequency">检查频率</span><span class="column-actions">操作</span>
          </div>
          <div v-for="source in sources" :key="source.slug" class="campus-manager-table-row">
            <span class="campus-manager-source-cell column-source">
              <CampusSourceIcon :source-slug="source.slug" />
              <span class="campus-manager-source-copy">
                <strong>{{ source.name }}</strong>
                <small :title="source.base_url">{{ sourceHost(source) }}</small>
              </span>
            </span>
            <span class="campus-manager-inline-control column-group">
              <ReportGroupMultiSelect
                :model-value="source.group_ids || []"
                :groups="reportGroups"
                :aria-label="`${source.name} 的报告分组`"
                @update:model-value="emit('update-source', source, { group_ids: $event })"
              />
            </span>
            <span class="campus-manager-activity-cell column-activity">
              <strong :class="sourceActivityClass(source)">{{ sourceActivityLabel(source) }}</strong>
              <small :title="source.last_message">{{ sourceActivityMeta(source) }}</small>
            </span>
            <span class="campus-manager-source-setting-cell column-analysis">
              <el-switch :model-value="source.auto_analyze" :aria-label="`${source.auto_analyze ? '关闭' : '开启'} ${source.name} 的自动分析`" @update:model-value="emit('update-source', source, { auto_analyze: $event })" />
            </span>
            <span class="campus-manager-source-setting-cell column-notification">
              <el-switch :model-value="source.notify_on_new" :aria-label="`${source.notify_on_new ? '关闭' : '开启'} ${source.name} 的新文章通知`" @update:model-value="emit('update-source', source, { notify_on_new: $event })" />
            </span>
            <span class="campus-manager-source-setting-cell column-enabled">
              <el-switch :model-value="source.enabled" :aria-label="`${source.enabled ? '暂停' : '启用'} ${source.name} 的自动检查`" @update:model-value="emit('update-source', source, { enabled: $event })" />
            </span>
            <span class="campus-manager-source-setting-cell column-frequency">
              <el-select :model-value="source.interval_minutes" size="small" :aria-label="`${source.name} 的检查频率`" @update:model-value="updateInterval(source, $event)">
                <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </span>
            <span class="campus-manager-operation-cell column-actions">
              <el-button
                text
                size="small"
                :loading="isSourceSyncing(source)"
                :disabled="bulkSyncing || isSourceSyncing(source)"
                @click="emit('sync-source', source)"
              >{{ historyRunningSourceSlug === source.slug ? '回溯中' : (isSourceSyncing(source) ? '检查中' : '检查') }}</el-button>
              <el-button text size="small" :disabled="bulkSyncing || isSourceSyncing(source)" @click="openHistory(source)">回溯历史</el-button>
            </span>
          </div>
        </div>
      </section>

      <section v-else-if="forumCaptureEnabled" key="forum" class="campus-manager-panel campus-manager-forum-panel" aria-label="校园论坛视觉采集">
        <MiniProgramForumCapture @library-changed="emit('library-changed', $event)" />
      </section>
    </Transition>

    <HistorySyncDialog
      v-model="historyDialog.open"
      :source-label="historyDialog.sourceLabel"
      :max-items="300"
      @confirm="confirmHistorySync"
    />

  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { MoreFilled } from '../../components/macosSymbolComponents.js'
import MiniProgramForumCapture from './MiniProgramForumCapture.vue'
import HistorySyncDialog from '../../components/HistorySyncDialog.vue'
import ReportGroupMultiSelect from '../../components/ReportGroupMultiSelect.vue'
import CollectionState from '../../components/CollectionState.vue'
import CampusSourceIcon from './CampusSourceIcon.vue'

const props = defineProps({
  campusAccess: { type: Object, default: () => ({ state: 'disconnected', label: '尚未连接', detail: '', connected: false }) },
  campusConnecting: Boolean,
  campusSyncing: Boolean,
  bulkSyncing: Boolean,
  sources: { type: Array, default: () => [] },
  loadingSources: Boolean,
  syncingSource: { type: String, default: '' },
  syncingSources: { type: Array, default: () => [] },
  reportGroups: { type: Array, default: () => [] },
  forumCaptureEnabled: Boolean
})

const emit = defineEmits([
  'load-access',
  'connect-campus',
  'disconnect-campus',
  'refresh-sources',
  'sync-source',
  'sync-history',
  'sync-all',
  'update-source',
  'library-changed'
])

const activePanel = ref('sources')
const historyDialog = reactive({ open: false, source: null, sourceLabel: '' })
const historyRunningSourceSlug = ref('')
const intervalOptions = [
  { value: 30, label: '每 30 分钟' },
  { value: 60, label: '每小时' },
  { value: 180, label: '每 3 小时' },
  { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' },
  { value: 1440, label: '每天' }
]

const enabledSourceCount = computed(() => props.sources.filter((source) => source.enabled).length)
const syncingSourceSlugs = computed(() => new Set(props.syncingSources.map(String)))
const bulkSyncSourcePosition = computed(() => props.sources
  .filter((source) => source.enabled)
  .findIndex((source) => source.slug === props.syncingSource))
const bulkSyncButtonLabel = computed(() => {
  if (!props.bulkSyncing || bulkSyncSourcePosition.value < 0) return '检查全部'
  return `检查 ${bulkSyncSourcePosition.value + 1}/${enabledSourceCount.value}`
})
const bulkSyncProgressTitle = computed(() => {
  if (!props.bulkSyncing || bulkSyncSourcePosition.value < 0) return '依次检查全部已启用来源'
  const source = props.sources.find((item) => item.slug === props.syncingSource)
  return `正在检查：${source?.name || props.syncingSource}`
})
const canConnectCampus = computed(() => props.campusAccess.available !== false && props.campusAccess.state !== 'direct_only')

watch(() => props.syncingSource, (activeSourceSlug) => {
  if (historyRunningSourceSlug.value && activeSourceSlug !== historyRunningSourceSlug.value) {
    historyRunningSourceSlug.value = ''
  }
})

watch(() => props.forumCaptureEnabled, (enabled) => {
  if (!enabled && activePanel.value === 'forum') activePanel.value = 'sources'
}, { immediate: true })

function handleHeaderCommand(command) {
  if (command === 'refresh') {
    emit('load-access')
    emit('refresh-sources')
  }
  if (command === 'connect') emit('connect-campus')
  if (command === 'disconnect') emit('disconnect-campus')
}

function isSourceSyncing(source) {
  return syncingSourceSlugs.value.has(String(source?.slug || ''))
}

function sourceHost(source) {
  try {
    return new URL(source.base_url).hostname
  } catch {
    return source.base_url || '校园来源'
  }
}

function intervalLabel(value) {
  return intervalOptions.find((option) => String(option.value) === String(value))?.label || '未设置'
}

function updateInterval(source, value) {
  if (String(source.interval_minutes) === String(value)) return
  emit('update-source', source, { interval_minutes: value })
}

function openHistory(source) {
  historyDialog.source = source
  historyDialog.sourceLabel = source?.name || '当前校园来源'
  historyDialog.open = true
}

function confirmHistorySync(options) {
  const source = historyDialog.source
  historyDialog.open = false
  if (source) {
    historyRunningSourceSlug.value = source.slug
    emit('sync-history', source, options)
  }
}

function sourceActivityLabel(source) {
  if (source.last_status === 'error' || source.last_status === 'failed') return '检查失败'
  if (historyRunningSourceSlug.value === source.slug) return '正在回溯'
  if (!source.last_sync_at) return '尚未检查'
  return Number(source.last_created || 0) > 0 ? `新增 ${source.last_created} 篇` : '无新增'
}

function sourceActivityClass(source) {
  if (source.last_status === 'error' || source.last_status === 'failed') return 'is-error'
  if (historyRunningSourceSlug.value === source.slug) return 'is-running'
  if (Number(source.last_created || 0) > 0) return 'has-new'
  return 'is-muted'
}

function sourceActivityMeta(source) {
  if (!source.last_sync_at) return source.enabled ? '等待自动检查' : '自动检查已暂停'
  const timestamp = new Date(source.last_sync_at)
  const time = Number.isNaN(timestamp.getTime())
    ? '最近检查'
    : new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(timestamp)
  if (source.last_status === 'error' || source.last_status === 'failed') return source.last_message || time
  return `${time} · 发现 ${Number(source.last_discovered || 0)} 篇`
}
</script>

<style scoped src="../../styles/campusManager.css"></style>
