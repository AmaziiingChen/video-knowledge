import assert from 'node:assert/strict'
import test from 'node:test'

import { usePromptTemplateController } from './usePromptTemplateController.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createController(options = {}) {
  const notices = { error: [], success: [], warning: [] }
  const controller = usePromptTemplateController({
    request: {
      get: async () => ({ data: [] }),
      post: async () => ({ data: {} }),
      patch: async () => ({ data: {} }),
      delete: async () => ({ data: {} }),
      ...options.request,
    },
    notify: {
      error: (message) => notices.error.push(message),
      success: (message) => notices.success.push(message),
      warning: (message) => notices.warning.push(message),
    },
    confirmDelete: options.confirmDelete,
    refreshContentAnalysisTemplates: options.refreshContentAnalysisTemplates,
    createVersion: () => 'v-test',
  })
  return { controller, notices }
}

test('loads templates in declared order and stale task-type responses cannot replace current state', async () => {
  const first = deferred()
  const second = deferred()
  const { controller } = createController({
    request: {
      get: async (_url, options) => (
        options.params.task_type === 'summary' ? first.promise : second.promise
      ),
    },
  })

  const firstLoad = controller.loadPromptTemplates()
  controller.promptTaskType.value = 'qa'
  const secondLoad = controller.loadPromptTemplates()
  first.resolve({ data: [{ id: 'stale', name: '旧模板', template: 'old', is_active: true }] })
  await firstLoad
  assert.equal(controller.loadingPrompts.value, true)
  assert.deepEqual(controller.promptTemplates.value, [])

  second.resolve({
    data: [
      { id: 'late', name: '后排模板', template: 'later', variables_schema: '{"order":20}' },
      { id: 'active', name: 'default_qa', template: 'current', variables_schema: { order: 1 }, is_active: true },
    ],
  })
  await secondLoad

  assert.equal(controller.loadingPrompts.value, false)
  assert.deepEqual(controller.promptTemplates.value.map((item) => item.id), ['active', 'late'])
  assert.equal(controller.selectedPromptTemplateId.value, 'active')
  assert.equal(controller.promptEditorName.value, '默认追问')
  assert.equal(controller.promptEditorText.value, 'current')
})

test('creates a shortcut with the original request shape and refreshes its enabled button list', async () => {
  const requests = []
  const saved = { id: 'shortcut-1', name: '继续分析', template: '继续分析材料', task_type: 'qa_shortcut', is_active: true }
  const { controller, notices } = createController({
    request: {
      post: async (...args) => {
        requests.push(['post', ...args])
        return { data: { id: saved.id } }
      },
      get: async (...args) => {
        requests.push(['get', ...args])
        return { data: [saved, { id: 'empty', template: '   ' }] }
      },
    },
  })
  controller.createPromptTemplate({ taskType: 'qa_shortcut', name: '继续分析', folderId: 'folder-1' })
  controller.promptEditorText.value = '  继续分析材料  '

  const id = await controller.savePromptTemplate()

  assert.equal(id, 'shortcut-1')
  assert.deepEqual(requests[0], [
    'post',
    'http://127.0.0.1:8000/api/prompts',
    {
      name: '继续分析',
      task_type: 'qa_shortcut',
      version: 'v-test',
      template: '继续分析材料',
      folder_id: 'folder-1',
      is_active: true,
    },
    { timeout: 10000 },
  ])
  assert.equal(requests.filter(([method]) => method === 'get').length, 2)
  assert.deepEqual(controller.qaShortcutTemplates.value, [saved])
  assert.deepEqual(notices.success, ['快捷追问已保存并启用'])
  assert.equal(controller.savingPromptTemplate.value, false)
})

test('editing a built-in display name preserves its persisted key and refreshes content analysis', async () => {
  const requests = []
  let analysisRefreshes = 0
  const template = {
    id: 'analysis-1',
    name: 'default_summary',
    template: 'old',
    task_type: 'content_analysis',
    variables_schema: '{"order":1}',
    is_active: true,
  }
  const { controller, notices } = createController({
    request: {
      patch: async (...args) => { requests.push(args) },
      get: async () => ({ data: [{ ...template, template: 'new' }] }),
    },
    refreshContentAnalysisTemplates: async () => { analysisRefreshes += 1 },
  })
  controller.promptTaskType.value = 'content_analysis'
  controller.promptTemplates.value = [template]
  controller.selectPromptTemplate(template.id)
  controller.promptEditorName.value = '默认总结'
  controller.promptEditorText.value = '  new  '

  assert.equal(await controller.savePromptTemplate(), 'analysis-1')
  assert.deepEqual(requests, [[
    'http://127.0.0.1:8000/api/prompts/analysis-1',
    { name: 'default_summary', template: 'new', variables_schema: '{"order":1}' },
    { timeout: 10000 },
  ]])
  assert.equal(analysisRefreshes, 1)
  assert.deepEqual(notices.success, ['提示词已保存'])
})

test('delete cancellation preserves editor state while confirmation refreshes dependent templates', async () => {
  const deleted = []
  let confirmed = false
  let analysisRefreshes = 0
  const template = {
    id: 'analysis-1',
    name: '分析按钮',
    template: '分析内容',
    task_type: 'content_analysis',
  }
  const { controller } = createController({
    request: {
      delete: async (...args) => { deleted.push(args) },
      get: async () => ({ data: [] }),
    },
    confirmDelete: async () => confirmed,
    refreshContentAnalysisTemplates: async () => { analysisRefreshes += 1 },
  })
  controller.promptTaskType.value = 'content_analysis'
  controller.promptTemplates.value = [template]
  controller.selectPromptTemplate(template.id)

  await controller.deletePromptTemplate(template.id)
  assert.deepEqual(deleted, [])
  assert.equal(controller.promptEditorText.value, '分析内容')

  confirmed = true
  await controller.deletePromptTemplate(template.id)
  assert.deepEqual(deleted, [[
    'http://127.0.0.1:8000/api/prompts/analysis-1',
    { timeout: 10000 },
  ]])
  assert.equal(analysisRefreshes, 1)
  assert.equal(controller.selectedPromptTemplateId.value, '')
  assert.equal(controller.promptEditorText.value, '')
})
