import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import LibraryContextMenu from './LibraryContextMenu.vue'

const wrappers = []

function mountMenu(menu) {
  const host = document.createElement('div')
  document.body.append(host)
  const wrapper = mount(LibraryContextMenu, {
    attachTo: host,
    props: { menu },
    global: { stubs: { Teleport: true } },
  })
  wrappers.push({ wrapper, host })
  return wrapper
}

function itemByText(wrapper, text) {
  return wrapper.findAll('[role="menuitem"]').find((button) => button.text().includes(text))
}

afterEach(() => {
  wrappers.splice(0).forEach(({ wrapper, host }) => {
    wrapper.unmount()
    host.remove()
  })
  document.body.replaceChildren()
})

describe('LibraryContextMenu', () => {
  it('stays inert while closed and can open without remounting', async () => {
    const wrapper = mountMenu(null)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    window.dispatchEvent(new PointerEvent('pointerdown'))
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)

    await wrapper.setProps({ menu: { kind: 'blank', x: 24, y: 24, node: null } })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="menu"]').attributes('style')).toContain('left: 24px')
  })

  it('emits the selected read state for a content item', async () => {
    const wrapper = mountMenu({
      kind: 'node',
      x: 20,
      y: 20,
      node: { id: 'item-1', type: 'content', name: '测试文章', raw: {} },
    })

    const unreadButton = itemByText(wrapper, '标记为未读')
    expect(unreadButton).toBeTruthy()

    await unreadButton.trigger('click')
    await itemByText(wrapper, '标记为已读').trigger('click')
    await itemByText(wrapper, '在 Finder 中显示').trigger('click')
    await itemByText(wrapper, '编辑文件名').trigger('click')
    await itemByText(wrapper, '删除文件').trigger('click')

    expect(wrapper.emitted('select').map(([event]) => event)).toEqual([
      { id: 'set-viewed', payload: false },
      { id: 'set-viewed', payload: true },
      { id: 'reveal', payload: null },
      { id: 'rename', payload: null },
      { id: 'delete', payload: null },
    ])
  })

  it('supports keyboard navigation and restores focus intent on Escape', async () => {
    const wrapper = mountMenu({
      kind: 'node',
      x: 20,
      y: 20,
      node: { id: 'folder-1', type: 'folder', name: '资料夹', raw: { is_pinned: false } },
    })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('[role="menuitem"]')
    items[0].element.focus()
    expect(document.activeElement).toBe(items[0].element)

    await items[0].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items[1].element)

    await items[1].trigger('keydown', { key: 'End' })
    expect(document.activeElement).toBe(items.at(-1).element)
    await items.at(-1).trigger('keydown', { key: 'Home' })
    expect(document.activeElement).toBe(items[0].element)
    await items[0].trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(items.at(-1).element)

    await itemByText(wrapper, '置顶文件夹').trigger('click')
    expect(wrapper.emitted('select').at(-1)).toEqual([{ id: 'toggle-pin', payload: null }])

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toEqual([[{ restoreFocus: true }]])

    await items[0].trigger('keydown', { key: 'Tab' })
    window.dispatchEvent(new PointerEvent('pointerdown'))
    expect(wrapper.emitted('close')).toEqual([
      [{ restoreFocus: true }],
      [{ restoreFocus: true }],
      [{ restoreFocus: false }],
    ])

    await wrapper.setProps({
      menu: { kind: 'node', x: 48, y: 64, node: { id: 'folder-2', type: 'folder', name: '新资料夹', raw: {} } },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[role="menu"]').attributes('style')).toContain('left: 48px')
  })

  it('keeps the blank-area action limited to creating a separator', () => {
    const wrapper = mountMenu({ kind: 'blank', x: 20, y: 20, node: null })
    const actions = wrapper.findAll('[role="menuitem"]')

    expect(actions).toHaveLength(1)
    expect(actions[0].text()).toContain('新建分割线')
    actions[0].element.click()
    expect(wrapper.emitted('select')).toEqual([[
      { id: 'create-separator', payload: null },
    ]])
  })

  it('offers only deletion for a user-created separator', async () => {
    const wrapper = mountMenu({
      kind: 'user-group-separator',
      x: 20,
      y: 20,
      node: { id: 'separator-1', type: 'user-group-separator', name: '分割线', raw: {} },
    })

    const actions = wrapper.findAll('[role="menuitem"]')
    expect(actions).toHaveLength(1)
    expect(actions[0].text()).toContain('删除分割线')
    await actions[0].trigger('click')
    expect(wrapper.emitted('select')).toEqual([[
      { id: 'delete-separator', payload: null },
    ]])
  })
})
