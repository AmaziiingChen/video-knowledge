<template>
  <el-dialog
    :model-value="modelValue"
    title="公开发现与批量采集"
    width="min(860px, calc(100vw - 32px))"
    append-to-body
    class="wechat-public-discovery-dialog"
    @closed="closeDialog"
    @opened="handleOpened"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="wechat-public-discovery">
      <section class="wechat-public-discovery-intro">
        <strong>不依赖公众号后台授权</strong>
        <p>可直接导入文章/合集，也可用一篇种子文章发现同公众号候选。公开搜索候选经你确认后才会进入正文、OCR 和总结管线。</p>
      </section>

      <section class="wechat-public-discovery-compose">
        <div class="wechat-public-discovery-strategy" role="radiogroup" aria-label="公众号发现方式">
          <button
            type="button"
            role="radio"
            :aria-checked="discoveryStrategy === 'direct'"
            :class="{ 'is-active': discoveryStrategy === 'direct' }"
            @click="discoveryStrategy = 'direct'"
          >
            直接导入
          </button>
          <button
            type="button"
            role="radio"
            :aria-checked="discoveryStrategy === 'seed'"
            :class="{ 'is-active': discoveryStrategy === 'seed' }"
            @click="discoveryStrategy = 'seed'"
          >
            种子扩展
          </button>
        </div>
        <label for="wechat-public-discovery-input">文章或合集链接</label>
        <el-input
          id="wechat-public-discovery-input"
          ref="inputRef"
          v-model="inputText"
          type="textarea"
          name="wechat-public-discovery-input"
          :rows="4"
          resize="vertical"
          :placeholder="discoveryStrategy === 'seed'
            ? '粘贴一篇该公众号的公开文章链接'
            : '每行粘贴一篇公众号文章链接，或单独粘贴一个公众号合集链接'"
          aria-describedby="wechat-public-discovery-hint"
        />
        <div class="wechat-public-discovery-compose-meta">
          <span id="wechat-public-discovery-hint">{{ inputHint }}</span>
          <el-switch
            v-model="autoAnalyze"
            inline-prompt
            active-text="总结"
            inactive-text="仅入库"
            aria-label="导入后自动生成总结"
          />
        </div>
        <div v-if="isAlbumInput" class="wechat-public-discovery-subscribe-option">
          <div>
            <strong>持续检测这个合集</strong>
            <small>首次导入后按计划检查新增文章，只处理尚未入库的内容。</small>
          </div>
          <el-select
            v-model="albumSyncInterval"
            size="small"
            :disabled="!subscribeAlbum"
            aria-label="合集自动检测频率"
          >
            <el-option label="每 6 小时" :value="360" />
            <el-option label="每 12 小时" :value="720" />
            <el-option label="每天" :value="1440" />
          </el-select>
          <el-switch
            v-model="subscribeAlbum"
            aria-label="持续检测这个合集"
          />
        </div>
        <div v-if="submitError" class="wechat-public-discovery-error" role="alert">{{ submitError }}</div>
        <div class="wechat-public-discovery-actions">
          <small>{{ discoveryStrategy === 'seed' ? '候选将严格匹配公众号身份，并等待你勾选确认。' : '公开合集不能保证覆盖公众号全部历史文章。' }}</small>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!inputText.trim()"
            @click="startDiscovery"
          >
            {{ discoveryStrategy === 'seed' ? '开始发现候选' : '开始校验并导入' }}
          </el-button>
        </div>
      </section>

      <section class="wechat-public-discovery-subscriptions">
        <header>
          <div>
            <strong>合集订阅</strong>
            <span>低频检查公开合集，只导入新增文章</span>
          </div>
          <el-button text size="small" :loading="loadingAlbumSources" @click="loadAlbumSources">刷新</el-button>
        </header>

        <div v-if="loadingAlbumSources && !albumSources.length" class="wechat-public-discovery-empty">正在读取合集订阅…</div>
        <div v-else-if="!albumSources.length" class="wechat-public-discovery-empty">导入一个合集后，可以在这里开启持续检测。</div>
        <div v-else class="wechat-public-discovery-source-list">
          <article v-for="source in albumSources" :key="source.id">
            <div class="wechat-public-discovery-source-copy">
              <strong>{{ source.title || '公众号合集' }}</strong>
              <small>{{ albumSourceScheduleText(source) }}</small>
            </div>
            <div class="wechat-public-discovery-source-controls">
              <el-switch
                :model-value="source.auto_analyze"
                inline-prompt
                active-text="总结"
                inactive-text="入库"
                :disabled="isSourceUpdating(source.id)"
                :aria-label="`${source.title || '公众号合集'}新增文章处理方式`"
                @update:model-value="updateAlbumSource(source, { auto_analyze: $event })"
              />
              <el-select
                :model-value="source.sync_interval_minutes"
                size="small"
                :disabled="isSourceUpdating(source.id)"
                :aria-label="`${source.title || '公众号合集'}检查频率`"
                @update:model-value="updateAlbumSource(source, { sync_interval_minutes: $event })"
              >
                <el-option label="6 小时" :value="360" />
                <el-option label="12 小时" :value="720" />
                <el-option label="每天" :value="1440" />
              </el-select>
              <el-switch
                :model-value="source.enabled"
                :disabled="isSourceUpdating(source.id)"
                :aria-label="`${source.enabled ? '暂停' : '开启'}${source.title || '公众号合集'}自动检测`"
                @update:model-value="updateAlbumSource(source, { enabled: $event })"
              />
              <el-button
                size="small"
                :loading="syncingSourceIds.has(source.id)"
                :disabled="isSourceUpdating(source.id)"
                @click="syncAlbumSource(source)"
              >
                立即检查
              </el-button>
            </div>
          </article>
        </div>
      </section>

      <section class="wechat-public-discovery-history">
        <header>
          <div>
            <strong>最近导入</strong>
            <span>任务持久化保存，关闭窗口后仍会继续</span>
          </div>
          <el-button text size="small" :loading="loadingRuns" @click="loadRuns">刷新</el-button>
        </header>

        <div v-if="loadingRuns && !runs.length" class="wechat-public-discovery-empty">正在读取导入记录…</div>
        <div v-else-if="!runs.length" class="wechat-public-discovery-empty">还没有公开导入记录。</div>
        <div v-else class="wechat-public-discovery-run-list">
          <article
            v-for="run in runs"
            :key="run.id"
            class="wechat-public-discovery-run"
            :class="{ 'is-selected': selectedRunId === run.id }"
          >
            <button type="button" class="wechat-public-discovery-run-main" @click="selectRun(run)">
              <span class="wechat-public-discovery-run-copy">
                <strong>{{ run.discovery_strategy === 'seed' ? (run.source_title || '公众号种子扩展') : (run.mode === 'album' ? '公众号合集' : '批量文章') }}</strong>
                <small>{{ formatTime(run.created_at) }} · {{ run.coverage_label }}</small>
              </span>
              <span class="wechat-public-discovery-run-counts">{{ discoveryRunSummary(run) }}</span>
              <span class="wechat-public-discovery-run-status" :class="`is-${run.review_required ? 'review' : run.status}`">
                {{ discoveryRunDisplayStatus(run) }}
              </span>
            </button>
            <el-button
              v-if="(
                ['queued', 'running'].includes(run.status)
                || ['queued', 'running'].includes(run.review_import_status)
              ) && run.task_id"
              text
              size="small"
              @click="cancelRun(run)"
            >
              取消
            </el-button>
            <p v-if="run.error_message" class="wechat-public-discovery-run-error">{{ run.error_message }}</p>
          </article>
        </div>
      </section>

      <section v-if="selectedRunId" class="wechat-public-discovery-candidates">
        <header>
          <div>
            <strong>文章明细</strong>
            <span>{{ candidates.length }} 条</span>
          </div>
          <div v-if="reviewableCandidates.length" class="wechat-public-discovery-review-actions">
            <label class="wechat-public-discovery-check">
              <input
                type="checkbox"
                :checked="allReviewableSelected"
                :indeterminate="someReviewableSelected"
                @change="toggleSelectAll($event.target.checked)"
              >
              全选待确认
            </label>
            <el-button
              type="primary"
              size="small"
              :loading="importingSelection"
              :disabled="!selectedCandidateIds.length"
              @click="importSelected"
            >
              导入选中 {{ selectedCandidateIds.length }} 篇
            </el-button>
          </div>
        </header>
        <p v-if="selectedRun?.cursor?.search_providers" class="wechat-public-discovery-provider-state">
          {{ providerStateText(selectedRun.cursor.search_providers) }}
        </p>
        <div v-if="loadingCandidates" class="wechat-public-discovery-empty">正在读取文章明细…</div>
        <div v-else class="wechat-public-discovery-candidate-list">
          <article v-for="candidate in candidates" :key="candidate.id">
            <label
              v-if="isReviewable(candidate)"
              class="wechat-public-discovery-check wechat-public-discovery-candidate-check"
            >
              <input
                type="checkbox"
                :checked="selectedCandidateIds.includes(candidate.id)"
                :aria-label="`选择${candidate.observed_title || '候选文章'}`"
                @change="toggleCandidate(candidate.id, $event.target.checked)"
              >
            </label>
            <span v-else class="wechat-public-discovery-candidate-spacer" aria-hidden="true"></span>
            <div>
              <strong>{{ candidate.observed_title || '等待读取标题' }}</strong>
              <small :title="candidate.normalized_url">
                {{ candidate.search_provider ? `${providerLabel(candidate.search_provider)} · ` : '' }}{{ candidate.normalized_url }}
              </small>
            </div>
            <span :class="`is-${candidate.import_state}`">{{ candidateStateLabel(candidate) }}</span>
            <p v-if="candidate.error_message">{{ candidate.error_message }}</p>
          </article>
        </div>
      </section>
    </div>
  </el-dialog>
