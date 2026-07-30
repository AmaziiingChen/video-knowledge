import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assistantSummaryFromMarkdown,
  documentMarkdownWithoutConversation,
  reportMarkdownForCenter,
  sourceMarkdownForCenter,
} from './assistantMarkdown.js'

test('extracts only the canonical AI summary, never the source body', () => {
  const markdown = `---\nid: "one"\n---\n\n# 标题\n\n## 原文内容\n\n不应显示的原文。\n\n## AI 摘要\n\n这是应显示的摘要。\n\n## 报告章节\n\n摘要内的二级标题必须保留。\n\n## 追问记录\n\n不应显示的问答。\n`
  assert.equal(assistantSummaryFromMarkdown(markdown), '这是应显示的摘要。\n\n## 报告章节\n\n摘要内的二级标题必须保留。')
})

test('returns no sidebar summary for a source document without an AI summary', () => {
  const markdown = '# 标题\n\n## 原文内容\n\n只有原文。\n\n## AI 摘要\n\n<!-- 由应用生成；人工编辑内容将被保留。 -->\n'
  assert.equal(assistantSummaryFromMarkdown(markdown), '')
})

test('does not treat an empty conversation heading as an AI summary', () => {
  const markdown = '# 标题\n\n## 原文内容\n\n正文。\n\n## AI 摘要\n## 追问记录\n'
  assert.equal(assistantSummaryFromMarkdown(markdown), '')
})

test('keeps legacy collapsed-source summaries compatible', () => {
  const markdown = '# 标题\n\n旧摘要。\n\n<details>\n<summary>原文正文</summary>\n\n原文。\n</details>\n'
  assert.equal(assistantSummaryFromMarkdown(markdown), '旧摘要。')
})

test('does not treat a legacy report body as a sidebar summary', () => {
  const report = '# 本周周报\n\n> 分组：测试 · 分析文章：2 篇\n\n## 本周重点\n\n报告正文。\n\n## 追问记录\n\n#### 2026-07-21\n\n**问：** 问题\n\n**答：** 回答'
  assert.equal(assistantSummaryFromMarkdown(report), '')
})

test('removes sidebar conversations without removing report or source content', () => {
  const markdown = '# 标题\n\n## AI 摘要\n\n摘要。\n\n## 追问记录\n\n### 对话 1（当前）\n\n**问：** 问题\n\n**答：** 回答'
  assert.equal(documentMarkdownWithoutConversation(markdown), '# 标题\n\n## AI 摘要\n\n摘要。')
})

test('keeps generated summaries and conversations out of a source reader', () => {
  const markdown = '# 标题\n\n## 原文内容\n\n> 这是原文引用。\n\n```js\nconst answer = 42\n```\n\n## AI 摘要\n\n不应出现在原文预览。\n\n## 追问记录\n\n**问：** 也不应出现。'
  assert.equal(
    sourceMarkdownForCenter(markdown),
    '# 标题\n\n## 原文内容\n\n> 这是原文引用。\n\n```js\nconst answer = 42\n```'
  )
})

test('keeps generated report bodies in the center and strips their conversations', () => {
  const legacyReport = '# 周报\n\n> 分组：测试\n\n## AI 摘要\n\n## 本周重点\n\n报告正文。\n\n## 追问记录\n\n**问：** 问题'
  const canonicalReport = '# 周报\n\n> 分组：测试\n\n## 报告正文\n\n## 本周重点\n\n报告正文。\n\n## 追问记录\n\n**问：** 问题'
  assert.equal(reportMarkdownForCenter(legacyReport), '# 周报\n\n> 分组：测试\n\n## 本周重点\n\n报告正文。')
  assert.equal(reportMarkdownForCenter(canonicalReport), '# 周报\n\n> 分组：测试\n\n## 本周重点\n\n报告正文。')
})
