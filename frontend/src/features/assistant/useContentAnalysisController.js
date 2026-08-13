import { ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { API_BASE as API } from '../../utils/localApiAuth.js'

export function useContentAnalysisController({
  sortTemplates,
  askQuestion,
  notify = ElMessage,
  request = axios,
  apiBase = API,
} = {}) {
  const contentAnalysisTemplates = ref([])

  async function loadContentAnalysisTemplates() {
    try {
      const res = await request.get(`${apiBase}/prompts`, {
        params: { task_type: 'content_analysis' },
        timeout: 10000,
      })
      contentAnalysisTemplates.value = sortTemplates(res.data || [])
        .filter((template) => template.is_active && template.template?.trim())
    } catch {
      contentAnalysisTemplates.value = []
    }
  }

  function runContentAnalysis() {
    const customTemplate = contentAnalysisTemplates.value[0]
    if (!customTemplate?.template?.trim()) {
      notify.error('未找到可用的自定义按钮提示词')
      return
    }
    return askQuestion('', { customTemplate })
  }

  return { contentAnalysisTemplates, loadContentAnalysisTemplates, runContentAnalysis }
}
