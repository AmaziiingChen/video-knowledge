import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const appSource = await readFile(new URL('../../App.vue', import.meta.url), 'utf8')

test('wires manual summary reasoning from the app controller into the assistant sidebar', () => {
  const bindingEnd = appSource.indexOf('} = useAppController()')
  const bindingStart = appSource.lastIndexOf('const {', bindingEnd)
  const controllerBinding = appSource.slice(bindingStart, bindingEnd)

  assert.ok(bindingStart >= 0 && bindingEnd > bindingStart, 'App must destructure the useAppController result')
  assert.match(controllerBinding, /\bgeneratingSummaryReasoning\b/)
  assert.match(controllerBinding, /\bgeneratingSummaryReasoningExpanded\b/)
  assert.match(appSource, /:generating-summary-reasoning="generatingSummaryReasoning"/)
  assert.match(appSource, /:generating-summary-reasoning-expanded="generatingSummaryReasoningExpanded"/)
  assert.match(appSource, /@update:generating-summary-reasoning-expanded="generatingSummaryReasoningExpanded = \$event"/)
})
