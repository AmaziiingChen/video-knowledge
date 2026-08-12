import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CampusSourceIcon from './CampusSourceIcon.vue'

describe('CampusSourceIcon', () => {
  const sourceSlugs = [
    'gwt', 'sztu', 'sgim', 'ai', 'nmne', 'utl', 'hsee', 'cep', 'cop', 'icoc',
    'future-tech', 'design', 'business', 'sfl', 'music', 'sztu-procurement',
  ]

  it.each([
    ['gwt', '01-公文通'],
    ['ai', '03-人工智能学院'],
    ['music', '14-音乐学院'],
    ['sztu-procurement', 'chineseyuanrenminbisign.bank.building.fill'],
  ])('keeps the reviewed source identity for %s', (sourceSlug, expectedIcon) => {
    const wrapper = mount(CampusSourceIcon, { props: { sourceSlug } })

    expect(wrapper.attributes('data-source-icon')).toBe(sourceSlug)
    expect(wrapper.get('[data-icon]').attributes('data-icon')).toBe(expectedIcon)
    expect(wrapper.attributes('style')).toContain('--source-icon-color:')
  })

  it('gives different sources distinct palettes and a coloured background owner', () => {
    const rendered = sourceSlugs.map((sourceSlug) => (
      mount(CampusSourceIcon, { props: { sourceSlug } })
    ))

    expect(new Set(rendered.map((wrapper) => wrapper.attributes('style'))).size).toBe(sourceSlugs.length)
    expect(new Set(rendered.map((wrapper) => wrapper.get('[data-icon]').attributes('data-icon'))).size)
      .toBe(sourceSlugs.length)
    expect(rendered[0].html()).toContain('campus-source-icon')
  })
})
