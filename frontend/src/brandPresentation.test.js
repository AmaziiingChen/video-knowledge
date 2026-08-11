import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const appSource = await readFile(new URL('./App.vue', import.meta.url), 'utf8')
const appStyles = await readFile(new URL('./styles/app.css', import.meta.url), 'utf8')

test('uses the approved application icon and a compact system monospace wordmark', () => {
  assert.match(appSource, /import appIconUrl from '\.\.\/build\/icon\.svg\?url'/)
  assert.match(appSource, /<img class="brand-mark" :src="appIconUrl" width="22" height="22"/)
  assert.doesNotMatch(appSource, /<div class="brand-mark">KH<\/div>/)
  assert.match(appStyles, /--vk-font-brand:\s*ui-monospace,[^;]+SF Mono[^;]+monospace;/)
  assert.match(appStyles, /\.brand h1\s*\{[\s\S]*?font-style:\s*normal;[\s\S]*?letter-spacing:\s*-0\.03em;/)
})
