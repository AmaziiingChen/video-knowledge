import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./LibrarySidebar.vue', import.meta.url), 'utf8')
const linkDockSource = await readFile(new URL('./SidebarLinkDock.vue', import.meta.url), 'utf8')

test('centres file-tree toolbar actions at the same glyph size as the activity bar', () => {
  assert.match(source, /<SvgMaskIcon :src="folderAddIcon" :size="18"\s*\/>/)
  assert.match(source, /<SvgMaskIcon :src="markdownImportIcon" :size="18"\s*\/>/)
  assert.match(
    source,
    /\.sidebar-file-toolbar\s*\{[\s\S]*?justify-content:\s*center;[\s\S]*?min-height:\s*36px;[\s\S]*?padding-block:\s*0;[\s\S]*?border-top:\s*0;/,
  )
  assert.match(
    source,
    /\.sidebar-file-toolbar \.sidebar-icon-button\s*\{[\s\S]*?width:\s*36px;[\s\S]*?height:\s*36px;/,
  )
})

test('keeps the empty library and search result state readable', () => {
  assert.match(source, /<div v-else class="sidebar-empty">/)
  assert.match(
    source,
    /\.sidebar-empty\s*\{[\s\S]*?padding:\s*8px 5px;[\s\S]*?color:\s*var\(--vk-muted\);[\s\S]*?font-size:\s*var\(--vk-type-label-size\);/,
  )
})

test('expands the pasted-link composer from one to six lines', () => {
  assert.match(linkDockSource, /aria-label="粘贴待处理链接"[\s\S]*?:autosize="\{ minRows: 1, maxRows: 6 \}"/)
  assert.match(
    linkDockSource,
    /\.sidebar-process-input\s*\{[\s\S]*?display:\s*grid;[\s\S]*?padding:\s*8px 8px 7px;[\s\S]*?\.sidebar-process-input :deep\(\.el-textarea__inner\)\s*\{[\s\S]*?max-height:\s*132px;[\s\S]*?padding:\s*0 2px;[\s\S]*?overflow-y:\s*auto;/,
  )
  assert.match(linkDockSource, /\.sidebar-run-button\s*\{[\s\S]*?justify-self:\s*end;/)
})
