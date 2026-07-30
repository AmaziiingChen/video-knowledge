const GENERIC_PROMPTS = [
  '这条内容讲了什么？',
  '提炼关键观点',
  '有哪些值得核实的结论？'
]

const PROMPT_PROFILES = [
  {
    name: 'notice',
    matches: ({ title, provider }) => (
      provider === 'campus'
      || /通知|公告|政策|新闻|通报|活动|报名|招标|招聘|会议|赛事|征集/u.test(title)
    ),
    prompts: ['发生了什么？', '这件事对我有什么影响？', '有哪些时间节点和行动项？']
  },
  {
    name: 'tutorial',
    matches: ({ title }) => /教程|入门|指南|实战|操作|配置|使用|方法|如何|怎么|技巧|流程|步骤|搭建|实现/u.test(title),
    prompts: ['给出可执行步骤', '有哪些前置条件和风险？', '哪些细节最容易踩坑？']
  },
  {
    name: 'tool',
    matches: ({ title }) => /工具|产品|应用|软件|平台|项目|模型|人工智能|\bai\b|agent|skill|开源|github/u.test(title),
    prompts: ['它解决什么问题？', '适合什么场景？', '有哪些限制或替代方案？']
  },
  {
    name: 'analysis',
    matches: ({ title }) => /观点|复盘|分享|演讲|访谈|对话|思考|经验|趋势|解读|分析/u.test(title),
    prompts: ['提炼关键观点', '作者的论据是否充分？', '哪些结论值得核实？']
  },
  {
    name: 'timed-media',
    matches: ({ contentType, sourceKind }) => (
      ['video', 'audio'].includes(contentType) && ['subtitle', 'transcript'].includes(sourceKind)
    ),
    prompts: ['这条内容讲了什么？', '提炼关键观点', '关键内容在什么时间点？']
  },
  {
    name: 'report',
    matches: ({ contentType, provider }) => contentType === 'report' || provider === 'wechat_report',
    prompts: ['用三点概括这份报告', '有哪些行动项？', '哪些结论值得进一步跟进？']
  }
]

function promptContext(content) {
  return {
    title: String(content?.title || '').trim().toLocaleLowerCase(),
    provider: String(content?.source_provider || '').trim().toLocaleLowerCase(),
    contentType: String(content?.content_type || '').trim().toLocaleLowerCase(),
    sourceKind: String(content?.text_readiness?.source_kind || '').trim().toLocaleLowerCase()
  }
}

/**
 * Choose a useful first question without pre-reading content through an LLM.
 * This keeps the empty conversation state instantaneous and token-free.
 */
export function starterPromptsForContent(content) {
  const context = promptContext(content)
  return PROMPT_PROFILES.find((profile) => profile.matches(context))?.prompts || GENERIC_PROMPTS
}
