import assert from 'node:assert/strict'
import test from 'node:test'

import axios from 'axios'

import { useRuntimeSettingsController } from './useRuntimeSettingsController.js'

test('saving pricing re-reads the canonical DeepSeek URL before the legacy update', async () => {
  const originalGet = axios.get
  const originalPut = axios.put
  const puts = []
  axios.get = async () => ({ data: { deepseek_base_url: 'https://canonical.example/v1' } })
  axios.put = async (url, body) => {
    puts.push([url, body])
    return { data: { deepseek_configured: true, deepseek_pricing: body.deepseek_pricing } }
  }
  try {
    const controller = useRuntimeSettingsController({
      formatBytes: () => '',
      loadAiTokenUsageSummary: () => {},
      requestDestructiveConfirmation: async () => false,
      notify: { success: () => {}, error: () => {} },
    })
    controller.deepseekBaseUrl.value = 'https://stale.example/v1'
    await controller.saveDeepSeekSettings()

    assert.equal(controller.deepseekBaseUrl.value, 'https://canonical.example/v1')
    assert.equal(puts.length, 1)
    assert.equal(puts[0][1].deepseek_base_url, 'https://canonical.example/v1')
    assert.equal(puts[0][1].deepseek_api_key, undefined)
  } finally {
    axios.get = originalGet
    axios.put = originalPut
  }
})
