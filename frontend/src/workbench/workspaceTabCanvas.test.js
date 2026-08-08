import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./WorkspaceTabs.vue', import.meta.url), 'utf8')

test('blends the active tab into the editor canvas', () => {
  assert.match(source, /\.workspace-tab-selection\s*\{[\s\S]*?height:\s*36px;/)
  assert.match(source, /--workspace-tab-active-outline:\s*var\(--vk-border\);/)
  assert.match(source, /border-bottom:\s*0;/)
  assert.match(source, /<svg class="workspace-tab-seam-arc is-left"[\s\S]*?<path d="M6 0A6 6 0 0 1 0 6"/)
  assert.match(source, /<svg class="workspace-tab-seam-arc is-right"[\s\S]*?<path d="M0 0A6 6 0 0 0 6 6"/)
  assert.match(source, /\.workspace-tab-seam-mask\s*\{[\s\S]*?background:\s*var\(--vk-bg-center\)/)
  assert.doesNotMatch(source, /workspace-tab-selection::(?:before|after)/)
  assert.doesNotMatch(source, /\.workspace-editor-header:has\(/)
})
