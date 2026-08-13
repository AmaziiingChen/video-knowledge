import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import LibrarySidebar from './LibrarySidebar.vue'

const wrappers = []

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  localStorage.clear()
  document.body.replaceChildren()
})

describe('LibrarySidebar', () => {
  it('keeps its owner mounted while removing inactive library DOM', async () => {
    const wrapper = mount(LibrarySidebar, {
      props: { active: false },
      global: {
        stubs: {
          Teleport: true,
          'el-tooltip': { template: '<span><slot /></span>' },
          'el-icon': { template: '<span><slot /></span>' },
          'el-input': { template: '<input />' },
        },
      },
    })
    wrappers.push(wrapper)

    expect(wrapper.find('.sidebar-tool-stack').exists()).toBe(false)
    await wrapper.setProps({ active: true })
    expect(wrapper.find('.sidebar-tool-stack').exists()).toBe(true)
  })
})
