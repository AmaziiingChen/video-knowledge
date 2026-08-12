import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import AssistantComposer from './AssistantComposer.vue'

const wrappers = []

function mountComposer(props = {}) {
  const wrapper = mount(AssistantComposer, {
    props: {
      currentQaEnabled: true,
      canGenerateAiSummary: true,
      availableAiModels: [{ value: 'deepseek-v4-pro:enabled', label: 'V4 Pro Thinking', provider_label: 'DeepSeek' }],
      qaShortcutTemplates: [{ id: 'summary', name: '总结', template: '总结正文' }],
      contentAnalysisTemplates: [{ id: 'analysis', name: '提炼观点', is_active: true }],
      ...props,
    },
    global: {
      stubs: {
        'el-tooltip': { template: '<span><slot /></span>' },
        'el-icon': { template: '<span><slot /></span>' },
        SvgMaskIcon: { template: '<i />' },
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

describe('AssistantComposer', () => {
  it('keeps input, model, shortcut and send events on the existing contract', async () => {
    const wrapper = mountComposer()
    await wrapper.get('textarea').setValue('问题')
    expect(wrapper.emitted('update:questionInput')).toEqual([['问题']])
    await wrapper.setProps({ questionInput: '问题' })
    await wrapper.get('[aria-label="发送"]').trigger('click')
    expect(wrapper.emitted('ask-question')).toEqual([[]])

    await wrapper.get('[aria-label="切换模型"]').trigger('click')
    const model = wrapper.findAll('.assistant-model-option').find((item) => item.text().includes('V4 Pro Thinking'))
    await model.trigger('click')
    expect(wrapper.emitted('update:selectedAiModel')).toEqual([['deepseek-v4-pro:enabled']])
    expect(wrapper.find('.assistant-model-options').exists()).toBe(false)

    await wrapper.get('.assistant-command-menu-button').trigger('click')
    await wrapper.get('.assistant-shortcut-suggestion').trigger('click')
    expect(wrapper.emitted('insert-shortcut')).toEqual([['总结']])
  })

  it('shows model names only while preserving provider-qualified selection values', async () => {
    const wrapper = mountComposer({
      selectedAiModel: 'qwen::qwen3.7-plus:enabled',
      availableAiModels: [
        {
          value: 'qwen::qwen3.7-plus:enabled',
          label: 'Qwen3.7 Plus',
          provider: 'qwen',
          provider_label: '阿里云百炼 · 千问',
        },
        {
          value: 'mimo::mimo-v2-pro:enabled',
          label: 'MiMo V2 Pro',
          provider: 'mimo',
          provider_label: 'Xiaomi MiMo',
        },
      ],
    })

    expect(wrapper.get('[aria-label="切换模型"]').text()).toContain('Qwen3.7 Plus')
    expect(wrapper.get('[aria-label="切换模型"]').text()).not.toContain('千问')
    await wrapper.get('[aria-label="切换模型"]').trigger('click')
    const options = wrapper.findAll('.assistant-model-option')
    expect(options.map((option) => option.text())).toContain('MiMo V2 Pro')
    expect(wrapper.get('.assistant-model-options').text()).not.toContain('Xiaomi MiMo')
    await options.find((option) => option.text() === 'MiMo V2 Pro').trigger('click')
    expect(wrapper.emitted('update:selectedAiModel')).toEqual([['mimo::mimo-v2-pro:enabled']])
  })

  it('preserves OCR and contextual action gates and events', async () => {
    const wrapper = mountComposer({
      articleOcrStatus: { status: 'queued', priority: false },
      currentInsightHtml: '<p>摘要</p>',
    })
    await wrapper.get('.assistant-ocr-button').trigger('click')
    await wrapper.get('[aria-label="开启新对话"]').trigger('click')
    await wrapper.get('[aria-label="生成 AI 摘要"]').trigger('click')
    await wrapper.get('[aria-label="导出当前 AI 对话为 Markdown"]').trigger('click')
    await wrapper.get('[aria-label="在当前对话中使用提炼观点"]').trigger('click')
    expect(wrapper.emitted('prioritize-ocr')).toEqual([[]])
    expect(wrapper.emitted('new-chat')).toEqual([[]])
    expect(wrapper.emitted('generate-ai-summary')).toEqual([[]])
    expect(wrapper.emitted('export-markdown')).toEqual([[]])
    expect(wrapper.emitted('run-content-analysis')).toEqual([[]])

    await wrapper.setProps({ askingQuestion: true })
    expect(wrapper.get('[aria-label="切换模型"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="开启新对话"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="生成 AI 摘要"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-label="在当前对话中使用提炼观点"]').attributes('disabled')).toBeDefined()
  })
})
