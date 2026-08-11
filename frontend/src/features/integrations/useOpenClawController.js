import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { API_BASE as API } from '../../utils/localApiAuth.js'

const OPENCLAW_STATUS_POLL_INTERVAL_MS = 5 * 60 * 1000

export function useOpenClawController({
  request = axios,
  notify = ElMessage,
  apiBase = API,
  scheduleInterval = (callback, delay) => window.setInterval(callback, delay),
  cancelInterval = (timer) => window.clearInterval(timer),
} = {}) {
  const openclawRunning = ref(false)
  const openclawScanning = ref(false)
  const openclawState = ref('unknown')
  const openclawStatus = ref('正在读取状态')
  const openclawBridge = ref({})
  const openclawTimer = ref(null)

  const openclawStatusText = computed(() => {
    if (openclawScanning.value) return '正在检查 OpenClaw Gateway…'
    if (openclawBridge.value.automation_ready) return '微信链接自动处理已就绪'
    if (openclawRunning.value) return openclawStatus.value || 'OpenClaw Gateway 已连接'
    if (openclawState.value === 'not_installed') return 'OpenClaw 服务未安装，点击安装并启动'
    if (openclawState.value === 'unavailable') return '未找到 OpenClaw CLI'
    return openclawStatus.value || 'OpenClaw 未运行，点击启动'
  })

  const openclawStatusTone = computed(() => {
    if (openclawBridge.value.automation_ready) return 'is-active'
    if (openclawRunning.value) return 'is-warning'
    return ['error', 'unavailable'].includes(openclawState.value) ? 'is-invalid' : 'is-warning'
  })

  const openclawConnectionItems = computed(() => {
    const bridge = openclawBridge.value || {}
    const statusClass = (state, readyStates) => readyStates.includes(state) ? 'is-valid' : (
      ['missing', 'offline', 'error', 'unavailable'].includes(state) ? 'is-invalid' : 'is-warning'
    )
    return [
      { key: 'gateway', label: 'OpenClaw', detail: openclawStatus.value || '正在读取 Gateway 状态', stateClass: statusClass(openclawState.value, ['running']) },
      { key: 'wechat', label: '微信', detail: bridge.wechat?.detail || '正在确认微信通道', stateClass: statusClass(bridge.wechat?.state, ['running']) },
      { key: 'mcp', label: 'KnowledgeHub', detail: bridge.mcp?.detail || '正在确认 MCP 配置', stateClass: statusClass(bridge.mcp?.state, ['configured']) },
      { key: 'backend', label: '本机处理', detail: bridge.backend?.detail || '正在确认本机后端', stateClass: statusClass(bridge.backend?.state, ['running']) },
      { key: 'conversation', label: '会话任务', detail: bridge.conversation_mapping?.detail || '正在确认会话映射', stateClass: statusClass(bridge.conversation_mapping?.state, ['ready']) }
    ]
  })

  function startOpenClawStatusPolling() {
    if (openclawTimer.value) return
    openclawTimer.value = scheduleInterval(loadOpenClawStatus, OPENCLAW_STATUS_POLL_INTERVAL_MS)
  }

  function stopOpenClawStatusPolling() {
    if (!openclawTimer.value) return
    cancelInterval(openclawTimer.value)
    openclawTimer.value = null
  }

  function applyOpenClawStatus(data) {
    openclawRunning.value = Boolean(data.gateway_running)
    openclawState.value = data.state || 'unknown'
    openclawStatus.value = data.detail || '状态未知'
    openclawBridge.value = data || {}
  }

  async function loadOpenClawStatus(forceRefresh = false) {
    try {
      const response = await request.get(`${apiBase}/openclaw-gateway`, {
        params: forceRefresh ? { refresh: true } : undefined,
        timeout: 30000
      })
      applyOpenClawStatus(response.data)
    } catch (error) {
      openclawRunning.value = false
      openclawState.value = 'error'
      openclawStatus.value = error.response?.data?.detail || error.message || '读取 OpenClaw 状态失败'
    }
  }

  async function startOpenClawGateway() {
    if (openclawRunning.value) {
      openclawScanning.value = true
      try {
        await loadOpenClawStatus(true)
        if (openclawRunning.value) notify.success(openclawStatus.value || 'OpenClaw Gateway 运行正常')
        else notify.warning(openclawStatus.value || 'OpenClaw Gateway 未响应')
      } finally {
        openclawScanning.value = false
      }
      return
    }

    openclawScanning.value = true
    try {
      const response = await request.post(`${apiBase}/openclaw-gateway/start`, {}, { timeout: 60000 })
      applyOpenClawStatus(response.data)
      if (!openclawRunning.value) throw new Error(openclawStatus.value || 'OpenClaw Gateway 未能启动')
      notify.success('OpenClaw Gateway 已启动')
    } catch (error) {
      const message = error.response?.data?.detail || error.message || '启动 OpenClaw Gateway 失败'
      openclawRunning.value = false
      openclawStatus.value = typeof message === 'string' ? message : '启动 OpenClaw Gateway 失败'
      notify.error(openclawStatus.value)
    } finally {
      openclawScanning.value = false
    }
  }

  return {
    openclawRunning,
    openclawScanning,
    openclawConnectionItems,
    openclawStatusTone,
    openclawStatusText,
    startOpenClawStatusPolling,
    stopOpenClawStatusPolling,
    loadOpenClawStatus,
    startOpenClawGateway
  }
}
