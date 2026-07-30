export const promptTaskGroups = [
  {
    id: 'content',
    label: '内容处理',
    taskTypes: ['summary', 'article_summary', 'article_material_reduction', 'document_formatting']
  },
  {
    id: 'assistant',
    label: '侧栏操作',
    taskTypes: ['qa', 'qa_shortcut', 'content_analysis', 'source_context_analysis']
  },
  {
    id: 'knowledge',
    label: '知识问答',
    taskTypes: ['knowledge_query_rewrite', 'knowledge_answer', 'knowledge_answer_retry']
  },
  {
    id: 'sources',
    label: '分组报告',
    taskTypes: ['wechat_reports', 'wechat_cover_planner', 'wechat_cover_image']
  },
  {
    id: 'group-report-pipeline',
    label: '分组报告管线',
    taskTypes: ['group_report_source_summary', 'group_report_section_plan', 'group_report_event_ledger', 'group_report_section_writer', 'group_report_overview']
  }
]

export const promptTaskContracts = {
  system_prompts: {
    entry: '系统提示词目录',
    input: '当前实际发送给模型的系统角色内容',
    output: '仅供核对与验收，不可在此修改',
    variables: []
  },
  prompt_contexts: {
    entry: '分组报告任务上下文目录',
    input: '随每个生成阶段附在 user 消息中的组别说明',
    output: '仅供核对与验收，不可在此修改',
    variables: []
  },
  summary: {
    entry: '视频处理流程',
    input: '视频标题与字幕或转写',
    output: '视频学习笔记',
    variables: []
  },
  article_summary: {
    entry: '文章处理流程',
    input: '文章标题与正文',
    output: '文章学习笔记',
    variables: []
  },
  article_material_reduction: {
    entry: '超长文章重新总结',
    input: '按原文顺序截取的文章材料与 OCR',
    output: '供最终总结使用的紧凑材料',
    variables: []
  },
  document_formatting: {
    entry: '采购 PDF OCR 阅读器',
    input: 'PaddleOCR 返回的 Markdown（含 HTML 表格）',
    output: '保真排版后的 Markdown',
    variables: []
  },
  qa: {
    entry: '右侧 AI 助手',
    input: '当前内容、已有总结与对话历史',
    output: '问答记录',
    variables: []
  },
  qa_shortcut: {
    entry: '右侧助手快捷命令',
    input: '当前内容与对话历史',
    output: '问答记录',
    variables: []
  },
  content_analysis: {
    entry: '右侧助手自定义按钮',
    input: '当前内容、已有总结与对话历史',
    output: '同一对话中的问答记录',
    variables: []
  },
  source_context_analysis: {
    entry: '视频总结、重新总结、追问与自定义按钮',
    input: '平台互动指标与有界评论样本',
    output: '对评论共识、分歧、疑问和反馈的归因分析',
    variables: []
  },
  knowledge_query_rewrite: {
    entry: '知识问答：检索前',
    input: '用户原始问题',
    output: '用于全文与向量召回的 JSON 查询',
    variables: []
  },
  knowledge_answer: {
    entry: '知识问答：回答生成',
    input: '用户问题与已召回证据',
    output: '带证据 ID 的 JSON 回答',
    variables: []
  },
  knowledge_answer_retry: {
    entry: '知识问答：回答异常重试',
    input: '上一轮无效输出后的原问题与证据',
    output: '修复后的 JSON 回答',
    variables: []
  },
  wechat_reports: {
    entry: '分组报告组别',
    input: '组别说明或某一阶段的领域适配规则',
    output: '与通用管线组合后的区间报告',
    variables: []
  },
  group_report_source_summary: {
    entry: '分组报告：单篇短摘要',
    input: '一篇完整来源原文（含按顺序插入的 OCR）与分组适配',
    output: '不超过 200 字的规划摘要',
    variables: []
  },
  group_report_section_plan: {
    entry: '分组报告：栏目规划',
    input: '全量单篇短摘要、组别说明与规划适配',
    output: '每篇来源唯一归属到事件单元的动态栏目 JSON',
    variables: []
  },
  group_report_event_ledger: {
    entry: '分组报告：事件事实账本',
    input: '一个事件单元的完整来源原文、组别说明与事件适配',
    output: '覆盖全部来源的紧凑事实账本 JSON',
    variables: []
  },
  group_report_section_writer: {
    entry: '分组报告：栏目写作',
    input: '一个事件的事实账本、组别说明与写作适配',
    output: '带来源引用的紧凑事件正文',
    variables: []
  },
  group_report_overview: {
    entry: '分组报告：概览写作',
    input: '已经完成的栏目正文、组别说明与概览适配',
    output: '只包含概览的 Markdown',
    variables: []
  },
  wechat_cover_planner: {
    entry: '报告右上角：生成或重新策划 AI 封面',
    input: '用户选择的封面风格、报告标题、报告类型与完整 Markdown 正文',
    output: '可编辑的封面视觉策划 JSON',
    variables: ['{cover_style}', '{article_title}', '{report_type}', '{report_markdown}']
  },
  wechat_cover_image: {
    entry: '封面视觉策划确认后',
    input: '用户选择的封面风格与经过过滤的视觉执行简报',
    output: '发送给图像模型的所选风格完整提示词',
    variables: ['{cover_style}', '{visual_brief}']
  }
}

const DEFAULT_PROMPT_DISPLAY_NAMES = {
  default_summary: '默认总结',
  default_article_summary: '默认长文总结',
  default_qa: '默认追问',
  '互动评论分析规则': '互动评论分析规则',
}

export function promptTemplateDisplayName(template) {
  if (!template) return ''
  const name = String(template?.name || '').trim()
  return DEFAULT_PROMPT_DISPLAY_NAMES[name] || name || '未命名提示词'
}

export function promptTemplatePersistedName(template, editorName) {
  const name = String(editorName || '').trim()
  if (!template) return name
  return name === promptTemplateDisplayName(template) ? template.name : name
}
