const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const mainSource = fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8')
const preloadSource = fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8')

test('the macOS application menu exposes existing global workbench actions', () => {
  assert.match(mainSource, /function createApplicationMenu\(\)/)
  assert.match(mainSource, /Menu\.setApplicationMenu\(Menu\.buildFromTemplate\(template\)\)/)
  assert.match(mainSource, /createApplicationMenu\(\)\n  createWindow\(\)/)
  assert.match(mainSource, /\{ role: 'editMenu', label: '编辑' \}/)
  for (const action of [
    'settings', 'check-for-update', 'import-local-files', 'open-command-palette',
    'toggle-primary-sidebar', 'toggle-context-sidebar', 'toggle-process-log',
    'toggle-clipboard-watching', 'refresh-library',
  ]) {
    assert.match(mainSource, new RegExp(`action\\('${action}'\\)`))
  }
})

test('only the preload bridge subscribes the renderer to main-menu actions', () => {
  assert.match(mainSource, /webContents\.send\('knowledgehub:menu-action', action\)/)
  assert.match(preloadSource, /onMenuAction: \(listener\)/)
  assert.match(preloadSource, /ipcRenderer\.on\('knowledgehub:menu-action', handler\)/)
  assert.match(preloadSource, /ipcRenderer\.removeListener\('knowledgehub:menu-action', handler\)/)
})
