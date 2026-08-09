import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ReportCoverPreview from './ReportCoverPreview.vue'

const history = {
  active_cover_id: 'cover-2',
  covers: [
    { id: 'cover-1', url: 'file:///cover-1.png' },
    { id: 'cover-2', url: 'file:///cover-2.png' },
    { id: 'cover-3', url: 'file:///cover-3.png' },
  ],
}

const wrappers = []

function mountPreview(props = {}) {
  const wrapper = mount(ReportCoverPreview, {
    props: {
      contentItemId: 'report-1',
      title: '每周报告',
      coverUrl: 'file:///fallback.png',
      history,
      ...props,
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('ReportCoverPreview', () => {
  it('renders the active cover and emits an adjacent cover selection', async () => {
    const wrapper = mountPreview()

    expect(wrapper.get('img').attributes('src')).toBe('file:///cover-2.png')
    expect(wrapper.get('img').attributes('alt')).toBe('每周报告封面')
    expect(wrapper.get('.report-cover-count').text()).toBe('2 / 3')

    await wrapper.get('[aria-label="下一张封面"]').trigger('click')
    await wrapper.get('[aria-label="上一张封面"]').trigger('click')

    expect(wrapper.emitted('select')).toEqual([
      [{ contentItemId: 'report-1', coverId: 'cover-3' }],
      [{ contentItemId: 'report-1', coverId: 'cover-1' }],
    ])
  })

  it('keeps the current cover visible and disables navigation while busy', () => {
    const wrapper = mountPreview({ generating: true, switching: true })

    expect(wrapper.get('figure').attributes('aria-busy')).toBe('true')
    expect(wrapper.get('img').attributes('src')).toBe('file:///cover-2.png')
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('当前图片会保留到新版本完成')
  })

  it('exposes a status message before the first cover is available', () => {
    const wrapper = mountPreview({ coverUrl: '', history: { active_cover_id: '', covers: [] }, generating: true })

    expect(wrapper.get('[role="status"]').text()).toContain('正在生成公众号封面')
    expect(wrapper.find('img').exists()).toBe(false)
  })
})
