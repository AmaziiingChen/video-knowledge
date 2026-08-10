import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import LocalFileReaderSurface from './LocalFileReaderSurface.vue'

const wrappers = []

function mountReader(props) {
  const wrapper = mount(LocalFileReaderSurface, { props })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('LocalFileReaderSurface', () => {
  it('renders the resolved PDF original with the existing title contract', () => {
    const wrapper = mountReader({
      mode: 'pdf',
      content: { title: '研究资料' },
      originalUrl: 'http://127.0.0.1:8000/api/media?path=source.pdf',
    })

    const frame = wrapper.get('iframe')
    expect(frame.attributes('src')).toBe('http://127.0.0.1:8000/api/media?path=source.pdf')
    expect(frame.attributes('title')).toBe('研究资料原件')
    expect(wrapper.find('.local-file-loading').exists()).toBe(false)
  })

  it('keeps the PDF loading copy when the resolved original is not ready', () => {
    const wrapper = mountReader({ mode: 'pdf', originalUrl: '' })

    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.get('.local-file-loading').text()).toBe('正在打开 PDF 原件…')
  })

  it('renders an image original without inventing a missing-image state', async () => {
    const wrapper = mountReader({
      mode: 'image',
      content: { title: '扫描页' },
      originalUrl: 'http://127.0.0.1:8000/api/media?path=scan.png',
    })

    const image = wrapper.get('img')
    expect(image.attributes('src')).toBe('http://127.0.0.1:8000/api/media?path=scan.png')
    expect(image.attributes('alt')).toBe('扫描页')

    await wrapper.setProps({ originalUrl: '' })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('.local-file-loading').exists()).toBe(false)
    expect(wrapper.find('.image-reader-figure').exists()).toBe(true)
  })
})
