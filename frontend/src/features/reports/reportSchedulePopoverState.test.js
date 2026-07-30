import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldKeepScheduleEditorOpen } from './reportSchedulePopoverState.js'

test('keeps the schedule editor open while the nested time picker is open', () => {
  assert.equal(shouldKeepScheduleEditorOpen({ timePickerOpen: true }), true)
})

test('keeps the schedule editor open for the click that closes the time picker', () => {
  assert.equal(shouldKeepScheduleEditorOpen({ timePickerClosing: true }), true)
})

test('allows the schedule editor to close after the time picker interaction ends', () => {
  assert.equal(shouldKeepScheduleEditorOpen(), false)
})
