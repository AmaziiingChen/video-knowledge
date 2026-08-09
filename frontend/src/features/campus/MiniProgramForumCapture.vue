<template>
  <div class="forum-capture-card">
    <div class="forum-capture-head">
      <div>
        <h3>校园论坛视觉采集</h3>
        <p>自动遍历帖子详情和评论，只读取当前账号正常可见的界面。</p>
      </div>
      <span class="forum-state" :data-state="stateTone">{{ stateLabel }}</span>
    </div>

    <div class="forum-readiness">
      <div><span>微信窗口</span><strong>{{ windowLabel }}</strong></div>
      <div><span>辅助功能</span><strong>{{ environment.accessibility_granted ? '已允许' : '待允许' }}</strong></div>
      <div><span>屏幕录制</span><strong>{{ environment.screen_capture_granted ? '已允许' : '待允许' }}</strong></div>
    </div>

    <div v-if="run" class="forum-progress">
      <div class="forum-progress-copy">
        <strong>{{ stageLabel }}</strong>
        <span>已查看 {{ run.posts_seen || 0 }} 篇 · 新增 {{ run.posts_created || 0 }} 篇 · 评论 {{ run.comments_captured || 0 }} 条 · 截图 {{ run.frames_captured || 0 }} 张</span>
        <span v-if="run.content_item_id">本轮文档已同步至资源管理器 / 微信小程序</span>
      </div>
      <el-progress :percentage="progressHint" :show-text="false" :indeterminate="active && !run.posts_seen" />
      <p v-if="run.last_error" class="forum-error">{{ run.last_error }}</p>
    </div>

    <section class="forum-run-settings" aria-label="本次采集设置">
      <div class="forum-run-settings-copy">
        <strong>本次采集</strong>
        <span>选择采集范围后开始；已入库内容会自动跳过。</span>
      </div>
      <div class="forum-run-settings-controls">
        <label class="forum-field">
          <span>采集方式</span>
          <el-select v-model="form.mode" aria-label="采集模式" :disabled="active">
            <el-option label="增量采集" value="incremental" />
            <el-option label="首次回溯" value="backfill" />
          </el-select>
        </label>
        <label class="forum-field forum-field--number">
          <span>文章上限</span>
          <div class="forum-number-control">
            <el-input-number v-model="form.max_posts" :min="1" :max="5000" controls-position="right" aria-label="本次最多采集帖子数" :disabled="active" />
            <em>篇</em>
          </div>
        </label>
      </div>
    </section>

    <div class="forum-auto-row">
      <div>
        <strong>空闲时自动增量采集</strong>
        <span>{{ autoSummary }}</span>
      </div>
      <label class="forum-field forum-field--interval">
        <span class="sr-only">自动采集频率</span>
        <el-select v-model="captureSettings.interval_minutes" :disabled="!captureSettings.enabled" aria-label="自动采集频率" @change="saveSettings({ interval_minutes: $event })">
          <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </label>
      <el-switch v-model="captureSettings.enabled" aria-label="启用空闲自动采集" @change="saveSettings({ enabled: $event })" />
    </div>

    <div class="forum-actions">
      <el-button size="small" :loading="permissionLoading" :disabled="active" @click="requestPermissions">检查权限</el-button>
      <el-button v-if="!active" type="primary" size="small" :loading="starting" @click="startCapture">开始采集</el-button>
      <el-button v-else-if="run?.status === 'paused'" type="primary" size="small" @click="resumeCapture">继续</el-button>
      <el-button v-else size="small" @click="pauseCapture">暂停</el-button>
      <el-button v-if="active" type="danger" plain size="small" @click="stopCapture">停止</el-button>
    </div>

    <p class="forum-note">
      开始前请在微信中打开“猹话会”的帖子列表并切到“最新”。首次运行会请求系统权限；采集期间请暂时不要操作微信，登录过期或验证码仍需人工处理。
    </p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE } from '../../utils/localApiAuth.js'

