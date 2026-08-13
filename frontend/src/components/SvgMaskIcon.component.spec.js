import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SvgMaskIcon from './SvgMaskIcon.vue'
import { ArrowLeft, IconX } from './macosSymbolComponents.js'
import { resolveMacosSymbolAssetUrl } from './macosSymbolAssets.js'

describe('SvgMaskIcon', () => {
  it('uses generated native SF Symbol assets for standard workbench icons', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'folder', size: 24 } })

    expect(wrapper.attributes('data-icon')).toBe('folder')
    expect(wrapper.attributes('style')).toContain('--icon-size: 24px')
    expect(wrapper.attributes('style')).toContain('--icon-render-size: 128%')
    expect(wrapper.attributes('style')).toContain('generated/sf-symbols/folder.png')
  })

  it('keeps the reviewed OpenClaw brand asset separate from system symbols', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'openclaw' } })

    expect(wrapper.attributes('data-icon')).toBe('openclaw')
    expect(wrapper.attributes('style')).toContain('--icon-render-size: contain')
    expect(wrapper.attributes('style')).toContain('brand-icons/openclaw.svg')
  })

  it('falls back deterministically when a caller supplies an unknown icon', () => {
    const wrapper = mount(SvgMaskIcon, { props: { src: 'missing-icon' } })

    expect(wrapper.attributes('data-icon')).toBe('text.document')
    expect(wrapper.attributes('style')).toContain('generated/sf-symbols/text.document.png')
  })
})

describe('macOS symbol asset URL', () => {
  it('anchors generated assets at the desktop document instead of the CSS bundle', () => {
    expect(resolveMacosSymbolAssetUrl(
      { kind: 'system', asset: 'folder.png' },
      'knowledgehub://app/index.html',
    )).toBe('knowledgehub://app/generated/sf-symbols/folder.png')
  })

  it('keeps browser previews on their own origin', () => {
    expect(resolveMacosSymbolAssetUrl(
      { kind: 'brand', asset: 'openclaw.svg' },
      'http://127.0.0.1:5173/index.html',
    )).toBe('http://127.0.0.1:5173/brand-icons/openclaw.svg')
  })
})

describe('macOS symbol component facade', () => {
  it('projects fixed symbol names while keeping the approved Tabler close glyph', () => {
    expect(mount(ArrowLeft).find('[data-icon="arrow.left"]').exists()).toBe(true)
    const close = mount(IconX, { attrs: { size: 20 } })
    expect(close.classes()).toContain('tabler-icon-x')
    expect(close.attributes('width')).toBe('20')
  })
})