</template>

<script setup>
import axios from 'axios'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  albumSourceScheduleText,
  discoveryInputHint,
  discoveryRunDisplayStatus,
  discoveryRunSummary,
  isWechatAlbumInput
} from './wechatPublicDiscovery'


const props = defineProps({
  modelValue: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'library-changed'])
const API = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api'
const inputRef = ref(null)
const inputText = ref('')
const discoveryStrategy = ref('direct')
const autoAnalyze = ref(false)
const subscribeAlbum = ref(false)
const albumSyncInterval = ref(720)
const submitting = ref(false)
const submitError = ref('')
const loadingRuns = ref(false)
const loadingCandidates = ref(false)
const runs = ref([])
const selectedRunId = ref('')
const candidates = ref([])
const selectedCandidateIds = ref([])
const importingSelection = ref(false)
const loadingAlbumSources = ref(false)
const albumSources = ref([])
const updatingSourceIds = ref(new Set())
const syncingSourceIds = ref(new Set())
const completedRunIds = new Set()
let pollTimer = null

const inputHint = computed(() => discoveryInputHint(inputText.value, discoveryStrategy.value))
const isAlbumInput = computed(() => (
  discoveryStrategy.value === 'direct' && isWechatAlbumInput(inputText.value)
))
const selectedRun = computed(() => runs.value.find((run) => run.id === selectedRunId.value))
const reviewableCandidates = computed(() => candidates.value.filter(isReviewable))
const allReviewableSelected = computed(() => (
  reviewableCandidates.value.length > 0
  && reviewableCandidates.value.every((candidate) => selectedCandidateIds.value.includes(candidate.id))
))
const someReviewableSelected = computed(() => (
  selectedCandidateIds.value.length > 0 && !allReviewableSelected.value
))

