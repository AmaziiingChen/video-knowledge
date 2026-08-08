const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const mainSource = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8')

test('every exposed desktop IPC handler requires the trusted app renderer', () => {
  const handlerCalls = [...mainSource.matchAll(/ipcMain\.handle\([^\n]+/g)]
  assert.ok(handlerCalls.length >= 10, 'expected desktop IPC handlers to be registered')
  for (const call of handlerCalls) {
    assert.match(call[0], /trustedIpcHandler\(/, call[0])
  }
  assert.match(mainSource, /function isTrustedDesktopRenderer\(event\)/)
  assert.match(mainSource, /frameUrl === APP_ORIGIN/)
})
