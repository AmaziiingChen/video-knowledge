import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const appSource = await readFile(
  new URL('../App.vue', import.meta.url),
  'utf8',
)
const appStyles = await readFile(
  new URL('../styles/app.css', import.meta.url),
  'utf8',
)

test('keeps the collapse control right-aligned inside the primary header', () => {
  const primaryHeaderStart = appSource.indexOf('<template #primary-header>')
  const editorHeaderStart = appSource.indexOf('<template #editor-header>')
  const primaryHeaderControls = appSource.slice(primaryHeaderStart, editorHeaderStart)

  assert.match(primaryHeaderControls, /class="topbar-icon-button layout-toggle-button workspace-primary-collapse"/)
  assert.match(primaryHeaderControls, /aria-label="展开或折叠左侧栏"/)
  assert.match(appStyles, /\.workspace-primary-collapse\s*\{[\s\S]*?margin-left:\s*auto;/)
})

test('keeps desktop sidebar controls clear of macOS window controls', () => {
  assert.match(
    appStyles,
    /html\.desktop-shell \.workspace-primary-controls:not\(\.is-collapsed\)[\s\S]*?padding-left:\s*calc\(var\(--vk-space-page\) \+ 24px\)/,
  )
  assert.match(
    appStyles,
    /\.workspace-editor-header-content \.workspace-primary-controls\.is-collapsed[\s\S]*?padding-left:\s*calc\(var\(--vk-space-section\) \+ var\(--vk-space-cluster\)\)/,
  )
})

test('aligns left workspace header glyphs to the macOS titlebar baseline', () => {
  assert.match(
    appStyles,
    /\.workspace-primary-controls \.topbar-icon-button > :is\(\.svg-mask-icon, \.panel-toggle-icon\)[\s\S]*?transform:\s*translateY\(1px\)/,
  )
})

test('shows only the restore control in the collapsed editor header', () => {
  const editorHeaderStart = appSource.indexOf('<template #editor-header>')
  const nextTabsStart = appSource.indexOf('<WorkspaceTabs', editorHeaderStart)
  const editorHeaderControls = appSource.slice(editorHeaderStart, nextTabsStart)

  assert.match(
    editorHeaderControls,
    /v-if="!showPrimaryPane && !primaryPaneTransitioning"/,
  )
  assert.doesNotMatch(
    editorHeaderControls,
    /showLibraryFiles|focusLibrarySearch/,
  )
  assert.doesNotMatch(
    appStyles,
    /\.workspace-editor-header-content\.is-primary-collapsed \.workspace-tabs-shell/,
  )
})

test('keeps the primary collapse control visible as one motion layer during pane transition', async () => {
  const shellSource = await readFile(
    new URL('./WorkbenchShell.vue', import.meta.url),
    'utf8',
  )

  assert.match(appSource, /const primaryPaneTransitioning = ref\(false\)/)
  assert.match(appSource, /@click="setPrimarySidebarOpen\(!primarySidebarOpen, \$event\)"/)
  assert.match(appSource, /@pane-visibility-transition-end="handlePaneVisibilityTransitionEnd"/)
  assert.match(shellSource, /class="primary-toggle-motion"/)
  assert.match(shellSource, /function beginPrimaryToggleMotion\(originRect, opening\)/)
  assert.match(shellSource, /transition: transform var\(--panel-motion\)/)
  assert.match(shellSource, /event\.target !== panes\[0\]/)
  assert.match(shellSource, /emit\('pane-visibility-transition-end', \{ side: 'primary' \}\)/)
})

test('reserves global action space from tabs when the context pane is hidden', () => {
  assert.match(
    appSource,
    /'is-context-collapsed': !showContextPane/,
  )
  assert.match(
    appStyles,
    /\.workspace-editor-header-content\.is-context-collapsed \.workspace-tabs-shell[\s\S]*?margin-right:\s*var\(--workspace-global-actions-width\)/,
  )
})
