import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TelemetryConsentNotice from './TelemetryConsentNotice.vue'

describe('TelemetryConsentNotice', () => {
  it('offers non-modal allow, defer, and details actions without blocking the workspace', async () => {
    const wrapper = mount(TelemetryConsentNotice)

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.text()).toContain('通过 Cloudflare')
    expect(wrapper.text()).toContain('最多保留 3 个月')
    expect(wrapper.text()).toContain('不会发送资料内容、搜索词、链接、路径、账号或密钥')

    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')

    expect(wrapper.emitted('allow')).toHaveLength(1)
    expect(wrapper.emitted('dismiss')).toHaveLength(1)
    expect(wrapper.emitted('open-privacy')).toHaveLength(1)
  })
})
