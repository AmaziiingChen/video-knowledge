import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const appSource = await readFile(new URL('../App.vue', import.meta.url), 'utf8')
const chromeSource = await readFile(new URL('./WorkspaceChromeActions.vue', import.meta.url), 'utf8')
const treeRowSource = await readFile(new URL('./SidebarTreeRow.vue', import.meta.url), 'utf8')
const sidebarSource = await readFile(new URL('./LibrarySidebar.vue', import.meta.url), 'utf8')
const contextMenuSource = await readFile(new URL('./LibraryContextMenu.vue', import.meta.url), 'utf8')

test('keeps quick open keyboard-accessible without a permanent topbar trigger', () => {
  assert.doesNotMatch(appSource, /topbar-command-trigger/)
  assert.match(appSource, /v-model="commandPaletteOpen"/)
})

test('does not render notification badges outside the file tree', () => {
  assert.doesNotMatch(chromeSource, /completion-notification/)
  assert.doesNotMatch(chromeSource, /tray\.badge\.svg/)
})

test('keeps unread state scoped to the file tree', () => {
  assert.match(treeRowSource, /sidebar-tree-row-unread/)
  assert.match(sidebarSource, /unread-root|unread-content/)
  assert.match(contextMenuSource, /标记为已读/)
  assert.match(contextMenuSource, /标记为未读/)
  assert.match(sidebarSource, /set-content-viewed/)
})
