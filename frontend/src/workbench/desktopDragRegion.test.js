import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const workbenchShellSource = await readFile(
  new URL('./WorkbenchShell.vue', import.meta.url),
  'utf8',
)
const workspaceTabsSource = await readFile(
  new URL('./WorkspaceTabs.vue', import.meta.url),
  'utf8',
)

test('keeps the editor header draggable outside concrete tab controls', () => {
  assert.match(
    workbenchShellSource,
    /\.workspace-pane-header\s*\{[\s\S]*?-webkit-app-region:\s*drag;/,
  )
  assert.doesNotMatch(
    workbenchShellSource,
    /\.workspace-pane-header\s+:deep\(\.workspace-tabs-shell\)/,
  )
  assert.match(
    workspaceTabsSource,
    /\.workspace-tab-item,\s*\n\.workspace-tabs-controls\s*\{[\s\S]*?-webkit-app-region:\s*no-drag;/,
  )
  assert.match(
    workbenchShellSource,
    /v-if="integratedChrome && !showContextPane"[\s\S]*?class="workspace-editor-header-action-region"/,
  )
  assert.match(
    workbenchShellSource,
    /\.workspace-editor-header-action-region\s*\{[\s\S]*?pointer-events:\s*none;[\s\S]*?-webkit-app-region:\s*no-drag;/,
  )
})
