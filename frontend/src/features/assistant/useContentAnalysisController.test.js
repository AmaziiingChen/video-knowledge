import assert from 'node:assert/strict'
import test from 'node:test'

import { useContentAnalysisController } from './useContentAnalysisController.js'

test('loads only active, non-empty content-analysis prompt buttons', async () => {
  let receivedOptions
  const controller = useContentAnalysisController({
    sortTemplates: (templates) => [...templates].sort((left, right) => left.id.localeCompare(right.id)),
    askQuestion: () => {},
    request: {
      get: async (_url, options) => {
        receivedOptions = options
        return { data: [
          { id: 'b', is_active: true, template: '  ' },
          { id: 'a', is_active: true, template: '分析这份资料' },
          { id: 'c', is_active: false, template: '不应显示' },
        ] }
      },
    },
    apiBase: '/api',
  })

  await controller.loadContentAnalysisTemplates()

  assert.deepEqual(receivedOptions, { params: { task_type: 'content_analysis' }, timeout: 10000 })
  assert.deepEqual(controller.contentAnalysisTemplates.value.map((template) => template.id), ['a'])
})

test('clears unavailable templates and delegates an active button to the existing question flow', async () => {
  const messages = []
  const questions = []
  const controller = useContentAnalysisController({
    sortTemplates: (templates) => templates,
    askQuestion: (...args) => questions.push(args),
    notify: { error: (message) => messages.push(message) },
    request: { get: async () => { throw new Error('offline') } },
  })

  await controller.loadContentAnalysisTemplates()
  controller.runContentAnalysis()
  assert.deepEqual(controller.contentAnalysisTemplates.value, [])
  assert.deepEqual(messages, ['未找到可用的自定义按钮提示词'])

  controller.contentAnalysisTemplates.value = [{ id: 'template-1', is_active: true, template: '请分析' }]
  controller.runContentAnalysis()
  assert.deepEqual(questions, [['', { customTemplate: controller.contentAnalysisTemplates.value[0] }]])
})