const emit = defineEmits(['library-changed'])
const API = `${API_BASE}/miniprogram-forum`
const status = ref({ active: false, run: null, environment: {} })
const starting = ref(false)
const permissionLoading = ref(false)
const form = reactive({ mode: 'incremental', max_posts: 300 })
const captureSettings = reactive({ enabled: false, interval_minutes: 360, idle_seconds_required: 120, last_attempt_at: '', last_status: '', last_message: '' })
const intervalOptions = [
  { value: 30, label: '每 30 分钟' }, { value: 60, label: '每小时' },
  { value: 180, label: '每 3 小时' }, { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' }, { value: 1440, label: '每天' },
]
let pollTimer = null
const announcedContentIds = new Set()

function announceRunDocument(run) {
  const contentItemId = String(run?.content_item_id || '')
  if (!contentItemId || announcedContentIds.has(contentItemId)) return
  announcedContentIds.add(contentItemId)
  emit('library-changed', { content_item_id: contentItemId })
}

const run = computed(() => status.value.run || null)
const active = computed(() => Boolean(status.value.active))
const environment = computed(() => status.value.environment || {})
const windowLabel = computed(() => {
  const selected = environment.value.selected_window
  if (selected) return selected.title || selected.owner || '已找到'
  return environment.value.available ? '未找到' : '不可用'
})
const stateTone = computed(() => {
  if (active.value && run.value?.status === 'paused') return 'paused'
  if (active.value) return 'running'
  if (run.value?.status === 'failed') return 'failed'
  if (run.value?.status === 'succeeded') return 'success'
  return 'idle'
})
const stateLabel = computed(() => ({
  running: '采集中', paused: '已暂停', failed: '需要处理', success: '已完成', idle: '待启动',
})[stateTone.value])
const stageLabel = computed(() => ({
  preparing: '正在准备', checking_permissions: '检查系统权限', scanning_feed: '识别帖子列表',
  opening_post: '打开帖子详情', returned_to_feed: '继续扫描列表', paused: '采集已暂停',
  resuming: '正在恢复', stopping: '正在停止', stopped: '已停止', succeeded: '本轮采集完成',
  failed: '采集异常', interrupted: '上次采集中断',
})[run.value?.current_stage] || run.value?.current_stage || '尚未采集')
const progressHint = computed(() => {
  const maximum = Number(run.value?.options?.max_posts || form.max_posts || 1)
  return Math.min(99, Math.round(Number(run.value?.posts_seen || 0) / maximum * 100))
})
const autoSummary = computed(() => {
  if (!captureSettings.enabled) return '关闭；手动开始不受影响'
  if (captureSettings.last_message) return captureSettings.last_message
  return `电脑空闲 ${captureSettings.idle_seconds_required || 120} 秒后运行，不抢占正在使用的微信`
})

async function loadStatus({ silent = false } = {}) {
  try {
    const response = await axios.get(`${API}/status`, { timeout: 15000 })
    status.value = response.data || status.value
    announceRunDocument(status.value.run)
  } catch (error) {
    if (!silent) ElMessage.error(error?.response?.data?.detail || '无法读取小程序采集状态')
  }
}

async function requestPermissions() {
  permissionLoading.value = true
  try {
    const response = await axios.post(`${API}/permissions`, { window_pattern: '猹话会', prompt: true }, { timeout: 45000 })
    status.value.environment = response.data || {}
    if (response.data?.accessibility_granted && response.data?.screen_capture_granted) {
      ElMessage.success('采集权限已就绪')
    } else {
      ElMessage.warning('请在系统设置的“隐私与安全性”中允许辅助功能和屏幕录制')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '系统权限检查失败')
  } finally {
    permissionLoading.value = false
  }
}

async function loadSettings() {
  try {
    const response = await axios.get(`${API}/settings`, { timeout: 10000 })
    Object.assign(captureSettings, response.data || {})
    if (response.data?.max_posts) form.max_posts = response.data.max_posts
  } catch { /* Status polling will surface backend availability. */ }
}

async function saveSettings(payload) {
  const previous = { ...captureSettings }
  Object.assign(captureSettings, payload)
  try {
    const response = await axios.patch(`${API}/settings`, payload, { timeout: 10000 })
    Object.assign(captureSettings, response.data || {})
    ElMessage.success(captureSettings.enabled ? '空闲自动采集已保存' : '自动采集已关闭')
  } catch (error) {
    Object.assign(captureSettings, previous)
    ElMessage.error(error?.response?.data?.detail || '自动采集设置保存失败')
  }
}

async function startCapture() {
  starting.value = true
  try {
    const response = await axios.post(`${API}/start`, {
      source_key: 'campus_forum',
      mode: form.mode,
      window_pattern: '猹话会',
      max_posts: form.max_posts,
      max_feed_scrolls: 500,
      max_detail_scrolls: 120,
      known_post_stop: 20,
      page_wait_seconds: 1.2,
      prompt_permissions: true,
    }, { timeout: 15000 })
    announceRunDocument(response.data)
    ElMessage.success('采集任务已启动，请暂时不要操作微信')
    await loadStatus({ silent: true })
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '小程序采集启动失败')
  } finally {
    starting.value = false
  }
}

