import assert from 'node:assert/strict'
import test from 'node:test'

import {
  estimatedReadingMinutes,
  readingProgressFromScroll,
  remainingReadingMinutes,
} from './readingProgress.js'

test('maps the reader scroll range onto a bounded percentage', () => {
  assert.equal(readingProgressFromScroll({ scrollTop: 0, scrollHeight: 1000, clientHeight: 200 }), 0)
  assert.equal(readingProgressFromScroll({ scrollTop: 400, scrollHeight: 1000, clientHeight: 200 }), 50)
  assert.equal(readingProgressFromScroll({ scrollTop: 900, scrollHeight: 1000, clientHeight: 200 }), 100)
})

test('treats a reader without overflow as already complete', () => {
  assert.equal(readingProgressFromScroll({ scrollTop: 0, scrollHeight: 200, clientHeight: 200 }), 100)
})

test('estimates reading time at the 350 characters per minute product pace', () => {
  assert.equal(estimatedReadingMinutes(0), 0)
  assert.equal(estimatedReadingMinutes(1), 1)
  assert.equal(estimatedReadingMinutes(350), 1)
  assert.equal(estimatedReadingMinutes(351), 2)
})

test('estimates only the unread time and reports completion at the end', () => {
  assert.equal(remainingReadingMinutes(3500, 0), 10)
  assert.equal(remainingReadingMinutes(3500, 50), 5)
  assert.equal(remainingReadingMinutes(3500, 99), 1)
  assert.equal(remainingReadingMinutes(3500, 100), 0)
})
