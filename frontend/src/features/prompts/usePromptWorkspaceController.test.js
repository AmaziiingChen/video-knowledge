import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { usePromptWorkspaceController } from './usePromptWorkspaceController.js'

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function createController({ load = async () => {}, confirmDestructive = async () => true } = {}) {
  const taskType = ref('qa_shortcut')
  const templates = ref([])
  const selectedId = ref('')
  const editorName = ref('')
  const editorText = ref('')
  const reportText = ref('')
  const fixedSystemPrompts = ref([])
  const activeView = ref('prompts')
  const controller = usePromptWorkspaceController({
    standardPrompt: {
      taskType, templates, selectedId, editorName, editorText, load,
      select: (id) => { selectedId.value = id },
      create: ({ taskType: nextType, name }) => { taskType.value = nextType; editorName.value = name; editorText.value = '' },
      save: async () => 'saved-prompt', activate: async () => {},
      refreshQaShortcutTemplates: async () => {}, refreshContentAnalysisTemplates: async () => {},
    },
    reportPrompt: {
      prompts: ref([{ id: 'report-1', group_id: 'group-1', report_type: 'group_context', display_name: '报告', template: '报告原文' }]),
      text: reportText, load: async () => {}, save: async () => true,
      selectGroup: () => {}, selectType: () => {},
    },
    fixedSystemPrompts,
    activeView,
    confirmDestructive,
    request: { get: async (url) => ({ data: String(url).endsWith('/prompts') ? [{ id: 'saved-prompt', name: '新建提示词', task_type: 'qa_shortcut', template: '草稿' }] : [] }), post: async () => {}, patch: async () => {}, put: async () => {}, delete: async () => {} },
    notify: Object.assign(() => ({ close: () => {} }), { error: () => {}, success: () => {}, warning: () => {} }),
  })
  return { controller, taskType, templates, selectedId, editorName, editorText, reportText, fixedSystemPrompts }
}

test('opens standard, report, system, and context tabs with their proper editor boundary', async () => {
  const { controller, taskType, editorName, editorText, reportText, fixedSystemPrompts } = createController()
  await controller.openPromptWorkspaceFile({ kind: 'prompt', prompt: { id: 'prompt-1', name: '普通', task_type: 'qa_shortcut', template: '普通内容' } })
  await controller.openPromptWorkspaceFile({ kind: 'report', prompt: { id: 'report-1', group_id: 'group-1', report_type: 'group_context', display_name: '报告', template: '报告内容' } })
  fixedSystemPrompts.value = [{ id: 'rule-1', name: '系统规则', template: '规则' }]
  await controller.openSystemPromptWorkspaceFile(fixedSystemPrompts.value[0])
  await controller.openPromptContextWorkspaceFile({ id: 'context-1', name: '上下文', template: '背景' })

  assert.deepEqual(controller.promptWorkspaceTabs.value.map((tab) => tab.kind), ['prompt', 'report', 'system', 'context'])
  assert.equal(controller.activePromptTabId.value, 'context:context-1')
  assert.equal(taskType.value, 'prompt_contexts')
  assert.equal(editorName.value, '上下文')
  assert.equal(editorText.value, '背景')
  assert.equal(reportText.value, '报告内容')
})

test('dirty tab preserves its draft when close is cancelled', async () => {
  const { controller, editorText } = createController({ confirmDestructive: async () => false })
  await controller.createPromptWorkspaceFile({ taskType: 'qa_shortcut', name: '新建提示词' })
  editorText.value = '草稿'
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(controller.promptWorkspaceTabs.value[0].dirty, true)
  assert.equal(await controller.closePromptWorkspaceTab(controller.activePromptTabId.value), false)
  assert.equal(controller.promptWorkspaceTabs.value[0].draftText, '草稿')
})

test('saving a new prompt rewrites its tab identity', async () => {
  const { controller, editorText, editorName } = createController()
  await controller.createPromptWorkspaceFile({ taskType: 'qa_shortcut', name: '新建提示词' })
  editorText.value = '草稿'
  await new Promise((resolve) => setTimeout(resolve, 0))
  await controller.savePromptWorkspaceCurrent()
  assert.equal(controller.activePromptTabId.value, 'prompt:saved-prompt')
  assert.equal(controller.promptWorkspaceTabs.value[0].title, '新建提示词')
  assert.equal(editorName.value, '新建提示词')
  assert.equal(await controller.closePromptWorkspaceTab('prompt:saved-prompt'), true)
  assert.equal(controller.promptWorkspaceTabs.value.length, 0)
})

test('rapid standard tab switching restores the newest draft after a stale load finishes', async () => {
  const first = deferred()
  const second = deferred()
  let calls = 0
  const { controller, editorName, editorText, selectedId } = createController({
    load: async () => {
      const current = calls++ === 0 ? first : second
      await current.promise
      editorName.value = '来自过期加载'
      editorText.value = '过期内容'
    },
  })
  controller.promptWorkspaceTabs.value = [
    { id: 'prompt:a', kind: 'prompt', promptId: 'a', taskType: 'qa_shortcut', draftName: 'A', draftText: 'A 草稿', originalName: 'A', originalText: 'A 草稿', isNew: false, dirty: false },
    { id: 'prompt:b', kind: 'prompt', promptId: 'b', taskType: 'qa_shortcut', draftName: 'B', draftText: 'B 草稿', originalName: 'B', originalText: 'B 草稿', isNew: false, dirty: false },
  ]
  const activatingA = controller.activatePromptWorkspaceTab('prompt:a')
  const activatingB = controller.activatePromptWorkspaceTab('prompt:b')
  second.resolve()
  await activatingB
  first.resolve()
  await activatingA

  assert.equal(controller.activePromptTabId.value, 'prompt:b')
  assert.equal(selectedId.value, 'b')
  assert.equal(editorName.value, 'B')
  assert.equal(editorText.value, 'B 草稿')
})
