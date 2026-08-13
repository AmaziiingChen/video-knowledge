import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import MediaTranscriptSurface from './MediaTranscriptSurface.vue'

const wrappers = []
const segments = [
  { position: 1, start_seconds: 5, text: '第一段', approximate: true },
  { position: 2, start_seconds: 65.2, text: '第二段', approximate: false },
]

function mountSurface(props = {}) {
  const wrapper = mount(MediaTranscriptSurface, {
    props: {
      height: 56,
      bounds: { min: 25.4, max: 74.6 },
      segmentActive: (segment) => segment.position === 2,
      ...props,
    },
    global: { stubs: { 'el-icon': true } },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('MediaTranscriptSurface', () => {
  it('renders the bounded splitter and forwards resize gestures', async () => {
    const wrapper = mountSurface({ segments })
    const splitter = wrapper.get('.media-transcript-splitter')

    expect(splitter.attributes('aria-valuemin')).toBe('25')
    expect(splitter.attributes('aria-valuemax')).toBe('75')
    expect(splitter.attributes('aria-valuenow')).toBe('56')

    await splitter.trigger('pointerdown', { pointerId: 4 })
    await splitter.trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('resize-start')).toHaveLength(1)
    expect(wrapper.emitted('resize-keydown')).toHaveLength(1)
  })

  it('keeps the task generation state truthful and non-interactive', () => {
    const wrapper = mountSurface({
      generating: true,
      generationLabel: '正在识别字幕',
      generationDescription: '音频可继续播放',
      segments,
      autoFollow: false,
    })

    expect(wrapper.get('.transcript-timeline').attributes('aria-busy')).toBe('true')
    expect(wrapper.get('.transcript-generation').text()).toContain('正在识别字幕')
    expect(wrapper.get('.transcript-generation').text()).toContain('音频可继续播放')
    expect(wrapper.findAll('.transcript-generation-line')).toHaveLength(4)
    expect(wrapper.find('.timeline-segment').exists()).toBe(false)
    expect(wrapper.find('.transcript-follow-button').exists()).toBe(false)
  })

  it('renders active and approximate segments and forwards seek intent', async () => {
    const wrapper = mountSurface({ segments, autoFollow: false })
    const rows = wrapper.findAll('.timeline-segment')

    expect(rows).toHaveLength(2)
    expect(rows[0].classes()).toContain('approximate')
    expect(rows[1].classes()).toContain('is-active')
    expect(rows[1].attributes('data-start-seconds')).toBe('65.2')
    expect(rows[1].get('.timeline-time').text()).toBe('01:05')

    await rows[1].trigger('click')
    expect(wrapper.emitted('select-segment')).toEqual([[segments[1]]])
    await wrapper.get('.transcript-follow-button').trigger('click')
    expect(wrapper.emitted('resume-auto-follow')).toHaveLength(1)
  })

  it('forwards auto-follow pauses and releases every segment ref', async () => {
    const wrapper = mountSurface({ segments })
    const refsAfterMount = wrapper.emitted('segment-ref') || []
    expect(refsAfterMount).toHaveLength(2)
    expect(refsAfterMount[0][0].segment).toStrictEqual(segments[0])
    expect(refsAfterMount[0][0].element).toBeInstanceOf(HTMLElement)

    await wrapper.get('.transcript-timeline').trigger('wheel')
    await wrapper.get('.transcript-timeline').trigger('touchstart')
    expect(wrapper.emitted('pause-auto-follow')).toHaveLength(2)

    await wrapper.setProps({ segments: [] })
    const releasedRefs = (wrapper.emitted('segment-ref') || []).slice(2)
    expect(releasedRefs).toHaveLength(2)
    expect(releasedRefs.every(([payload]) => payload.element === null)).toBe(true)
  })
})
