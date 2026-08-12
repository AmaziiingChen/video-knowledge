import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import SecondarySidebar from './SecondarySidebar.vue'

describe('SecondarySidebar', () => {
  it('forwards composer payloads without changing the public sidebar contract', () => {
    const AssistantComposer = defineComponent({
      name: 'AssistantComposer',
      emits: ['ask-question', 'insert-shortcut', 'update:selectedAiModel'],
      setup() { return () => h('section', { class: 'composer-stub' }) },
    })
    const wrapper = mount(SecondarySidebar, {
      props: { renderMarkdown: (value) => value },
      global: {
        stubs: {
          AssistantComposer,
          AiSkeletonStream: true,
          SvgMaskIcon: true,
        },
      },
    })
    const composer = wrapper.getComponent(AssistantComposer)
    composer.vm.$emit('ask-question')
    composer.vm.$emit('ask-question', '解释重点')
    composer.vm.$emit('insert-shortcut', '总结')
    composer.vm.$emit('update:selectedAiModel', 'deepseek-v4-pro:enabled')
    expect(wrapper.emitted('ask-question')).toEqual([[], ['解释重点']])
    expect(wrapper.emitted('insert-shortcut')).toEqual([['总结']])
    expect(wrapper.emitted('update:selectedAiModel')).toEqual([['deepseek-v4-pro:enabled']])
    wrapper.unmount()
  })

  it('keeps pipeline reasoning separate from manual state and collapses on visible summary text', async () => {
    const AiReasoningPanel = defineComponent({
      name: 'AiReasoningPanel',
      props: ['reasoning', 'expanded', 'pendingAnswer', 'truncated'],
      setup(props) {
        return () => h('div', {
          class: 'reasoning-stub',
          'data-reasoning': props.reasoning,
          'data-expanded': String(props.expanded),
          'data-truncated': String(props.truncated),
        })
      },
    })
    const wrapper = mount(SecondarySidebar, {
      props: {
        renderMarkdown: (value) => value,
        pipelineGeneratingAiSummary: true,
        pipelineGeneratingSummaryReasoning: '自动摘要思考',
        pipelineGeneratingSummaryReasoningTruncated: true,
        pipelineSummaryTaskId: 'task-1',
        generatingSummaryReasoning: '手动摘要思考',
        generatingSummaryReasoningExpanded: true,
      },
      global: {
        stubs: {
          AssistantComposer: true,
          AiReasoningPanel,
          AiSkeletonStream: true,
          SvgMaskIcon: true,
        },
      },
    })

    await nextTick()
    let panel = wrapper.getComponent(AiReasoningPanel)
    expect(panel.props('reasoning')).toBe('自动摘要思考')
    expect(panel.props('expanded')).toBe(true)
    expect(panel.props('truncated')).toBe(true)

    await wrapper.setProps({
      pipelineSummaryTaskId: 'task-2',
      pipelineGeneratingSummaryReasoning: '另一个任务的思考',
    })
    await nextTick()
    panel = wrapper.getComponent(AiReasoningPanel)
    expect(panel.props('reasoning')).toBe('另一个任务的思考')
    expect(panel.props('expanded')).toBe(true)

    await wrapper.setProps({ pipelineGeneratingSummaryText: '自动摘要正文' })
    await nextTick()
    panel = wrapper.getComponent(AiReasoningPanel)
    expect(panel.props('expanded')).toBe(false)

    await wrapper.setProps({
      pipelineGeneratingAiSummary: false,
      generatingAiSummary: true,
      generatingSummaryText: '',
    })
    await nextTick()
    panel = wrapper.getComponent(AiReasoningPanel)
    expect(panel.props('reasoning')).toBe('手动摘要思考')
    expect(panel.props('expanded')).toBe(true)
    wrapper.unmount()
  })
})
