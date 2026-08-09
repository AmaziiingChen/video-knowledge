import assert from 'node:assert/strict'
import test from 'node:test'

import { useWechatPublishingSettingsController } from './useWechatPublishingSettingsController.js'

function notifications() {
  const messages = []
  return {
    messages,
    error(message) { messages.push(['error', message]) },
    info(message) { messages.push(['info', message]) },
    success(message) { messages.push(['success', message]) },
  }
}

test('loads masked publishing settings and never keeps returned credentials in form refs', async () => {
  const request = {
    async get(url) {
      assert.equal(url, 'http://local.test/publishing/settings')
      return {
        data: {
          configured: true,
          display_name: '校报',
          app_id_masked: 'wx***',
          public_site_base_url: 'https://example.com',
        },
      }
    },
  }
  const controller = useWechatPublishingSettingsController({
    apiBase: 'http://local.test/publishing',
    request,
    notify: notifications(),
  })
  controller.wechatPublishingAppId.value = 'stale-id'
  controller.wechatPublishingAppSecret.value = 'stale-secret'

  await controller.loadWechatPublishingSettings()

  assert.equal(controller.wechatPublishingSettings.value.configured, true)
  assert.equal(controller.wechatPublishingDisplayName.value, '校报')
  assert.equal(controller.wechatPublishingAppId.value, '')
  assert.equal(controller.wechatPublishingAppSecret.value, '')
  assert.equal(controller.wechatPublicSiteBaseUrl.value, 'https://example.com')
})

test('opens the precise settings section when publishing or cover credentials are absent', async () => {
  const sections = []
  const notify = notifications()
  const request = {
    async get(url) {
      return { data: { configured: false, model: url.endsWith('/cover-settings') ? 'qwen-image-2.0' : undefined } }
    },
  }
  const controller = useWechatPublishingSettingsController({
    apiBase: 'http://local.test/publishing',
    request,
    notify,
    openSettings: (section) => sections.push(section),
  })

  assert.equal(await controller.ensureWechatPublishingConfigured(), false)
  assert.equal(await controller.ensureWechatCoverConfigured(), false)
  assert.deepEqual(sections, ['wechat', 'ai'])
  assert.equal(notify.messages.filter(([kind]) => kind === 'info').length, 2)
})

test('submits publishing credentials only to the API and clears the form after success', async () => {
  let submitted = null
  const controller = useWechatPublishingSettingsController({
    apiBase: 'http://local.test/publishing',
    request: {
      async put(url, payload) {
        assert.equal(url, 'http://local.test/publishing/settings')
        submitted = payload
        return { data: { configured: true, app_id_masked: 'wx***' } }
      },
    },
    notify: notifications(),
  })
  controller.wechatPublishingDisplayName.value = ' 校报 '
  controller.wechatPublishingAppId.value = ' wx-app-id '
  controller.wechatPublishingAppSecret.value = ' app-secret '
  controller.wechatPublicSiteBaseUrl.value = ' https://example.com '

  await controller.saveWechatPublishingSettings()

  assert.deepEqual(submitted, {
    display_name: '校报',
    app_id: 'wx-app-id',
    app_secret: 'app-secret',
    public_site_base_url: 'https://example.com',
  })
  assert.equal(controller.wechatPublishingAppId.value, '')
  assert.equal(controller.wechatPublishingAppSecret.value, '')
  assert.equal(controller.savingWechatPublishingSettings.value, false)
})
