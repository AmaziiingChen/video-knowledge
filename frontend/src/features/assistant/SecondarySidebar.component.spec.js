import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
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
})
