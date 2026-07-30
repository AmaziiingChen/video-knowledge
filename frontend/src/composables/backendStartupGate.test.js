import assert from 'node:assert/strict'
import test from 'node:test'

import { waitForDesktopBackend } from './backendStartupGate.js'

test('waits for the Electron-owned backend instead of starting hydration early', async () => {
  let releaseBackend
  const backendReady = new Promise((resolve) => {
    releaseBackend = resolve
  })
  let completed = false
  const waiting = waitForDesktopBackend(() => backendReady).then(() => {
    completed = true
  })

  await Promise.resolve()
  assert.equal(completed, false)
  releaseBackend(true)
  await waiting
  assert.equal(completed, true)
})

test('does not add a desktop-only gate to browser development', async () => {
  await waitForDesktopBackend(undefined)
})
