export const stages = [
  { key: 'parse', label: '解析' },
  { key: 'download', label: '下载' },
  { key: 'extract_audio', label: '音频' },
  { key: 'transcribe', label: '转写' },
  { key: 'summarize', label: '总结' },
  { key: 'save', label: '保存' }
]

export const modelProfiles = [
  { model: 'tiny', label: '快', note: '最快，适合先看大意' },
  { model: 'base', label: '均衡', note: '速度和准确率折中' },
  { model: 'small', label: '准确', note: '更稳，耗时更久' },
  { model: 'medium', label: '深度', note: '长视频会很慢' },
  { model: 'large-v3', label: '最细', note: '重模型，谨慎使用' }
]

export const stepNames = {
  parse: '解析',
  info: '信息',
  download: '下载',
  extract_audio: '音频',
  transcribe: '转写',
  summarize: '总结',
  save: '保存',
  total: '总计',
  config: '配置',
  cancelled: '取消',
  paused: '暂停',
  interrupted: '中断',
  executor: '执行器',
  whisper_model_load: '模型加载',
  whisper_decode: '语音识别',
  report_prepare: '报告准备',
  report_sources: '来源装载',
  report_source_summaries: '材料短摘要',
  report_section_plan: '栏目规划',
  report_citation_repair: '引用校对',
  report_event_ledgers: '事件事实账本',
  report_section_write: '栏目正文',
  report_facts: '事实卡',
  report_embeddings: '语义向量',
  report_clustering: '事件聚类',
  report_briefs: '事件摘要',
  report_sections: '栏目生成',
  report_overview: '本期概览',
  report_audit: '事实审校',
  report_save: '保存报告'
}

export const timingOrder = [
  'parse',
  'info',
  'download',
  'extract_audio',
  'whisper_model_load',
  'whisper_decode',
  'transcribe',
  'summarize',
  'save',
  'total'
]

export const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled'])

export const preferredModelOrder = ['tiny', 'base', 'small', 'medium', 'large-v3']

export const contentStatusOptions = [
  { value: 'all', label: '全部' },
  { value: 'processing', label: '处理中' },
  { value: 'to_read', label: '待阅读' },
  { value: 'distilled', label: '已沉淀' },
  { value: 'archived', label: '归档' },
  { value: 'failed', label: '失败' }
]

export const promptTaskOptions = [
  { value: 'summary', label: '总结' },
  { value: 'article_summary', label: '长文总结' },
  { value: 'article_material_reduction', label: '长文材料压缩' },
  { value: 'document_formatting', label: 'PDF OCR 排版' },
  { value: 'qa', label: '追问' },
  { value: 'qa_shortcut', label: '快捷追问' },
  { value: 'content_analysis', label: '自定义按钮' },
  { value: 'source_context_analysis', label: '互动评论规则' },
  { value: 'knowledge_query_rewrite', label: '检索查询改写' },
  { value: 'knowledge_answer', label: '基于证据回答' },
  { value: 'knowledge_answer_retry', label: '回答格式重试' },
  { value: 'wechat_reports', label: '分组报告' },
  { value: 'wechat_cover_planner', label: '封面主题策划' },
  { value: 'wechat_cover_image', label: '封面图像生成' },
  { value: 'group_report_source_summary', label: '单篇短摘要' },
  { value: 'group_report_section_plan', label: '栏目规划' },
  { value: 'group_report_event_ledger', label: '事件事实账本' },
  { value: 'group_report_section_writer', label: '栏目写作' },
  { value: 'group_report_overview', label: '概览写作' }
]

export const ribbonItems = [
  { view: 'library', label: '资源管理器', icon: 'folder' },
  { view: 'prompts', label: '提示词', icon: 'prompt' },
  { view: 'wechat', label: '公众号管理', icon: 'wechat' },
  { view: 'campus', label: '网页管理', icon: 'campus' },
  { view: 'creator', label: '创作者采集', icon: 'creator' },
  { view: 'rss', label: 'RSS 订阅', icon: 'rss' },
  { view: 'reports', label: '生成报告', icon: 'report' }
]
