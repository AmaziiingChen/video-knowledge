import axios from 'axios'
import { ElMessage, ElNotification } from 'element-plus'

import { API_BASE as API, localApiAuthHeaders, localApiRequestUrl } from '../../utils/localApiAuth.js'
import { qaHistoryForPrompt } from './qaHistory.js'

export function useQaRequestController({
  ensureQaSession,
  syncQaSessionIfActive,
  refreshQaSessionHistory,
  resolveQaQuestion,
  removeSelectedTextContextToken,
  readQaStream,
  getRequestContext = () => ({}),
  getActiveContentId = () => null,
  isStartingNewChat = () => false,
  loadCompletionNotifications = async () => {},
  fetchRequest = (...args) => globalThis.fetch(...args),
  request = axios,
  apiBase = API,
  requestUrl = localApiRequestUrl,
  authHeaders = localApiAuthHeaders,
  getVisibilityState = () => globalThis.document?.visibilityState || 'visible',
  now = () => Date.now(),
  timeLabel = () => new Date().toLocaleTimeString(),
  notify = ElMessage,
  notifyCompletion = ElNotification,
} = {}) {
  async function askQuestion(quickPrompt = '', { customTemplate = null } = {}) {
    const context = getRequestContext() || {}
    const contentItemId = context.contentItemId || null
    const session = ensureQaSession(contentItemId)
    if (session.asking || session.generatingSummary || isStartingNewChat()) return
    const draftQuestion = customTemplate
      ? `自定义按钮：${customTemplate.name || '未命名提示词'}`
      : removeSelectedTextContextToken(String(quickPrompt || session.draft)).trim()
    const resolvedQuestion = customTemplate
      ? {
          prompt: `已选择的追问方式：\n${customTemplate.name || '自定义按钮'}\n${customTemplate.template.trim()}`,
          autoShortcutName: '',
        }
      : resolveQaQuestion(draftQuestion)
    const question = resolvedQuestion.prompt
    if (!question) {
      notify.warning('请输入追问内容')
      return
    }
    const selectionContext = context.selectionContext
    const modelQuestion = selectionContext
      ? `【用户选中的原文】\n${selectionContext.text}\n\n【用户的问题】\n${question}`
      : question
    const displayQuestion = selectionContext
      ? `@选中文本\n> ${selectionContext.text.replace(/\n/gu, '\n> ')}\n\n${draftQuestion}`
      : draftQuestion
    session.asking = true
    session.lastSaved = false
    syncQaSessionIfActive(contentItemId, session)
    const historySnapshot = qaHistoryForPrompt(session.history)
    const pendingItem = {
      question: draftQuestion,
      modelQuestion,
      displayQuestion,
      selectedText: selectionContext?.text || '',
      answer: '',
      saved: false,
      autoShortcutName: resolvedQuestion.autoShortcutName,
      pending: true,
      error: false,
      time: timeLabel(),
    }
    session.history.push(pendingItem)
    refreshQaSessionHistory(contentItemId, session)
    if (!quickPrompt && !customTemplate) {
      session.draft = ''
      syncQaSessionIfActive(contentItemId, session)
    }
    try {
      const headers = await authHeaders({ 'Content-Type': 'application/json' })
      const requestContext = getRequestContext() || {}
      const shouldAppendToObsidian = requestContext.obsidianAutoWrite && Boolean(requestContext.obsidianPath)
      const response = await fetchRequest(requestUrl(`${apiBase}/qa/stream`), {
        method: 'POST',
        headers,
        body: JSON.stringify({
          question: modelQuestion,
          display_question: displayQuestion,
          summary: requestContext.summary || '',
          transcript: requestContext.transcript || '',
          video_title: requestContext.videoTitle || '',
          source_url: requestContext.sourceUrl || '',
          content_item_id: contentItemId,
          obsidian_path: shouldAppendToObsidian ? requestContext.obsidianPath : null,
          history: historySnapshot,
          append_to_obsidian: shouldAppendToObsidian,
          ai_model: requestContext.aiModel,
        }),
      })
      if (!response.ok) {
        const errorText = await response.text()
        try {
          const errorData = JSON.parse(errorText)
          throw new Error(errorData.detail || '追问失败')
        } catch (error) {
          if (error instanceof SyntaxError) throw new Error(errorText || '追问失败')
          throw error
        }
      }
      await readQaStream(response, pendingItem, contentItemId, { session })
      // A response may finish after the user has moved to another document or
      // hidden the app. Persist a bounded local completion event in that case.
      if (
        String(getActiveContentId() || '') !== String(contentItemId || '')
        || getVisibilityState() !== 'visible'
      ) {
        const questionPreview = String(draftQuestion || 'AI 追问').replace(/\s+/gu, ' ').slice(0, 80)
        const answerPreview = String(pendingItem.answer || '').replace(/\s+/gu, ' ').slice(0, 240)
        await request.post(`${apiBase}/completion-notifications`, {
          event_key: `qa:${contentItemId || 'workspace'}:${pendingItem.id || now()}`,
          event_type: 'assistant_response',
          title: questionPreview,
          body: answerPreview,
          content_item_id: contentItemId,
          target_view: 'library',
        }, { timeout: 10000 }).catch(() => {})
        await loadCompletionNotifications()
        if (getVisibilityState() === 'visible') {
          notifyCompletion({
            title: questionPreview,
            message: answerPreview || 'AI 已完成回复，点击顶部待查看按钮可回到这条内容。',
            duration: 6000,
          })
        }
      }
      if (resolvedQuestion.autoShortcutName) {
        notify.info(`已按本地规则附加 @${resolvedQuestion.autoShortcutName} 追问指引`)
      }
      if (session.lastSaved) {
        notify.success('追问已自动写入 Markdown')
      } else if (pendingItem.savedToContent) {
        if (pendingItem.obsidianError) {
          notify.warning('回答已保存到内容记录；Markdown 未自动写入')
        } else {
          notify.success('已保存到内容记录，可在重新打开时继续追问')
        }
      } else {
        notify.success('已基于当前内容生成回答')
      }
    } catch (error) {
      pendingItem.pending = false
      pendingItem.error = true
      pendingItem.answer = pendingItem.answer || '追问失败'
      refreshQaSessionHistory(contentItemId, session)
      const message = error?.response?.data?.detail || error?.message || '追问失败'
      notify.error(typeof message === 'string' ? message : '追问失败')
    } finally {
      session.asking = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  async function regenerateQaAnswer(item) {
    const context = getRequestContext() || {}
    const contentItemId = context.contentItemId || null
    const session = ensureQaSession(contentItemId)
    const itemIndex = session.history.indexOf(item)
    if (!contentItemId || !item?.id || itemIndex !== session.history.length - 1) {
      notify.warning('只能重新生成当前会话最后一条回答')
      return
    }
    if (session.asking || session.generatingSummary || isStartingNewChat() || item.pending) return

    const previousAnswer = String(item.answer || '')
    const question = String(item.modelQuestion || resolveQaQuestion(item.question).prompt || '').trim()
    if (!question) {
      notify.warning('找不到原始提问，无法重新生成')
      return
    }
    const historySnapshot = qaHistoryForPrompt(session.history.slice(0, itemIndex))
    session.asking = true
    session.lastSaved = false
    item.answer = ''
    item.pending = true
    item.error = false
    refreshQaSessionHistory(contentItemId, session)
    try {
      const headers = await authHeaders({ 'Content-Type': 'application/json' })
      const requestContext = getRequestContext() || {}
      const response = await fetchRequest(requestUrl(`${apiBase}/qa/stream`), {
        method: 'POST',
        headers,
        body: JSON.stringify({
          question,
          display_question: String(item.displayQuestion || item.question || '').trim(),
          summary: requestContext.summary || '',
          transcript: requestContext.transcript || '',
          video_title: requestContext.videoTitle || '',
          source_url: requestContext.sourceUrl || '',
          content_item_id: contentItemId,
          history: historySnapshot,
          append_to_obsidian: false,
          ai_model: requestContext.aiModel,
          regenerate_assistant_message_id: item.id,
        }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || '重新生成回答失败')
      }
      await readQaStream(response, item, contentItemId, { session })
      notify.success(item.obsidianError ? '回答已重新生成，但 Markdown 更新失败' : '回答已重新生成')
    } catch (error) {
      item.answer = previousAnswer
      item.pending = false
      item.error = false
      refreshQaSessionHistory(contentItemId, session)
      notify.error(error?.message || '重新生成回答失败')
    } finally {
      session.asking = false
      syncQaSessionIfActive(contentItemId, session)
    }
  }

  return { askQuestion, regenerateQaAnswer }
}
