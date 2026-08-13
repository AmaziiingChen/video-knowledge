import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TelemetryConsentNotice from './TelemetryConsentNotice.vue'

describe('TelemetryConsentNotice', () => {
  it('discloses default-on diagnostics with acknowledge, disable, and details actions', async () => {
    const wrapper = mount(TelemetryConsentNotice, { props: { saving: true } })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-busy')).toBe('true')
    expect(wrapper.text()).toContain('去标识使用诊断已开启')
    expect(wrapper.text()).toContain('默认低频发送 17 个固定检查点')
    expect(wrapper.text()).toContain('到 Cloudflare')
    expect(wrapper.text()).toContain('最多保留 3 个月')
    expect(wrapper.text()).toContain('不会发送资料内容、搜索词、链接、路径、账号、密钥或错误原文')
    expect(wrapper.text()).toContain('关闭并清除')

    const buttons = wrapper.findAll('button')
    expect(buttons.every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    await wrapper.setProps({ saving: false })
    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')

    expect(wrapper.emitted('acknowledge')).toHaveLength(1)
    expect(wrapper.emitted('disable')).toHaveLength(1)
    expect(wrapper.emitted('open-privacy')).toHaveLength(1)
  })
})
