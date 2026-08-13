import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import PrimarySidebar from './PrimarySidebar.vue'

function mountSidebar(activeView = 'library') {
  const focusLibrarySearch = vi.fn()
  const showLibrarySearch = vi.fn()
  const showLibraryFiles = vi.fn()
  const LibrarySidebar = defineComponent({
    name: 'LibrarySidebar',
    props: { active: Boolean },
    emits: ['open-content', 'update:searchQuery'],
    setup(props, { expose }) {
      expose({ focusLibrarySearch, showLibrarySearch, showLibraryFiles })
      return () => h('div', { class: 'library-stub', 'data-active': String(props.active) })
    },
  })
  const PromptFileTree = defineComponent({
    name: 'PromptFileTree',
    emits: ['open-prompt', 'load-trash'],
    setup() {
      return () => h('div', { class: 'prompt-stub' })
    },
  })
  const wrapper = mount(PrimarySidebar, {
    props: { activeView },
    global: { stubs: { LibrarySidebar, PromptFileTree } },
  })
  return { wrapper, LibrarySidebar, PromptFileTree, focusLibrarySearch, showLibrarySearch, showLibraryFiles }
}

describe('PrimarySidebar', () => {
  it('routes views without recreating the long-lived library owner', async () => {
    const state = mountSidebar()
    const libraryInstance = state.wrapper.getComponent(state.LibrarySidebar).vm
    expect(state.wrapper.get('.library-stub').attributes('data-active')).toBe('true')
    expect(state.wrapper.find('.prompt-stub').exists()).toBe(false)

    await state.wrapper.setProps({ activeView: 'prompts' })
    expect(state.wrapper.getComponent(state.LibrarySidebar).vm).toBe(libraryInstance)
    expect(state.wrapper.get('.library-stub').attributes('data-active')).toBe('false')
    expect(state.wrapper.find('.prompt-stub').exists()).toBe(true)
    expect(state.wrapper.get('aside').classes()).toContain('prompt-sidebar')

    await state.wrapper.setProps({ activeView: 'future-workspace' })
    expect(state.wrapper.getComponent(state.LibrarySidebar).vm).toBe(libraryInstance)
    expect(state.wrapper.find('.prompt-stub').exists()).toBe(false)
    expect(state.wrapper.get('aside').classes()).toEqual(['file-sidebar'])
  })

  it('proxies library focus methods and re-emits both sidebar event families', async () => {
    const state = mountSidebar()
    state.wrapper.vm.focusLibrarySearch()
    state.wrapper.vm.showLibrarySearch()
    state.wrapper.vm.showLibraryFiles()
    expect(state.focusLibrarySearch).toHaveBeenCalledOnce()
    expect(state.showLibrarySearch).toHaveBeenCalledOnce()
    expect(state.showLibraryFiles).toHaveBeenCalledOnce()

    const library = state.wrapper.getComponent(state.LibrarySidebar)
    library.vm.$emit('open-content', { id: 'content-1' })
    library.vm.$emit('update:searchQuery', '搜索词')
    expect(state.wrapper.emitted('open-content')).toEqual([[{ id: 'content-1' }]])
    expect(state.wrapper.emitted('update:searchQuery')).toEqual([['搜索词']])

    await state.wrapper.setProps({ activeView: 'prompts' })
    const prompt = state.wrapper.getComponent(state.PromptFileTree)
    prompt.vm.$emit('open-prompt', { kind: 'report', prompt: { id: 'report-1' } })
    prompt.vm.$emit('load-trash')
    expect(state.wrapper.emitted('open-prompt')).toEqual([[
      { kind: 'report', prompt: { id: 'report-1' } },
    ]])
    expect(state.wrapper.emitted('load-prompt-trash')).toEqual([[]])
  })
})
