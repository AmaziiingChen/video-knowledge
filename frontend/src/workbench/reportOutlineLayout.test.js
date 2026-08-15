import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canShowReportOutline,
  reportOutlineHeight,
} from './reportOutlineLayout.js'

test('shows a local outline only after the reader has enough width and safe gutter', () => {
  assert.equal(canShowReportOutline({ width: 620, height: 640, entryCount: 2, leftGutter: 120 }), false)
  assert.equal(canShowReportOutline({ width: 760, height: 640, entryCount: 2, leftGutter: 69 }), false)
  assert.equal(canShowReportOutline({ width: 760, height: 640, entryCount: 2, leftGutter: 70 }), true)
  assert.equal(canShowReportOutline({ width: 900, height: 299, entryCount: 2, leftGutter: 120 }), false)
  assert.equal(canShowReportOutline({ width: 900, height: 640, entryCount: 1, leftGutter: 120 }), false)
})

test('keeps an internal-browser outline behind the same reader width threshold', () => {
  assert.equal(canShowReportOutline({ width: 360, height: 640, entryCount: 2, leftGutter: 70, remote: true }), false)
  assert.equal(canShowReportOutline({ width: 760, height: 640, entryCount: 2, leftGutter: 70, remote: true }), true)
  assert.equal(canShowReportOutline({ width: 360, height: 299, entryCount: 2, remote: true }), false)
  assert.equal(canShowReportOutline({ width: 360, height: 640, entryCount: 1, remote: true }), false)
})

test('keeps two or three headings visible with the minimum rail height', () => {
  assert.equal(reportOutlineHeight({ availableHeight: 600, readerHeight: 640, entryCount: 2 }), 64)
  assert.equal(reportOutlineHeight({ availableHeight: 600, readerHeight: 640, entryCount: 3 }), 64)
  assert.equal(reportOutlineHeight({ availableHeight: 600, readerHeight: 640, entryCount: 5 }), 80)
  assert.equal(reportOutlineHeight({ availableHeight: 60, readerHeight: 640, entryCount: 5 }), 0)
})
