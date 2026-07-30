import assert from 'node:assert/strict'
import test from 'node:test'

import { starterPromptsForContent } from './starterPrompts.js'

test('uses tutorial questions for how-to content without any model call', () => {
  assert.deepEqual(
    starterPromptsForContent({ title: 'B站字幕下载工具使用教程', content_type: 'video' }),
    ['给出可执行步骤', '有哪些前置条件和风险？', '哪些细节最容易踩坑？']
  )
})

test('uses notice questions for campus notices', () => {
  assert.deepEqual(
    starterPromptsForContent({ title: '暑期图书馆开放时间', source_provider: 'campus', content_type: 'article' }),
    ['发生了什么？', '这件事对我有什么影响？', '有哪些时间节点和行动项？']
  )
})

test('uses timestamp question when timed video or audio text is available', () => {
  for (const content_type of ['video', 'audio']) {
    assert.deepEqual(
      starterPromptsForContent({
        title: `一段没有关键词的${content_type}`,
        content_type,
        text_readiness: { source_kind: 'transcript' }
      }),
      ['这条内容讲了什么？', '提炼关键观点', '关键内容在什么时间点？']
    )
  }
})

test('falls back to stable generic prompts when no rule applies', () => {
  assert.deepEqual(
    starterPromptsForContent({ title: '随手记录', content_type: 'article' }),
    ['这条内容讲了什么？', '提炼关键观点', '有哪些值得核实的结论？']
  )
})