watch(() => props.modelValue, (visible) => {
  if (visible) {
    loadRuns()
    loadAlbumSources()
    startPolling()
  } else {
    stopPolling()
  }
})

onBeforeUnmount(stopPolling)

async function handleOpened() {
  await nextTick()
  inputRef.value?.focus?.()
}

function closeDialog() {
  stopPolling()
  emit('update:modelValue', false)
}

async function startDiscovery() {
  if (!inputText.value.trim() || submitting.value) return
  submitting.value = true
  submitError.value = ''
  try {
    const response = await axios.post(`${API}/wechat-discovery/runs`, {
      input_text: inputText.value,
      auto_analyze: autoAnalyze.value,
      strategy: discoveryStrategy.value,
      subscribe_album: isAlbumInput.value && subscribeAlbum.value,
      sync_interval_minutes: albumSyncInterval.value
    }, { timeout: 15000 })
    const run = response.data?.run
    if (run) {
      runs.value = [run, ...runs.value.filter((item) => item.id !== run.id)]
      selectedRunId.value = run.id
      candidates.value = []
      selectedCandidateIds.value = []
    }
    inputText.value = ''
    subscribeAlbum.value = false
    ElMessage.success(discoveryStrategy.value === 'seed' ? '公众号候选发现任务已创建' : '公众号导入任务已创建')
    await loadAlbumSources()
    startPolling()
  } catch (error) {
    submitError.value = errorMessage(error, '公众号导入任务创建失败')
  } finally {
    submitting.value = false
  }
}

