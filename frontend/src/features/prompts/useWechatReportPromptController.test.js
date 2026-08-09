import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useWechatReportPromptController } from './useWechatReportPromptController.js'

test('loads the selected group prompt and saves its trimmed template through the feature boundary', async () => {
  const requests = []
  const controller = useWechatReportPromptController({
    reportGroups: ref([{ id: 'group-1' }]),
    request: {
      get: async () => ({ data: [{ id: 'prompt-1', group_id: 'group-1', report_type: 'group_context', template: '原始内容' }] }),
      put: async (...args) => { requests.push(args) },
    },
    notify: { error: () => {}, success: () => {}, warning: () => {} },
  })

  await controller.loadWechatReportPrompts()
  assert.equal(controller.selectedWechatReportPromptGroupId.value, 'group-1')
  assert.equal(controller.wechatReportPromptText.value, '原始内容')

  controller.wechatReportPromptText.value = '  保存内容  '
  assert.equal(await controller.saveWechatReportPrompt(), true)
  assert.deepEqual(requests[0], [
    'http://127.0.0.1:8000/api/wechat-report-groups/group-1/prompts/group_context',
    { template: '保存内容' },
    { timeout: 10000 },
  ])
})
