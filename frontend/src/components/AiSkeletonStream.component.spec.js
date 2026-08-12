import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AiSkeletonStream from './AiSkeletonStream.vue'

describe('AiSkeletonStream', () => {
  it('renders one accessible shared loading stream with the established line rhythm', () => {
    const wrapper = mount(AiSkeletonStream, {
      props: {
        label: '正在生成 AI 摘要',
        ariaLabel: 'AI 正在生成摘要',
      },
    })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.attributes('aria-label')).toBe('AI 正在生成摘要')
    expect(wrapper.get('.ai-skeleton-stream-label').text()).toBe('正在生成 AI 摘要')
    expect(wrapper.findAll('.ai-skeleton-stream-line')).toHaveLength(4)
    expect(wrapper.findAll('.ai-skeleton-stream-line').map((line) => line.classes())).toEqual([
      ['ai-skeleton-stream-line', 'wide'],
      ['ai-skeleton-stream-line'],
      ['ai-skeleton-stream-line', 'medium'],
      ['ai-skeleton-stream-line', 'short'],
    ])
  })
})
