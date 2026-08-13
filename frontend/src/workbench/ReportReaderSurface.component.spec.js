import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReportReaderSurface from './ReportReaderSurface.vue'

const ReportCoverPreviewStub = defineComponent({
  name: 'ReportCoverPreview',
  props: ['contentItemId', 'title', 'coverUrl', 'history', 'generating', 'switching'],
  emits: ['select'],
  template: '<button class="cover-stub" @click="$emit(\'select\', { contentItemId, coverId: \'cover-2\' })">封面</button>',
})

const ReportOutlineRailStub = defineComponent({
  name: 'ReportOutlineRail',
  props: ['scrollRoot', 'contentRoot', 'contentVersion', 'reportKey'],
  template: '<div class="outline-stub"></div>',
})

const wrappers = []

function mountSurface(props = {}) {
  const wrapper = mount(ReportReaderSurface, {
    props: {
      mode: 'report',
      tab: { id: 'report:one', title: '标签标题' },
      content: { id: 'content:one', title: '原始标题', cover_url: '/cover.png' },
      markdownHtml: '<h2 data-markdown-heading="1">正文标题</h2><p>正文</p>',
      sourceStats: { analyzed: 8, referenced: 3 },
      reportDisplayTitle: '每周观察周报',
      reportDateLabel: '2026年8月4日—8月10日',
      reportGeneratedLabel: '生成于 2026年8月10日 18:30',
      coverHistory: { active_cover_id: 'cover-1', covers: [] },
      formatDateTime: (value) => `时间:${value}`,
      ...props,
    },
    global: {
      stubs: {
        ElIcon: true,
        ReportCoverPreview: ReportCoverPreviewStub,
        ReportOutlineRail: ReportOutlineRailStub,
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.restoreAllMocks()
})

describe('ReportReaderSurface', () => {
  it('renders report metadata, bridges cover selection, outline roots and reading scroll', async () => {
    const wrapper = mountSurface()
    await wrapper.vm.$nextTick()
    const reader = wrapper.get('.report-reader').element
    const markdown = wrapper.get('.report-markdown').element

    expect(wrapper.get('h2').text()).toBe('每周观察周报')
    expect(wrapper.text()).toContain('分析 8 篇文章')
    expect(wrapper.text()).toContain('正文引用 3 篇文章')
    expect(wrapper.get('.report-markdown').html()).toContain('正文标题')
    expect(wrapper.vm.getScrollRoot()).toBe(reader)
    expect(wrapper.vm.getContentRoot()).toBe(markdown)

    const outline = wrapper.getComponent(ReportOutlineRailStub)
    expect(outline.props('scrollRoot')).toBe(reader)
    expect(outline.props('contentRoot')).toBe(markdown)
    expect(outline.props('reportKey')).toBe('report:one')
    expect(outline.props('contentVersion')).toContain('正文标题')

    await wrapper.get('.cover-stub').trigger('click')
    expect(wrapper.emitted('select-cover')).toEqual([
      [{ contentItemId: 'content:one', coverId: 'cover-2' }],
    ])
    await wrapper.get('.report-reader').trigger('scroll')
    expect(wrapper.emitted('scroll')?.[0]?.[0].target).toBe(reader)
  })

  it('preserves capture metadata and its loading state', () => {
    const wrapper = mountSurface({
      mode: 'capture',
      content: {
        title: '校园动态',
        source_name: '校园论坛',
        source_section: '通知公告',
        published_at: '2026-08-10T10:00:00+08:00',
      },
      markdownHtml: '',
    })

    expect(wrapper.get('.capture-reader-kicker').text()).toBe('小程序采集')
    expect(wrapper.get('h2').text()).toBe('校园动态')
    expect(wrapper.text()).toContain('通知公告')
    expect(wrapper.text()).toContain('采集于 时间:2026-08-10T10:00:00+08:00')
    expect(wrapper.text()).toContain('正在载入采集记录…')
    expect(wrapper.find('.cover-stub').exists()).toBe(false)
  })

  it('keeps imported Markdown metadata and its dedicated loading state', () => {
    const wrapper = mountSurface({
      mode: 'markdown',
      content: { title: '外部研究笔记', created_at: '2026-08-09T09:00:00+08:00' },
      markdownHtml: '',
      externalImportKindLabel: 'Markdown 文档',
    })

    expect(wrapper.get('h2').text()).toBe('外部研究笔记')
    expect(wrapper.text()).toContain('外部导入')
    expect(wrapper.text()).toContain('Markdown 文档')
    expect(wrapper.text()).toContain('导入于 时间:2026-08-09T09:00:00+08:00')
    expect(wrapper.text()).toContain('正在载入 Markdown 内容…')
    expect(wrapper.find('.cover-stub').exists()).toBe(false)
  })

  it('owns footnote return state and exposes the original focus behavior', async () => {
    const wrapper = mountSurface({
      markdownHtml: '<p><sup class="markdown-footnote-ref"><a href="#fn-1">1</a></sup></p><p id="fn-1">注释</p>',
    })
    const reader = wrapper.get('.report-reader').element
    const footnote = wrapper.get('#fn-1').element
    const scrollIntoView = vi.fn()
    const scrollTo = vi.fn()
    const focus = vi.fn()
    footnote.scrollIntoView = scrollIntoView
    reader.scrollTo = scrollTo
    reader.focus = focus
    reader.scrollTop = 64
    window.matchMedia = vi.fn(() => ({ matches: false }))

    await wrapper.get('.markdown-footnote-ref a').trigger('click', { button: 0 })
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start', inline: 'nearest' })
    expect(wrapper.get('[aria-label="返回引用位置"]').exists()).toBe(true)

    await wrapper.get('[aria-label="返回引用位置"]').trigger('click')
    expect(scrollTo).toHaveBeenCalledWith({ top: 64, behavior: 'smooth' })
    expect(wrapper.find('[aria-label="返回引用位置"]').exists()).toBe(false)

    expect(wrapper.vm.focusReader()).toBe(true)
    expect(focus).toHaveBeenCalledWith({ preventScroll: true })
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: 'smooth' })
  })
})
