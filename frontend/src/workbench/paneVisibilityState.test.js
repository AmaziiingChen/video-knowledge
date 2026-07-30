import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeWorkspacePaneVisibility } from './paneVisibilityState.js'

test('keeps explicit workspace pane visibility choices', () => {
  assert.deepEqual(normalizeWorkspacePaneVisibility({ primary: false, context: true }), {
    primary: false,
    context: true,
  })
})

test('falls back to a complete workspace when saved pane visibility is invalid', () => {
  assert.deepEqual(normalizeWorkspacePaneVisibility(null), { primary: true, context: true })
  assert.deepEqual(normalizeWorkspacePaneVisibility({ primary: 'false', context: null }), {
    primary: true,
    context: true,
  })
})
