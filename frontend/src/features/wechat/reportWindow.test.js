import test from 'node:test'
import assert from 'node:assert/strict'

import {
  defaultCustomReportWindow,
  normalizeReportWindow,
  reportWindowDates,
  validateCustomReportWindow,
} from './reportWindow.js'


test('custom report window accepts cross-day ranges and later edits', () => {
  const crossDay = normalizeReportWindow([
    new Date(2026, 6, 16, 23, 0),
    new Date(2026, 6, 17, 1, 0),
  ])
  assert.equal(validateCustomReportWindow(crossDay), '')

  const corrected = normalizeReportWindow([
    new Date(2026, 6, 17, 0, 0),
    new Date(2026, 6, 17, 1, 0),
  ])
  assert.notStrictEqual(corrected, crossDay)
  assert.equal(validateCustomReportWindow(corrected), '')
  assert.deepEqual(
    reportWindowDates(corrected).map((value) => value.getHours()),
    [0, 1],
  )
})


test('custom report window is stored as primitive timestamps', () => {
  const now = new Date(2026, 6, 17, 10, 30)
  const window = defaultCustomReportWindow(now)

  assert.deepEqual(window, [new Date(2026, 6, 17, 0, 0).getTime(), now.getTime()])
  assert.ok(window.every((value) => Number.isFinite(value)))
})