async function loadAlbumSources() {
  if (loadingAlbumSources.value) return
  loadingAlbumSources.value = true
  try {
    const response = await axios.get(`${API}/wechat-discovery/sources`, { timeout: 10000 })
    albumSources.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    if (!albumSources.value.length) submitError.value = errorMessage(error, '合集订阅读取失败')
  } finally {
    loadingAlbumSources.value = false
  }
}

function isSourceUpdating(sourceId) {
  return updatingSourceIds.value.has(sourceId)
}

async function updateAlbumSource(source, changes) {
  if (!source?.id || isSourceUpdating(source.id)) return
  updatingSourceIds.value = new Set([...updatingSourceIds.value, source.id])
  try {
    const response = await axios.patch(
      `${API}/wechat-discovery/sources/${encodeURIComponent(source.id)}`,
      changes,
      { timeout: 10000 }
    )
    albumSources.value = albumSources.value.map((item) => (
      item.id === source.id ? response.data : item
    ))
    ElMessage.success('合集自动检测设置已更新')
  } catch (error) {
    ElMessage.error(errorMessage(error, '合集设置更新失败'))
    await loadAlbumSources()
  } finally {
    const next = new Set(updatingSourceIds.value)
    next.delete(source.id)
    updatingSourceIds.value = next
  }
}

async function syncAlbumSource(source) {
  if (!source?.id || syncingSourceIds.value.has(source.id)) return
  syncingSourceIds.value = new Set([...syncingSourceIds.value, source.id])
  try {
    const response = await axios.post(
      `${API}/wechat-discovery/sources/${encodeURIComponent(source.id)}/sync`,
      {},
      { timeout: 15000 }
    )
    const run = response.data?.run
    if (run) {
      runs.value = [run, ...runs.value.filter((item) => item.id !== run.id)]
      selectedRunId.value = run.id
    }
    ElMessage.success('合集检查任务已创建')
    startPolling()
    await loadAlbumSources()
  } catch (error) {
    ElMessage.error(errorMessage(error, '合集检查任务创建失败'))
  } finally {
    const next = new Set(syncingSourceIds.value)
    next.delete(source.id)
    syncingSourceIds.value = next
  }
}

async function loadRuns() {
  if (loadingRuns.value) return
  loadingRuns.value = true
  try {
    let completedAny = false
    const previous = new Map(runs.value.map((run) => [
      run.id,
      `${run.status}:${run.review_import_status || ''}`
    ]))
    const response = await axios.get(`${API}/wechat-discovery/runs`, {
      params: { limit: 30 },
      timeout: 10000
    })
    runs.value = Array.isArray(response.data) ? response.data : []
    for (const run of runs.value) {
      const previousStatus = previous.get(run.id)
      const wasActive = previousStatus?.includes('queued') || previousStatus?.includes('running')
      const currentActive = ['queued', 'running'].includes(run.status)
        || ['queued', 'running'].includes(run.review_import_status)
      const completionKey = `${run.id}:${run.review_import_status ? 'review' : 'discovery'}`
      if (
        (wasActive || previousStatus === undefined)
        && !currentActive
        && !completedRunIds.has(completionKey)
      ) {
        completedRunIds.add(completionKey)
        completedAny = true
        emit('library-changed')
      }
    }
    if (completedAny) await loadAlbumSources()
    if (selectedRunId.value) await loadCandidates(selectedRunId.value)
    if (!runs.value.some((run) => (
      ['queued', 'running'].includes(run.status)
      || ['queued', 'running'].includes(run.review_import_status)
    ))) stopPolling()
  } catch (error) {
    if (!runs.value.length) submitError.value = errorMessage(error, '公众号导入记录读取失败')
  } finally {
    loadingRuns.value = false
  }
}

