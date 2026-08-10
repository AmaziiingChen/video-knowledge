import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const appStyles = await readFile(
  new URL('../styles/app.css', import.meta.url),
  'utf8',
)
const editorHostSource = await readFile(
  new URL('./EditorHost.vue', import.meta.url),
  'utf8',
)
const editorHostStyles = (
  await Promise.all([
    'editor-host-workspace.css',
    'editor-host-documents.css',
    'editor-host-articles.css',
    'editor-host-transcript.css',
  ].map((filename) => readFile(new URL(filename, import.meta.url), 'utf8')))
).join('\n')
const reportReaderStyles = await readFile(
  new URL('./report-reader-surface.css', import.meta.url),
  'utf8',
)
const workbenchShellSource = await readFile(
  new URL('./WorkbenchShell.vue', import.meta.url),
  'utf8',
)
const aiSkeletonStreamSource = await readFile(
  new URL('../components/AiSkeletonStream.vue', import.meta.url),
  'utf8',
)

test('keeps central preview workbench surfaces square', () => {
  assert.match(
    appStyles,
    /:global\(\.main-canvas\)\s*\{[\s\S]*?border-radius:\s*0;/,
  )
  assert.match(
    editorHostStyles,
    /\.workbench-editor-host\s*\{[\s\S]*?border-radius:\s*0;/,
  )
  assert.match(
    editorHostStyles,
    /\.content-hero\.media-transcript-layout\s+\.transcript-timeline,[\s\S]*?\{[\s\S]*?border-radius:\s*0;/,
  )
})

test('keeps workbench panes flush while retaining a one-pixel divider', () => {
  assert.match(
    workbenchShellSource,
    /\.workspace-panes\s+:deep\(\.splitpanes__splitter\)\s*\{[\s\S]*?width:\s*1px;[\s\S]*?min-width:\s*1px;[\s\S]*?flex-basis:\s*1px;[\s\S]*?margin:\s*0 !important;/,
  )
  assert.match(
    workbenchShellSource,
    /\.workspace-panes\s+:deep\(\.splitpanes__splitter::after\)\s*\{[\s\S]*?left:\s*-7px;[\s\S]*?width:\s*15px;/,
  )
})

test('keeps Xiaohongshu captures visible as independent image and text streams', () => {
  assert.match(editorHostSource, /shouldShowXhsImageCapturePreview\(activeContentTab\.id\)/)
  assert.match(editorHostSource, /shouldShowXhsTextCapturePreview\(activeContentTab\.id\)/)
  assert.match(editorHostSource, /content\?\.status === 'processing'/)
  assert.match(editorHostStyles, /\.xhs-capture-image-stream\s*\{/)
  assert.match(editorHostSource, /<AiSkeletonStream[\s\S]*?label="正在读取作者文字"/)
  assert.match(aiSkeletonStreamSource, /ai-skeleton-stream-shimmer/)
})

test('uses a native media spinner instead of skeleton text over a video cover', () => {
  const coverPreview = editorHostSource.slice(
    editorHostSource.indexOf("contentForTab(activeContentTab.id)?.cover_url"),
    editorHostSource.indexOf("<div v-else class=\"media-placeholder\">")
  )
  assert.match(coverPreview, /class="media-preview-loader"/)
  assert.match(coverPreview, /class="media-preview-spinner"/)
  assert.doesNotMatch(coverPreview, /AiSkeletonStream/)
  assert.match(editorHostStyles, /@keyframes media-preview-spin/)
})

test('keeps the EditorHost scoped style domains in their original cascade order', () => {
  assert.match(
    editorHostSource,
    /<style scoped src="\.\/editor-host-workspace\.css"><\/style>[\s\S]*?<style scoped src="\.\/editor-host-documents\.css"><\/style>[\s\S]*?<style scoped src="\.\/editor-host-articles\.css"><\/style>[\s\S]*?<style scoped src="\.\/editor-host-transcript\.css"><\/style>/,
  )
})

test('keeps capture metadata separators with the report reader surface', () => {
  assert.match(
    reportReaderStyles,
    /\.capture-reader-meta span \+ span::before\s*\{[\s\S]*?content:\s*"·";[\s\S]*?margin:\s*0 7px;/,
  )
})
