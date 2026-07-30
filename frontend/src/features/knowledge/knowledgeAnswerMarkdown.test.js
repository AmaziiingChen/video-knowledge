import assert from 'node:assert/strict'
import test from 'node:test'
import { knowledgeAnswerMarkdown } from './knowledgeAnswerMarkdown.js'

test('turns only returned evidence IDs into shared Markdown footnotes', () => {
  const markdown = knowledgeAnswerMarkdown('RRF 同时融合两路召回。[E001] 未引用的 [E404] 保持原样。', [{
    evidence_id: 'E001',
    title: '混合检索原理',
    source_label: 'LaTeX工作室',
    published_at: '2026-07-30',
    source_url: 'https://example.com/rrf',
  }])

  assert.match(markdown, /两路召回。\[\^E001\]/)
  assert.match(markdown, /\[E404\]/)
  assert.match(markdown, /\[\^E001\]: \[混合检索原理\]/)
})
