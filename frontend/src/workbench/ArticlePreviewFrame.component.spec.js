import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ArticlePreviewFrame from './ArticlePreviewFrame.vue'

const wrappers = []

function mountFrame(props = {}) {
  const wrapper = mount(ArticlePreviewFrame, {
    props: {
      srcdoc: '<p>正文</p>',
      title: '文章正文快照',
      ...props,
    },
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

describe('ArticlePreviewFrame', () => {
  it('keeps the sandbox boundary and initializes safe MathML and find styles', async () => {
    const wrapper = mountFrame({ hidden: true, localHtmlOriginal: true })
    const iframe = wrapper.get('iframe')
    const frame = iframe.element
    const frameDocument = installFrameDocument(iframe, '<span class="article-math" data-latex="x^2"></span>')

    await iframe.trigger('load')

    expect(iframe.attributes('sandbox')).toBe('allow-same-origin')
    expect(iframe.attributes('referrerpolicy')).toBe('no-referrer')
    expect(iframe.classes()).toContain('is-hidden')
    expect(iframe.classes()).toContain('local-html-original-frame')
    expect(wrapper.vm.getFrame()).toBe(frame)
    expect(wrapper.emitted('ready')?.[0]?.[0]).toBe(frameDocument)
    expect(frameDocument.querySelector('.article-math')?.dataset.rendered).toBe('true')
    expect(frameDocument.getElementById('knowledgehub-preview-find-styles')).not.toBeNull()
  })

  it('opens only http(s) links and owns the iframe find shortcut', async () => {
    const wrapper = mountFrame()
    const iframe = wrapper.get('iframe')
    const frameDocument = installFrameDocument(iframe, `
      <a id="external" href="https://example.com/path">外链</a>
      <a id="mail" href="mailto:test@example.com">邮件</a>
    `)
    await iframe.trigger('load')

    const externalClick = new MouseEvent('click', { button: 0, bubbles: true, cancelable: true })
    frameDocument.getElementById('external').dispatchEvent(externalClick)
    frameDocument.getElementById('mail').dispatchEvent(new MouseEvent('click', { button: 0, bubbles: true, cancelable: true }))
    frameDocument.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'f', metaKey: true, bubbles: true, cancelable: true,
    }))

    expect(externalClick.defaultPrevented).toBe(true)
    expect(wrapper.emitted('open-external-link')).toEqual([['https://example.com/path']])
    expect(wrapper.emitted('open-find')).toHaveLength(1)
  })
})
