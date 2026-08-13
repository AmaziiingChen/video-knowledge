import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AiReasoningPanel from './AiReasoningPanel.vue'
import KnowledgeWorkspace from '../knowledge/KnowledgeWorkspace.vue'

describe('AI response envelope UI', () => {
  it('renders reasoning through the supplied sanitized Markdown boundary', async () => {
    const calls = []
    const wrapper = mount(AiReasoningPanel, {
      props: {
        reasoning: '**核对依据**',
        expanded: true,
        pendingAnswer: false,
        renderMarkdown(value) {
          calls.push(value)
          return '<strong>核对依据</strong>'
        },
      },
    })
    expect(wrapper.text()).toContain('思考过程')
    expect(wrapper.html()).toContain('<strong>核对依据</strong>')
    expect(calls).toEqual(['**核对依据**'])
    await wrapper.find('details').trigger('toggle')
    expect(wrapper.emitted('update:expanded')).toBeTruthy()
  })

  it('does not let an old Knowledge EOF overwrite the newly selected scope', async () => {
    let streamController
    const responseBody = new ReadableStream({
      start(controller) {
        streamController = controller
      },
    })
    const originalFetch = globalThis.fetch
    globalThis.fetch = async () => new Response(responseBody, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })

    try {
      const wrapper = mount(KnowledgeWorkspace, {
        global: {
          stubs: {
            'el-icon': true,
            'el-option': true,
            'el-select': true,
            'el-tooltip': { template: '<div><slot /></div>' },
            SvgMaskIcon: true,
          },
        },
      })
      wrapper.vm.setKnowledgeScope({ provider: 'rss', name: '旧知识集', selectable: true })
      await wrapper.find('textarea').setValue('旧问题')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const done = {
        answer: '旧回答',
        citations: [],
        reasoning_content: '旧思考',
        suggested_questions: ['旧建议？'],
        conversation_id: 'old-conversation',
        usage: { call_count: 9 },
      }
      streamController.enqueue(new TextEncoder().encode(`event: done\ndata: ${JSON.stringify(done)}\n\n`))
      await flushPromises()
      wrapper.vm.setKnowledgeScope({ provider: 'rss', name: '新知识集', selectable: true })
      streamController.close()
      await flushPromises()
      await flushPromises()

      expect(wrapper.emitted('conversation-activated') || []).not.toContainEqual(['old-conversation'])
      expect(wrapper.emitted('conversation-usage-changed') || []).not.toContainEqual([
        expect.objectContaining({ call_count: 9 }),
      ])
      wrapper.unmount()
    } finally {
      globalThis.fetch = originalFetch
    }
  })
})
