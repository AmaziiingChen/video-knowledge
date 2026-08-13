import { ElMessage } from 'element-plus'

import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../../utils/localApiAuth.js'

export function useAiSummaryGenerationController({
  ensureQaSession,
  syncQaSessionIfActive,
  refreshQaSessionHistory,
  readQaStream,
  addLog,
  getActiveItem = () => null,
  getCurrentSummary = () => '',
  getAiModel = () => '',
  getLogs = () => [],
  isStartingNewChat = () => false,
  fetchRequest = (...args) => globalThis.fetch(...args),
  apiBase = API,
  requestUrl = localApiRequestUrl,
  authHeaders = localApiAuthHeaders,
  schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
  cancel = (timer) => globalThis.clearTimeout(timer),
  now = () => Date.now(),
  timeLabel = () => new Date().toLocaleTimeString(),
  notify = ElMessage,
} = {}) {
  async function generateAiSummary() {
    const item = getActiveItem()
    if (!item?.id) {
      notify.warning('请先打开一篇公众号文章或一个已处理的视频')
      return
    }
    const session = ensureQaSession(item.id)
    if (session.asking || session.generatingSummary || isStartingNewChat()) return
    if (String(getCurrentSummary() || '').trim()) {
      notify.info('当前内容已有 AI 摘要')
      return
    }

    session.asking = true
    session.generatingSummary = true
    session.generatingSummaryText = ''
    session.generatingSummaryReasoning = ''
    session.generatingSummaryReasoningExpanded = false
    session.suggestedQuestions = []
    session.lastSaved = false
    syncQaSessionIfActive(item.id, session)

    const displayQuestion = '生成 AI 摘要'
    const logTaskId = `manual:summary:${item.id}:${now()}`
    const logTaskName = `生成摘要 · ${item.title || '文章'}`
    const writeRegenerationLog = (entry) => {
      addLog(
        entry.message,
        entry.level || 'info',
        entry.step || 'summarize',
        entry.elapsed_seconds ?? null,
        {
          task_id: logTaskId,
          task_name: logTaskName,
          task_status: entry.status || 'running',
          task_progress: entry.progress ?? 0,
        },
      )
    }
    writeRegenerationLog({
      message: '开始生成 AI 摘要',
      level: 'info',
      step: 'summarize',
      progress: 5,
      status: 'running',
    })
    let waitingForModelTimer = schedule(() => {
      writeRegenerationLog({
        message: 'AI 服务仍在生成，最长等待约 90 秒',
        level: 'info',
        step: 'summarize',
        progress: 35,
        status: 'running',
      })
    }, 15000)
    const pendingItem = {
      question: displayQuestion,
      answer: '',
      reasoning: '',
      reasoningExpanded: false,
      suggestedQuestions: [],
      saved: false,
      pending: true,
      error: false,
      time: timeLabel(),
    }

    try {
      const response = await fetchRequest(requestUrl(`${apiBase}/qa/stream`), {
        method: 'POST',
        headers: await authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          question: '请基于当前内容的完整原文生成 AI 摘要。',
          display_question: displayQuestion,
          summary: '',
          transcript: '',
          video_title: item.title || '',
          source_url: item.source_url || '',
          content_item_id: item.id,
          obsidian_path: null,
          history: [],
          append_to_obsidian: false,
          ai_model: getAiModel(),
          regenerate_summary: true,
        }),
      })
      if (!response.ok) {
        const errorText = await response.text()
        try {
          const errorData = JSON.parse(errorText)
          throw new Error(errorData.detail || '生成 AI 摘要失败')
        } catch (error) {
          if (error instanceof SyntaxError) throw new Error(errorText || '生成 AI 摘要失败')
          throw error
        }
      }
      await readQaStream(response, pendingItem, item.id, {
        session,
        onLog: writeRegenerationLog,
        onFirstDelta: () => {
          cancel(waitingForModelTimer)
          waitingForModelTimer = null
          writeRegenerationLog({
            message: 'AI 已开始返回总结内容',
            level: 'info',
            step: 'summarize',
            progress: 55,
            status: 'running',
          })
        },
        onFirstReasoning: () => {
          session.generatingSummaryReasoningExpanded = true
          syncQaSessionIfActive(item.id, session)
        },
        onReasoning: (reasoning) => {
          session.generatingSummaryReasoning = reasoning
          syncQaSessionIfActive(item.id, session)
        },
        onSuggestions: (questions) => {
          session.suggestedQuestions = questions
          syncQaSessionIfActive(item.id, session)
        },
        onCommit: (summary) => {
          session.generatingSummaryText = summary
          if (session.generatingSummaryReasoning) session.generatingSummaryReasoningExpanded = false
          syncQaSessionIfActive(item.id, session)
        },
      })
      // The canonical summary is updated by the stream; the existing Q&A
      // conversation intentionally remains untouched.
      if (session.lastSaved) {
        notify.success('AI 摘要已生成并自动写入 Markdown')
      } else if (pendingItem.savedToContent) {
        notify.success('AI 摘要已保存到内容记录')
      } else {
        notify.success('AI 摘要已生成')
      }
    } catch (error) {
      pendingItem.pending = false
      pendingItem.error = true
      pendingItem.answer = pendingItem.answer || '生成 AI 摘要失败'
      session.generatingSummaryText = ''
      session.generatingSummaryReasoning = ''
      session.generatingSummaryReasoningExpanded = false
      session.suggestedQuestions = []
      refreshQaSessionHistory(item.id, session)
      const failureMessage = error?.message || '生成 AI 摘要失败'
      const latestTaskLog = [...getLogs()].reverse().find((entry) => entry.task_id === logTaskId)
      if (latestTaskLog?.task_status !== 'failed') {
        writeRegenerationLog({
          message: `生成 AI 摘要失败：${failureMessage}`,
          level: 'error',
          step: 'summarize',
          progress: 100,
          status: 'failed',
        })
      }
      notify.error(failureMessage)
    } finally {
      cancel(waitingForModelTimer)
      session.asking = false
      session.generatingSummary = false
      session.generatingSummaryText = ''
      syncQaSessionIfActive(item.id, session)
    }
  }

  return { generateAiSummary }
}
