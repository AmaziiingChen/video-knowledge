import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { useSelectedTextContext } from './useSelectedTextContext.js'

test('binds one normalized selection to the active content and its explicit token', async () => {
  const questionInput = ref('请解释')
  const activeContent = ref({ id: 'content-1', title: '材料一' })
  const controller = useSelectedTextContext({
    questionInput,
    getActiveContent: () => activeContent.value,
    now: () => 42,
  })

  controller.setSelectedTextContext({ text: '  第一行\n第二行  ' })

  assert.equal(questionInput.value, '请解释 @选中文本 ')
  assert.deepEqual(controller.activeSelectedTextContext.value, {
    id: 'content-1:42',
    contentItemId: 'content-1',
    contentTitle: '材料一',
    text: '第一行 第二行',
  })

  await nextTick()
  questionInput.value = '请解释'
  await nextTick()
  assert.equal(controller.activeSelectedTextContext.value, null)
  controller.disposeSelectedTextContext()
})

test('hides a retained selection after the active document changes', () => {
  const questionInput = ref('')
  const activeContent = ref({ id: 'content-1', title: '材料一' })
  const controller = useSelectedTextContext({
    questionInput,
    getActiveContent: () => activeContent.value,
  })

  controller.setSelectedTextContext({ text: '选中内容' })
  activeContent.value = { id: 'content-2', title: '材料二' }

  assert.equal(controller.activeSelectedTextContext.value, null)
  controller.clearSelectedTextContext()
  assert.equal(questionInput.value, '')
  controller.disposeSelectedTextContext()
})
