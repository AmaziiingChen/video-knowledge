import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PanelToggleIcon from './PanelToggleIcon.vue'
import panelSource from './PanelToggleIcon.vue?raw'
import ProcessLogToggleIcon from './ProcessLogToggleIcon.vue'
import processLogSource from './ProcessLogToggleIcon.vue?raw'

describe('workspace panel toggle icons', () => {
  it('renders mirrored side ownership and a distinct collapsed state', async () => {
    const left = mount(PanelToggleIcon, {
      props: { side: 'left', collapsed: false },
    })
    const right = mount(PanelToggleIcon, {
      props: { side: 'right', collapsed: false },
    })

    expect(left.get('.panel-toggle-icon').classes()).toContain('is-left')
    expect(right.get('.panel-toggle-icon').classes()).toContain('is-right')
    expect(left.get('.panel-toggle-icon-fill').attributes('d')).toBe('M3 4h6v12H3z')
    expect(right.get('.panel-toggle-icon-fill').attributes('d')).toBe('M11 4h6v12h-6z')
    expect(left.get('.panel-toggle-icon').classes()).not.toContain('is-collapsed')

    await left.setProps({ collapsed: true })

    expect(left.get('.panel-toggle-icon').classes()).toContain('is-collapsed')
  })

  it('renders a distinct bottom log collapsed state', async () => {
    const wrapper = mount(ProcessLogToggleIcon, {
      props: { collapsed: false },
    })

    expect(wrapper.get('.process-log-toggle-icon').classes()).not.toContain('is-collapsed')
    expect(wrapper.get('.process-log-toggle-icon-fill').attributes('d')).toBe('M3 11h14v5H3z')

    await wrapper.setProps({ collapsed: true })

    expect(wrapper.get('.process-log-toggle-icon').classes()).toContain('is-collapsed')
  })

  it('keeps the panel transitions and reduced-motion fallback', () => {
    expect(panelSource).toMatch(/transition:\s*transform var\(--vk-motion-panel\) var\(--vk-ease-out\)/)
    expect(panelSource).toMatch(/is-collapsed \.panel-toggle-icon-fill[\s\S]*?scaleX\(0\.22\)/)
    expect(processLogSource).toMatch(/transition:\s*transform var\(--vk-motion-panel\) var\(--vk-ease-out\)/)
    expect(processLogSource).toMatch(/is-collapsed \.process-log-toggle-icon-fill[\s\S]*?scaleY\(0\.22\)/)
    expect(panelSource).toMatch(/prefers-reduced-motion:\s*reduce[\s\S]*?transition:\s*none/)
    expect(processLogSource).toMatch(/prefers-reduced-motion:\s*reduce[\s\S]*?transition:\s*none/)
  })
})