async function selectRun(run) {
  selectedRunId.value = selectedRunId.value === run.id ? '' : run.id
  candidates.value = []
  selectedCandidateIds.value = []
  if (selectedRunId.value) await loadCandidates(selectedRunId.value)
}

async function loadCandidates(runId) {
  if (!runId || loadingCandidates.value) return
  loadingCandidates.value = true
  try {
    const response = await axios.get(`${API}/wechat-discovery/runs/${encodeURIComponent(runId)}/candidates`, {
      params: { limit: 500 },
      timeout: 10000
    })
    if (selectedRunId.value === runId) {
      candidates.value = Array.isArray(response.data) ? response.data : []
      selectedCandidateIds.value = selectedCandidateIds.value.filter((id) => (
        candidates.value.some((candidate) => candidate.id === id && isReviewable(candidate))
      ))
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, '文章明细读取失败'))
  } finally {
    loadingCandidates.value = false
  }
}

function isReviewable(candidate) {
  return candidate?.verification_state === 'verified' && candidate?.import_state === 'pending'
}

function toggleCandidate(candidateId, checked) {
  if (checked) {
    selectedCandidateIds.value = [...new Set([...selectedCandidateIds.value, candidateId])]
  } else {
    selectedCandidateIds.value = selectedCandidateIds.value.filter((id) => id !== candidateId)
  }
}

function toggleSelectAll(checked) {
  selectedCandidateIds.value = checked
    ? reviewableCandidates.value.map((candidate) => candidate.id)
    : []
}

async function importSelected() {
  if (!selectedRunId.value || !selectedCandidateIds.value.length || importingSelection.value) return
  importingSelection.value = true
  try {
    const response = await axios.post(
      `${API}/wechat-discovery/runs/${encodeURIComponent(selectedRunId.value)}/import`,
      {
        candidate_ids: selectedCandidateIds.value,
        auto_analyze: autoAnalyze.value
      },
      { timeout: 15000 }
    )
    const run = response.data?.run
    if (run) runs.value = runs.value.map((item) => item.id === run.id ? run : item)
    ElMessage.success('已创建选中候选的导入任务')
    startPolling()
  } catch (error) {
    ElMessage.error(errorMessage(error, '候选文章导入失败'))
  } finally {
    importingSelection.value = false
  }
}

async function cancelRun(run) {
  try {
    await axios.post(
      `${API}/wechat-discovery/runs/${encodeURIComponent(run.id)}/cancel`,
      {},
      { timeout: 10000 }
    )
    ElMessage.success('已请求取消导入任务')
    await loadRuns()
  } catch (error) {
    ElMessage.error(errorMessage(error, '取消任务失败'))
  }
}

function startPolling() {
  if (pollTimer || !props.modelValue) return
  pollTimer = window.setInterval(loadRuns, 2000)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

function candidateStateLabel(candidate) {
  if (candidate.import_state === 'imported') return '已导入'
  if (candidate.import_state === 'duplicate') return '已存在'
  if (candidate.import_state === 'failed') return '失败'
  if (candidate.verification_state === 'verified') return '已校验'
  return '等待处理'
}

function providerLabel(provider) {
  return { sogou: '搜狗微信', bing: 'Bing', duckduckgo: 'DuckDuckGo' }[provider] || provider
}

function providerStateText(states) {
  const parts = Object.entries(states || {}).map(([provider, state]) => {
    if (state?.status === 'ok') return `${providerLabel(provider)} 找到 ${Number(state.result_count || 0)} 条`
    return `${providerLabel(provider)}：${state?.message || '暂时不可用'}`
  })
  return parts.join('；')
}

function formatTime(value) {
  const timestamp = Date.parse(value || '')
  if (!Number.isFinite(timestamp)) return '刚刚'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(timestamp)
}

function errorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}
</script>

<style scoped src="../../styles/wechatPublicDiscovery.css"></style>
