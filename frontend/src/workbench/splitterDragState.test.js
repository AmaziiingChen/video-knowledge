import assert from 'node:assert/strict'
import test from 'node:test'

import {
  COLLAPSED_PANE_REVEAL_DISTANCE,
  COLLAPSED_PANE_SIZE,
  MAX_PROCESS_LOG_TASK_WIDTH,
  MAX_PROCESS_LOG_HEIGHT,
  MIN_PROCESS_LOG_TASK_WIDTH,
  PROCESS_LOG_SNAP_COLLAPSE_HEIGHT,
  PROCESS_LOG_SNAP_REOPEN_HEIGHT,
  clampProcessLogTaskWidth,
  processLogRevealHeight,
  resolveProcessLogDragTransition,
  resolvePaneDragTransition,
  revealProgressForDistance,
  clampVerticalContentSplit,
  verticalContentSplitBounds,
} from './splitterDragState.js'

test('keeps the same pane drag active through collapse, reverse-open, and resize', () => {
  const initialResize = resolvePaneDragTransition({}, 240)
  assert.equal(initialResize.action, 'resize')

  let state = resolvePaneDragTransition({}, 119)
  assert.deepEqual(state, {
    collapsed: true,
    action: 'collapse'
  })

  state = resolvePaneDragTransition(state, 140)
  assert.equal(state.action, 'none')
  assert.equal(state.collapsed, true)

  state = resolvePaneDragTransition(state, 148)
  assert.equal(state.action, 'open')
  assert.equal(state.collapsed, false)

  state = resolvePaneDragTransition(state, 176)
  assert.equal(state.action, 'resize')
})

test('uses hysteresis so a reopened pane does not chatter around the snap point', () => {
  let state = resolvePaneDragTransition({ collapsed: true }, 121)
  assert.equal(state.action, 'none')
  assert.equal(state.collapsed, true)

  state = resolvePaneDragTransition(state, 160)
  assert.equal(state.action, 'open')

  state = resolvePaneDragTransition(state, 119)
  assert.equal(state.action, 'collapse')
  assert.equal(state.collapsed, true)
})

test('maps a collapsed-pane drag to continuous reveal progress', () => {
  assert.equal(revealProgressForDistance(-20), 0)
  assert.equal(revealProgressForDistance(0), 0)
  assert.equal(revealProgressForDistance(COLLAPSED_PANE_REVEAL_DISTANCE / 2), 0.5)
  assert.equal(revealProgressForDistance(COLLAPSED_PANE_REVEAL_DISTANCE), 1)
  assert.equal(revealProgressForDistance(COLLAPSED_PANE_REVEAL_DISTANCE * 2), 1)
})

test('maps a collapsed log drag to its visible panel height', () => {
  assert.equal(processLogRevealHeight(-20), COLLAPSED_PANE_SIZE)
  assert.equal(processLogRevealHeight(0), COLLAPSED_PANE_SIZE)
  assert.equal(processLogRevealHeight(42), COLLAPSED_PANE_SIZE + 42)
  assert.equal(processLogRevealHeight(1000), MAX_PROCESS_LOG_HEIGHT)
})

test('keeps the log resize gesture active through collapse and reverse-open', () => {
  let state = resolveProcessLogDragTransition({}, PROCESS_LOG_SNAP_COLLAPSE_HEIGHT - 1)
  assert.deepEqual(state, { collapsed: true, action: 'collapse' })

  state = resolveProcessLogDragTransition(state, PROCESS_LOG_SNAP_REOPEN_HEIGHT - 1)
  assert.deepEqual(state, { collapsed: true, action: 'none' })

  state = resolveProcessLogDragTransition(state, PROCESS_LOG_SNAP_REOPEN_HEIGHT)
  assert.deepEqual(state, { collapsed: false, action: 'open' })

  state = resolveProcessLogDragTransition(state, PROCESS_LOG_SNAP_REOPEN_HEIGHT + 32)
  assert.deepEqual(state, { collapsed: false, action: 'resize' })
})

test('keeps the log task list readable without starving the output columns', () => {
  assert.equal(clampProcessLogTaskWidth(100, 1200), MIN_PROCESS_LOG_TASK_WIDTH)
  assert.equal(clampProcessLogTaskWidth(600, 1200), MAX_PROCESS_LOG_TASK_WIDTH)
  assert.equal(clampProcessLogTaskWidth(380, 780), 372)
})

test('keeps vertical media/text panes within their physical minimum heights', () => {
  assert.deepEqual(verticalContentSplitBounds(800), { min: 25, max: 75 })
  const compactBounds = verticalContentSplitBounds(320)
  assert.equal(compactBounds.min, 46.875)
  assert.ok(Math.abs(compactBounds.max - 51.25) < 0.001)
  assert.equal(clampVerticalContentSplit(10, 320), 47)
  assert.equal(clampVerticalContentSplit(90, 320), 51)
})
