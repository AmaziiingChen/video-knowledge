import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import ArticleReaderSurface from './ArticleReaderSurface.vue'

const ReportOutlineRailStub = defineComponent({
  name: 'ReportOutlineRail',
  props: ['scrollRoot', 'contentRoot', 'contentVersion', 'reportKey'],
  template: '<div class="outline-stub"></div>',
})

const wrappers = []

function mountReader(props = {}) {
  const wrapper = mount(ArticleReaderSurface, {
    props: {
      tab: { id: 'article:one', title: '标签标题' },
      content: {
        id: 'content:one', title: '文章标题', source_name: '来源',
        source_section: '栏目', published_at: '2026-08-10',
      },
      preview: { html: '<h2>章节</h2>', published_at: '2026-08-11' },
      articleHtml: '<h2>章节</h2>',
      articleText: '正文',
      sourceLabel: '来源类型',
      attachments: [{ url: '/attachment.pdf', name: '附件.pdf', download_type: 'direct' }],
      ...props,
    },
    global: { stubs: { ReportOutlineRail: ReportOutlineRailStub } },
  })
  wrappers.push(wrapper)
  return wrapper
}

function installFrameDocument(iframe, html) {
  const frameDocument = document.implementation.createHTMLDocument('文章预览')
  frameDocument.body.innerHTML = html
  Object.defineProperty(iframe.element, 'contentDocument', {
    configurable: true,
    value: frameDocument,
  })
  return frameDocument
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('ArticleReaderSurface', () => {
  it('renders snapshot metadata, bridges the frame and opens attachments', async () => {
    const wrapper = mountReader()
    const iframe = wrapper.get('iframe')
    const frameDocument = installFrameDocument(iframe, '<h2>章节</h2>')
    await iframe.trigger('load')
    await wrapper.vm.$nextTick()

    expect(wrapper.get('h2').text()).toBe('文章标题')
    expect(wrapper.text()).toContain('来源')
    expect(wrapper.text()).toContain('栏目')
    expect(wrapper.text()).toContain('2026-08-11')
    expect(wrapper.vm.getPreviewFrame()).toBe(iframe.element)
    expect(wrapper.emitted('preview-frame-ready')?.[0]?.[0]).toBe(frameDocument)
    const outline = wrapper.getComponent(ReportOutlineRailStub)
    expect(outline.props('scrollRoot')).toBe(iframe.element)
    expect(outline.props('contentRoot')).toBe(frameDocument.body)

    await wrapper.get('.article-attachment-row').trigger('click')
    expect(wrapper.emitted('open-campus-attachment')).toEqual([
      [{ url: '/attachment.pdf', name: '附件.pdf', download_type: 'direct' }],
    ])
  })

  it('keeps remote status, hidden-frame and external-link event contracts', async () => {
    const wrapper = mountReader({
      wechatArticle: true,
      remoteStatus: 'failed',
      remoteVisible: true,
      localHtmlRemoteVisible: true,
    })
    const iframe = wrapper.get('iframe')
    const frameDocument = installFrameDocument(iframe, '<a href="https://example.com/article">原文</a>')
    await iframe.trigger('load')
    frameDocument.querySelector('a').dispatchEvent(new MouseEvent('click', { button: 0, bubbles: true, cancelable: true }))

    expect(wrapper.text()).toContain('原页面未加载，正在显示缓存正文')
    expect(iframe.classes()).toContain('is-hidden')
    expect(wrapper.findComponent(ReportOutlineRailStub).exists()).toBe(false)
    expect(wrapper.emitted('open-external-link')).toEqual([['https://example.com/article']])
  })

  it('preserves campus loading, silent loading and metadata-only fallbacks', async () => {
    const visibleLoading = mountReader({
      preview: { loading: true, showLoader: true, loading_label: '正在读取校园正文…' },
      articleHtml: '',
      articleText: '',
      attachments: [],
    })
    expect(visibleLoading.get('.campus-article-loading').text()).toContain('正在读取校园正文…')

    const loading = mountReader({
      preview: { loading: true, formatting_status: 'queued', loading_label: '正在读取校园正文…' },
      articleHtml: '',
      articleText: '',
      attachments: [],
    })
    expect(loading.text()).toContain('正在整理 OCR 文档版式…')
    expect(loading.find('.article-preview-silent-loading').exists()).toBe(true)

    await loading.setProps({
      preview: { loading: false },
      isCampus: true,
    })
    expect(loading.get('.campus-article-placeholder').text()).toContain('文章元数据已保存')
  })
})
