import { reactive, ref } from 'vue'
import axios from 'axios'

import { API_BASE as API } from '../../utils/localApiAuth.js'

const EMPTY_DAILY_USAGE = Object.freeze({
  period_start: '',
  call_count: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  prompt_cache_hit_tokens: 0,
  prompt_cache_miss_tokens: 0,
  estimated_cost: 0,
  unreported_count: 0,
  by_type: [],
  by_model: [],
  image_call_count: 0,
  image_count: 0,
  image_estimated_cost: 0,
  by_image_model: [],
})

const EMPTY_OPENCLAW_USAGE = Object.freeze({
  available: false,
  reason: '',
  session_count: 0,
  model_response_count: 0,
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  total_tokens: 0,
  estimated_cost_usd: 0,
  sessions: [],
})

function dailyUsageFrom(data = {}) {
  return {
    period_start: String(data.period_start || ''),
    call_count: Number(data.call_count || 0),
    prompt_tokens: Number(data.prompt_tokens || 0),
    completion_tokens: Number(data.completion_tokens || 0),
    total_tokens: Number(data.total_tokens || 0),
    prompt_cache_hit_tokens: Number(data.prompt_cache_hit_tokens || 0),
    prompt_cache_miss_tokens: Number(data.prompt_cache_miss_tokens || 0),
    estimated_cost: Number(data.estimated_cost || 0),
    unreported_count: Number(data.unreported_count || 0),
    by_type: Array.isArray(data.by_type) ? data.by_type : [],
    by_model: Array.isArray(data.by_model) ? data.by_model : [],
    image_call_count: Number(data.image_call_count || 0),
    image_count: Number(data.image_count || 0),
    image_estimated_cost: Number(data.image_estimated_cost || 0),
    by_image_model: Array.isArray(data.by_image_model) ? data.by_image_model : [],
  }
}

function openClawUsageFrom(data = {}) {
  return {
    available: Boolean(data.available),
    reason: String(data.reason || ''),
    session_count: Number(data.session_count || 0),
    model_response_count: Number(data.model_response_count || 0),
    input_tokens: Number(data.input_tokens || 0),
    output_tokens: Number(data.output_tokens || 0),
    cache_read_tokens: Number(data.cache_read_tokens || 0),
    cache_write_tokens: Number(data.cache_write_tokens || 0),
    total_tokens: Number(data.total_tokens || 0),
    estimated_cost_usd: Number(data.estimated_cost_usd || 0),
    sessions: Array.isArray(data.sessions) ? data.sessions : [],
  }
}

export function useAiUsageController({
  request = axios,
  apiBase = API,
  schedule = globalThis.setInterval,
  cancel = globalThis.clearInterval,
} = {}) {
  const aiCallsByContentId = reactive({})
  const dailyAiTokenUsage = ref({ ...EMPTY_DAILY_USAGE })
  const openClawTokenUsage = ref({ ...EMPTY_OPENCLAW_USAGE })
  let summaryTimer = null
  let summaryLoading = false

  async function loadContentAiCalls(contentItemId) {
    if (!contentItemId) return
    try {
      const res = await request.get(`${apiBase}/content/${contentItemId}/ai-calls`, { timeout: 10000 })
      aiCallsByContentId[contentItemId] = Array.isArray(res.data) ? res.data : []
    } catch {
      // Token 统计失败不影响内容阅读或追问。
    }
  }

  async function loadAiTokenUsageSummary() {
    if (summaryLoading) return
    summaryLoading = true
    try {
      const [knowledgeResult, openClawResult] = await Promise.allSettled([
        request.get(`${apiBase}/ai-calls/summary`, { timeout: 10000 }),
        request.get(`${apiBase}/openclaw/usage`, { timeout: 10000 }),
      ])
      if (knowledgeResult.status === 'fulfilled') dailyAiTokenUsage.value = dailyUsageFrom(knowledgeResult.value.data)
      if (openClawResult.status === 'fulfilled') openClawTokenUsage.value = openClawUsageFrom(openClawResult.value.data)
    } catch {
      // 全局 Token 汇总不可用时保留上一份数据，不影响处理流程。
    } finally {
      summaryLoading = false
    }
  }

  function appendContentAiCall(contentItemId, call) {
    if (!contentItemId || !call) return
    const existingCalls = Array.isArray(aiCallsByContentId[contentItemId]) ? aiCallsByContentId[contentItemId] : []
    aiCallsByContentId[contentItemId] = [...existingCalls, call]
    void loadAiTokenUsageSummary()
  }

  function startAiTokenUsagePolling() {
    void loadAiTokenUsageSummary()
    if (summaryTimer === null) summaryTimer = schedule(loadAiTokenUsageSummary, 15000)
  }

  function stopAiTokenUsagePolling() {
    if (summaryTimer === null) return
    cancel(summaryTimer)
    summaryTimer = null
  }

  return {
    aiCallsByContentId,
    dailyAiTokenUsage,
    openClawTokenUsage,
    loadContentAiCalls,
    loadAiTokenUsageSummary,
    appendContentAiCall,
    startAiTokenUsagePolling,
    stopAiTokenUsagePolling,
  }
}
