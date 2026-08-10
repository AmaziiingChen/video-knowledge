import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../composables/useDestructiveConfirm', () => ({
  requestDestructiveConfirmation: vi.fn(() => Promise.resolve(true)),
}))

import PromptFileTree from './PromptFileTree.vue'

const wrappers = []

const taskOptions = [
  { value: 'summary', label: '视频总结' },
  { value: 'wechat_reports', label: '公众号报告' },
]
const prompt = { id: 'prompt-1', task_type: 'summary', name: '默认总结', is_active: true }
const reportPrompt = { id: 'report-1', group_id: 'group-1', group_name: '报告组', display_name: '周报' }
const systemPrompt = { id: 'system-1', category: '系统规则', name: '固定规则' }
const promptContext = { id: 'context-1', category: '材料说明', name: '任务材料' }

function mountTree(props = {}) {
  const wrapper = mount(PromptFileTree, {
    props: {
      taskOptions,
      templates: [prompt],
      reportPrompts: [reportPrompt],
      systemPrompts: [systemPrompt],
      promptContexts: [promptContext],
      ...props,
    },
    global: {
      stubs: {
        'el-tooltip': { template: '<span><slot /></span>' },
        'el-icon': { template: '<span><slot /></span>' },
      },
      directives: { loading: () => {} },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

function treeRow(wrapper, label) {
  const row = wrapper.findAll('.sidebar-tree-row').find((candidate) => candidate.text().includes(label))
  expect(row, `missing tree row: ${label}`).toBeTruthy()
  return row
}

async function activateRow(wrapper, label) {
  await treeRow(wrapper, label).get('.sidebar-tree-row-main').trigger('click')
}

beforeEach(() => localStorage.clear())

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  localStorage.clear()
})

describe('PromptFileTree', () => {
  it('opens ordinary, report, system, and context prompts with their exact payloads', async () => {
    const wrapper = mountTree()

    await activateRow(wrapper, '默认总结')
    await activateRow(wrapper, '报告组')
    await activateRow(wrapper, '周报')
    await activateRow(wrapper, '系统提示词')
    await activateRow(wrapper, '系统规则')
    await activateRow(wrapper, '固定规则')
    await activateRow(wrapper, '任务上下文')
    await activateRow(wrapper, '材料说明')
    await activateRow(wrapper, '任务材料')

    expect(wrapper.emitted('open-prompt')).toEqual([
      [{ kind: 'prompt', prompt }],
      [{ kind: 'report', prompt: reportPrompt }],
    ])
    expect(wrapper.emitted('open-system-prompt')).toEqual([[systemPrompt]])
    expect(wrapper.emitted('open-prompt-context')).toEqual([[promptContext]])
  })

  it('loads trash on first reveal and forwards restore and confirmed permanent deletion', async () => {
    const entry = { id: 'trash-1', entry_type: 'prompt', name: '已删除提示词', item_count: 1 }
    const wrapper = mountTree({ trashEntries: [entry] })

    await wrapper.get('.prompt-tree-trash-toggle').trigger('click')
    expect(wrapper.emitted('load-trash')).toEqual([[]])

    const entryRow = wrapper.get('.prompt-tree-trash-entry')
    const actions = entryRow.findAll('button')
    await actions.find((button) => button.text() === '恢复').trigger('click')
    await actions.find((button) => button.text() === '删除').trigger('click')
    await Promise.resolve()

    expect(wrapper.emitted('restore-trash')).toEqual([[entry]])
    expect(wrapper.emitted('permanently-delete-trash')).toEqual([[entry]])
  })

  it('restores useful defaults after malformed storage and protects the final task prompt', () => {
    localStorage.setItem('knowledgehub:prompt-tree-open:v1', '{invalid')
    const wrapper = mountTree()

    expect(treeRow(wrapper, '默认总结').exists()).toBe(true)
    const deleteButton = treeRow(wrapper, '默认总结').get('.sidebar-tree-action.danger')
    expect(deleteButton.attributes('disabled')).toBeDefined()
    expect(deleteButton.attributes('aria-label')).toBe('每项功能至少保留一个提示词')
  })
})
