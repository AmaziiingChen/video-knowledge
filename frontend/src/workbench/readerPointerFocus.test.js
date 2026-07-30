import assert from 'node:assert/strict'
import test from 'node:test'

import {
  READER_INTERACTIVE_SELECTOR,
  READER_TEXT_FOCUS_SELECTOR,
  shouldClaimReaderFocus,
} from './readerPointerFocus.js'

function targetMatching(...selectors) {
  const matches = new Set(selectors)
  return {
    closest(selector) {
      return matches.has(selector) ? { selector } : null
    },
  }
}

test('plain reader text claims focus from a stale sidebar control', () => {
  assert.equal(
    shouldClaimReaderFocus(targetMatching(READER_TEXT_FOCUS_SELECTOR)),
    true,
  )
})

test('interactive controls inside a reader keep their own focus behavior', () => {
  assert.equal(
    shouldClaimReaderFocus(targetMatching(
      READER_TEXT_FOCUS_SELECTOR,
      READER_INTERACTIVE_SELECTOR,
    )),
    false,
  )
})

test('pointer activity outside the reader does not change focus', () => {
  assert.equal(shouldClaimReaderFocus(targetMatching()), false)
  assert.equal(shouldClaimReaderFocus(null), false)
})
