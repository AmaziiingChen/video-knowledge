import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SvgMaskIcon from './SvgMaskIcon.vue'
import { ArrowLeft, IconX } from './macosSymbolComponents.js'

describe('SvgMaskIcon', () => {
  it('uses generated native SF Symbol assets for standard workbench icons', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'folder', size: 24 } })

    expect(wrapper.attributes('data-icon')).toBe('folder')
    expect(wrapper.attributes('style')).toContain('--icon-size: 24px')
    expect(wrapper.attributes('style')).toContain('generated/sf-symbols/folder.png')
  })

  it('keeps the reviewed OpenClaw brand asset separate from system symbols', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'openclaw' } })

    expect(wrapper.attributes('data-icon')).toBe('openclaw')
    expect(wrapper.attributes('style')).toContain('brand-icons/openclaw.svg')
  })

  it('falls back deterministically when a caller supplies an unknown icon', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'missing-icon' } })

    expect(wrapper.attributes('data-icon')).toBe('text.document')
    expect(wrapper.attributes('style')).toContain('generated/sf-symbols/text.document.png')
  })
})

describe('macOS symbol component facade', () => {
  it('projects fixed symbol names for Element Plus icon slots', () => {
    expect(mount(ArrowLeft).find('[data-icon="arrow.left"]').exists()).toBe(true)
    expect(mount(IconX, { attrs: { size: 20 } }).find('[data-icon="xmark"]').attributes('style'))
      .toContain('--icon-size: 20px')
  })
})
