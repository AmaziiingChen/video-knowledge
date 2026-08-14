import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('./App.vue', import.meta.url), 'utf8')
const primarySidebarSource = await readFile(new URL('./workbench/PrimarySidebar.vue', import.meta.url), 'utf8')
const librarySidebarSource = await readFile(new URL('./workbench/LibrarySidebar.vue', import.meta.url), 'utf8')

test('desktop menu actions reuse the existing settings, update, workspace, and clipboard flows', () => {
  assert.match(source, /checkManualUpdate,/)
  assert.match(source, /function handleDesktopMenuAction\(action\)/)
  assert.match(source, /case 'settings':[\s\S]*?await openSettings\(\)/)
  assert.match(source, /case 'check-for-update':[\s\S]*?checkManualUpdate\(\{ interactive: true \}\)/)
  assert.match(source, /case 'toggle-clipboard-watching':[\s\S]*?toggleClipboardWatching\(!clipboardWatching\.value\)/)
  assert.match(source, /onMenuAction\?\.\(\(action\) => \{[\s\S]*?handleDesktopMenuAction\(action\)/)
  assert.match(source, /__knowledgeHubRemoveMenuActionListener\?\.\(\)/)
})

test('the menu-driven local import reaches the established library file picker', () => {
  assert.match(source, /chooseLocalFileImport\?\.\(\)/)
  assert.match(primarySidebarSource, /chooseLocalFileImport: \(\) => librarySidebar\.value\?\.chooseLocalFileImport\?\.\(\)/)
  assert.match(librarySidebarSource, /chooseLocalFileImport: \(\) => chooseMarkdownFile\(\)/)
})
