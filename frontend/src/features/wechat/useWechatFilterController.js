import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

export function useWechatFilterController({
  filterApi,
  loadSubscriptions,
  request = axios,
  notify = ElMessage,
  errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback,
} = {}) {
  const savingWeChatFilter = ref(false)

  function notifyError(error, fallback) {
    const message = errorMessage(error, fallback)
    notify.error(typeof message === 'string' ? message : fallback)
  }

  async function createWeChatFilter(payload, done) {
    savingWeChatFilter.value = true
    try {
      await request.post(filterApi, payload, { timeout: 10000 })
      done?.()
      notify.success('正文清洗规则已添加')
      await loadSubscriptions()
    } catch (error) {
      notifyError(error, '添加正文清洗规则失败')
    } finally {
      savingWeChatFilter.value = false
    }
  }

  async function deleteWeChatFilter(ruleId) {
    try {
      await request.delete(`${filterApi}/${ruleId}`, { timeout: 10000 })
      notify.success('正文清洗规则已删除')
      await loadSubscriptions()
    } catch (error) {
      notifyError(error, '删除正文清洗规则失败')
    }
  }

  return { savingWeChatFilter, createWeChatFilter, deleteWeChatFilter }
}
