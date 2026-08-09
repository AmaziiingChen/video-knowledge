import assert from 'node:assert/strict'
import test from 'node:test'
import { createEditorReportPresentation } from './editorReportPresentation.js'

function createPresentation(content = {}, tab = {}) {
  return createEditorReportPresentation({
    contentForTab: () => content,
    workspaceTabById: () => tab,
  })
}

test('formats report titles and one-day or same-year date ranges', () => {
  const presentation = createPresentation({ title: '2026-08-01｜产品观察周报' })
  assert.equal(presentation.reportTypeLabel('report'), '周报')
  assert.equal(presentation.reportDisplayTitle('report'), '产品观察周报周报')
  assert.equal(presentation.reportDateLabel('report'), '2026年8月1日')

  const range = createPresentation({ title: '日报 2026-08-01 至 2026-08-08' })
  assert.equal(range.reportDisplayTitle('report'), '日报 2026-08-01 至 2026-08-08')
  assert.equal(range.reportDateLabel('report'), '2026年8月1日—8月8日')
})

test('retains the end year for cross-year reports and falls back safely', () => {
  const presentation = createPresentation({ title: '2025-12-30 至 2026-01-05 报告' })
  assert.equal(presentation.reportDateLabel('report'), '2025年12月30日—2026年1月5日')
  assert.equal(createPresentation({ title: '无日期报告' }).reportDateLabel('report'), '生成报告')
})

test('uses tab fallback and rejects invalid generated timestamps', () => {
  const timestamp = new Date(2026, 0, 2, 3, 4).toISOString()
  const presentation = createPresentation({}, { title: '2026-01-02｜测试日报', opened_at: timestamp })
  assert.equal(presentation.reportDisplayTitle('report'), '测试日报日报')
  assert.equal(presentation.reportGeneratedLabel('report'), '生成于 2026年1月2日 03:04')
  assert.equal(createPresentation({ created_at: 'not-a-date' }).reportGeneratedLabel('report'), '')
})
