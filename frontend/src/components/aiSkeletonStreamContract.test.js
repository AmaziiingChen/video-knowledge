import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const [tokens, stream, knowledge, media, xhsStyles] = await Promise.all([
  readFile(new URL('../styles/app.css', import.meta.url), 'utf8'),
  readFile(new URL('./AiSkeletonStream.vue', import.meta.url), 'utf8'),
  readFile(new URL('../features/knowledge/KnowledgeWorkspace.vue', import.meta.url), 'utf8'),
  readFile(new URL('../workbench/media-transcript-surface.css', import.meta.url), 'utf8'),
  readFile(new URL('../workbench/editor-host-articles.css', import.meta.url), 'utf8'),
])

test('uses one quiet semantic palette for AI and transcript loading streams', () => {
  assert.match(tokens, /--vk-ai-stream-track:\s*color-mix\(in srgb, var\(--vk-border\) 62%, var\(--vk-bg-panel\)\);/)
  assert.match(tokens, /--vk-ai-stream-highlight:\s*color-mix\(in srgb, var\(--vk-bg-panel\) 56%, var\(--vk-border\)\);/)
  assert.match(stream, /background:\s*var\(--vk-ai-stream-track\);/)
  assert.match(stream, /var\(--vk-ai-stream-highlight\) 48%/)
  assert.match(media, /background:\s*var\(--vk-ai-stream-track\);/)
  assert.match(media, /var\(--vk-ai-stream-highlight\) 48%/)
  assert.doesNotMatch(stream, /var\(--vk-text\) 16%/)
})

test('reuses the shared stream in knowledge answers without retaining a duplicate shimmer', () => {
  assert.match(knowledge, /import AiSkeletonStream from '\.\.\/\.\.\/components\/AiSkeletonStream\.vue'/)
  assert.match(knowledge, /<AiSkeletonStream[\s\S]*?v-else-if="item\.pending"[\s\S]*?aria-label="AI 正在生成回答"/)
  assert.doesNotMatch(knowledge, /class="skeleton-line/)
  assert.doesNotMatch(knowledge, /knowledge-skeleton-shimmer/)
})

test('leaves the independent image-capture and campus preview animations intact', () => {
  assert.match(xhsStyles, /animation:\s*xhs-capture-shimmer/)
  assert.match(xhsStyles, /animation:\s*campus-preview-pulse/)
})
