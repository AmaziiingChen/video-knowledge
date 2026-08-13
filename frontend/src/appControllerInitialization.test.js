import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('./composables/useAppController.js', import.meta.url), 'utf8')

test('initializes the content detail dependency before completion notifications', () => {
  const readiness = source.indexOf('} = useContentReadinessController({')
  const notifications = source.indexOf('} = useCompletionNotificationController({')

  assert.ok(readiness >= 0)
  assert.ok(notifications > readiness)
  assert.match(source.slice(notifications, notifications + 360), /getContentItemDetail/)
})
