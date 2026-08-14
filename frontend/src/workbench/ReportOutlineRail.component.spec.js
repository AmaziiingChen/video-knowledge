import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ReportOutlineRail from './ReportOutlineRail.vue'

const wrappers = []
const roots = []

function rectangle({ left = 180, top = 40, width = 360, height = 640 } = {}) {
  return {
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    x: left,
    y: top,
    toJSON: () => ({}),
  }
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
})

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  roots.splice(0).forEach((root) => root.remove())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ReportOutlineRail', () => {
  it('shows two internal-browser entries at the minimum rail height on a narrow reader', async () => {
    const scrollRoot = document.createElement('div')
    scrollRoot.getBoundingClientRect = () => rectangle()
    document.body.appendChild(scrollRoot)
    roots.push(scrollRoot)

    const wrapper = mount(ReportOutlineRail, {
      props: {
        scrollRoot,
        remoteEntries: [
          { id: 'first', text: '第一节', level: 2 },
          { id: 'second', text: '第二节', level: 2 },
        ],
        remoteActiveId: 'first',
      },
    })
    wrappers.push(wrapper)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const rail = document.body.querySelector('.report-outline-rail')
    expect(rail).not.toBeNull()
    expect(rail.style.getPropertyValue('--report-outline-rail-height')).toBe('64px')
    expect(rail.querySelectorAll('.report-outline-rail-item')).toHaveLength(2)
  })

  it('keeps a local outline hidden when the text gutter is too small', async () => {
    const scrollRoot = document.createElement('div')
    const contentRoot = document.createElement('div')
    scrollRoot.appendChild(contentRoot)
    scrollRoot.getBoundingClientRect = () => rectangle({ left: 100, width: 900 })
    contentRoot.getBoundingClientRect = () => rectangle({ left: 150, width: 800 })
    contentRoot.innerHTML = '<h2>第一节</h2><h2>第二节</h2><h2>第三节</h2><h2>第四节</h2>'
    document.body.appendChild(scrollRoot)
    roots.push(scrollRoot)

    const wrapper = mount(ReportOutlineRail, {
      props: { scrollRoot, contentRoot },
    })
    wrappers.push(wrapper)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(document.body.querySelector('.report-outline-rail')).toBeNull()
  })
})
