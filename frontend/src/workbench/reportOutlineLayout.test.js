import assert from 'node:assert/strict'
import test from 'node:test'

import { canShowReportOutline } from './reportOutlineLayout.js'

test('keeps the outline available in the ordinary three-pane reader', () => {
  assert.equal(canShowReportOutline({ width: 620, height: 640, entryCount: 2 }), true)
  assert.equal(canShowReportOutline({ width: 519, height: 640, entryCount: 2 }), false)
  assert.equal(canShowReportOutline({ width: 620, height: 299, entryCount: 2 }), false)
  assert.equal(canShowReportOutline({ width: 620, height: 640, entryCount: 1 }), false)
})