async function pauseCapture() {
  try { await axios.post(`${API}/pause`); await loadStatus({ silent: true }) } catch (error) { ElMessage.error(error?.response?.data?.detail || '暂停失败') }
}
async function resumeCapture() {
  try { await axios.post(`${API}/resume`); await loadStatus({ silent: true }) } catch (error) { ElMessage.error(error?.response?.data?.detail || '继续失败') }
}
async function stopCapture() {
  try { await axios.post(`${API}/stop`); await loadStatus({ silent: true }) } catch (error) { ElMessage.error(error?.response?.data?.detail || '停止失败') }
}

function schedulePoll() {
  window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(async () => {
    await loadStatus({ silent: true })
    schedulePoll()
  }, active.value ? 2500 : 10000)
}

onMounted(async () => { await Promise.all([loadStatus({ silent: true }), loadSettings()]); schedulePoll() })
onBeforeUnmount(() => window.clearTimeout(pollTimer))
</script>

<style scoped>
.forum-capture-card {
  display: grid;
  gap: var(--vk-space-panel);
  min-height: 100%;
  padding: 20px;
  align-content: start;
}
.forum-capture-head,
.forum-actions { display: flex; align-items: center; gap: var(--vk-space-control); }
.forum-capture-head { justify-content: space-between; gap: var(--vk-space-panel); }
.forum-capture-head h3 { margin: 0 0 var(--vk-space-xs); color: var(--vk-text); font-size: var(--vk-type-reading-size); font-weight: 680; }
.forum-capture-head p,
.forum-note,
.forum-progress p { margin: 0; color: var(--vk-muted); font-size: var(--vk-type-meta-size); line-height: 1.6; }
.forum-state {
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-xs);
  flex: none;
  padding: 4px 9px;
  border-radius: var(--vk-radius-pill);
  background: var(--vk-bg-hover);
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}
.forum-state::before { width: 6px; height: 6px; border-radius: var(--vk-radius-pill); background: currentColor; content: ''; }
.forum-state[data-state="running"],
.forum-state[data-state="success"] { background: color-mix(in srgb, var(--vk-accent) 9%, transparent); color: var(--vk-accent-strong); }
.forum-state[data-state="paused"] { background: color-mix(in srgb, var(--vk-warning) 10%, transparent); color: var(--vk-warning); }
.forum-state[data-state="failed"] { background: color-mix(in srgb, var(--vk-danger) 9%, transparent); color: var(--vk-danger); }
.forum-readiness {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-block: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
}
.forum-readiness div { min-width: 0; padding: var(--vk-space-cluster) var(--vk-space-panel); }
.forum-readiness div + div { border-left: 1px solid color-mix(in srgb, var(--vk-border) 58%, transparent); }
.forum-readiness span, .forum-readiness strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.forum-readiness span { margin-bottom: var(--vk-space-xs); color: var(--vk-muted); font-size: var(--vk-type-meta-size); }
.forum-readiness strong { color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: 650; }
.forum-progress { padding: var(--vk-space-cluster); border: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent); border-radius: var(--vk-radius-input); background: color-mix(in srgb, var(--vk-bg-hover) 38%, transparent); }
.forum-progress-copy { display: flex; justify-content: space-between; gap: var(--vk-space-cluster); margin-bottom: var(--vk-space-control); font-size: var(--vk-type-meta-size); }
.forum-progress-copy strong { color: var(--vk-text); }
.forum-progress-copy span { color: var(--vk-muted); text-align: right; }
.forum-progress .forum-error { margin-top: var(--vk-space-control); color: var(--vk-danger); }
.forum-progress :deep(.el-progress-bar__outer) { background: color-mix(in srgb, var(--vk-border) 46%, transparent); }
.forum-progress :deep(.el-progress-bar__inner) { background: var(--vk-accent); }
.forum-run-settings {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-panel);
  padding: 13px 14px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 74%, transparent);
  border-radius: var(--vk-radius-input);
  background: color-mix(in srgb, var(--vk-bg-hover) 28%, var(--vk-bg-panel));
}
.forum-run-settings-copy { display: grid; min-width: 0; gap: 3px; }
.forum-run-settings-copy strong { color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: 650; }
.forum-run-settings-copy span { overflow: hidden; color: var(--vk-muted); font-size: var(--vk-type-meta-size); text-overflow: ellipsis; white-space: nowrap; }
.forum-run-settings-controls { display: flex; align-items: end; gap: var(--vk-space-control); flex: 0 0 auto; }
.forum-field { display: grid; gap: 5px; color: var(--vk-muted); font-size: var(--vk-type-meta-size); font-weight: 500; }
.forum-field :deep(.el-select) { width: 142px; }
.forum-field :deep(.el-select__wrapper),
.forum-number-control :deep(.el-input__wrapper) {
  min-height: 36px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--vk-bg-panel) 92%, var(--vk-bg-center));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--vk-border) 84%, transparent) inset;
  transition: box-shadow var(--vk-motion-fast) var(--vk-ease-out), background-color var(--vk-motion-fast) var(--vk-ease-out);
}
.forum-field :deep(.el-select__wrapper:hover),
.forum-number-control:hover :deep(.el-input__wrapper) { background: var(--vk-bg-panel); box-shadow: 0 0 0 1px color-mix(in srgb, var(--vk-text) 16%, var(--vk-border)) inset; }
.forum-number-control { position: relative; display: flex; align-items: center; }
.forum-number-control :deep(.el-input-number) { width: 132px; }
.forum-number-control :deep(.el-input__inner) { padding-right: 43px; color: var(--vk-text); font-variant-numeric: tabular-nums; text-align: left; }
.forum-number-control :deep(.el-input-number__increase),
.forum-number-control :deep(.el-input-number__decrease) {
  right: 1px;
  width: 30px;
  height: 17px;
  border-left: 1px solid color-mix(in srgb, var(--vk-border) 74%, transparent);
  background: color-mix(in srgb, var(--vk-bg-hover) 60%, transparent);
  color: var(--vk-muted);
  line-height: 17px;
  transition: background-color var(--vk-motion-fast) var(--vk-ease-out), color var(--vk-motion-fast) var(--vk-ease-out);
}
.forum-number-control :deep(.el-input-number__increase) { top: 1px; border-radius: var(--vk-radius-control); }
.forum-number-control :deep(.el-input-number__decrease) { bottom: 1px; border-top: 1px solid color-mix(in srgb, var(--vk-border) 62%, transparent); border-radius: var(--vk-radius-control); }
.forum-number-control :deep(.el-input-number__increase:hover),
.forum-number-control :deep(.el-input-number__decrease:hover) { background: color-mix(in srgb, var(--vk-accent) 10%, var(--vk-bg-panel)); color: var(--vk-accent-strong); }
.forum-number-control em { position: absolute; right: 38px; color: var(--vk-muted); font-size: var(--vk-type-micro-size); font-style: normal; pointer-events: none; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.forum-auto-row {
  display: flex;
  align-items: center;
  gap: var(--vk-space-cluster);
  padding: var(--vk-space-cluster);
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-radius: var(--vk-radius-input);
  background: color-mix(in srgb, var(--vk-bg-hover) 32%, transparent);
}
.forum-auto-row > div { min-width: 0; flex: 1; }
.forum-auto-row strong, .forum-auto-row span { display: block; }
.forum-auto-row strong { margin-bottom: 3px; color: var(--vk-text); font-size: var(--vk-type-label-size); font-weight: 650; }
.forum-auto-row span { overflow: hidden; color: var(--vk-muted); font-size: var(--vk-type-meta-size); text-overflow: ellipsis; white-space: nowrap; }
.forum-field--interval { flex: 0 0 auto; }
.forum-field--interval :deep(.el-select) { width: 126px; }
.forum-actions :deep(.el-button) { min-height: 32px; border-radius: var(--vk-radius-control); }
.forum-note { max-width: 780px; text-wrap: pretty; }

@media (max-width: 900px) {
  .forum-readiness { grid-template-columns: 1fr; }
  .forum-readiness div + div { border-top: 1px solid color-mix(in srgb, var(--vk-border) 58%, transparent); border-left: 0; }
  .forum-progress-copy { display: grid; }
  .forum-progress-copy span { text-align: left; }
  .forum-run-settings { align-items: flex-start; flex-direction: column; }
  .forum-run-settings-controls { align-self: stretch; }
}

@media (max-width: 640px) {
  .forum-capture-card { padding: var(--vk-space-panel); }
  .forum-capture-head,
  .forum-auto-row { align-items: flex-start; flex-direction: column; }
  .forum-run-settings-controls { width: 100%; align-items: stretch; flex-direction: column; }
  .forum-field :deep(.el-select),
  .forum-field--interval :deep(.el-select),
  .forum-number-control,
  .forum-number-control :deep(.el-input-number) { width: 100%; }
  .forum-auto-row .forum-field { width: 100%; }
  .forum-actions { align-items: flex-start; flex-wrap: wrap; }
}
</style>
