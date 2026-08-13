import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const sourceRoot = path.join(frontendRoot, 'src')
const manifest = JSON.parse(fs.readFileSync(
  path.join(sourceRoot, 'components/macosSymbolManifest.json'),
  'utf8',
))

function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const filePath = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(filePath)
    return /\.(?:js|ts|vue)$/.test(entry.name) ? [filePath] : []
  })
}

test('product icons use the macOS boundary while tree controls retain their original Element Plus owner', () => {
  const violations = sourceFiles(sourceRoot)
    .filter((filePath) => !filePath.endsWith('macosSymbolContract.test.js'))
    .filter((filePath) => /@(?:tabler|element-plus)\/icons-vue/.test(fs.readFileSync(filePath, 'utf8')))
    .map((filePath) => path.relative(frontendRoot, filePath))

  assert.deepEqual(violations, [
    'src/components/macosSymbolComponents.js',
    'src/workbench/LibraryTrashPanel.vue',
    'src/workbench/PromptFileTree.vue',
    'src/workbench/SidebarTreeRow.vue',
  ])
})

test('the close glyph keeps the approved Tabler default instead of an SF xmark asset', () => {
  const facade = fs.readFileSync(
    path.join(sourceRoot, 'components/macosSymbolComponents.js'),
    'utf8',
  )

  assert.match(facade, /IconX as TablerIconX/)
  assert.equal(manifest.xmark, undefined)
})

test('every system icon has a stable output asset and at least one native symbol candidate', () => {
  for (const [logicalName, entry] of Object.entries(manifest)) {
    assert.match(entry.asset, /^[a-z0-9][a-z0-9.-]*$/i, `${logicalName} has an unsafe asset name`)
    if (entry.kind === 'brand') continue
    assert.ok(Array.isArray(entry.candidates) && entry.candidates.length > 0, logicalName)
  }
  assert.deepEqual(
    Object.entries(manifest).filter(([, entry]) => entry.kind === 'brand').map(([name]) => name),
    ['openclaw'],
  )
})

test('normal macOS builds generate symbols before Vite bundles the renderer', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(frontendRoot, 'package.json'), 'utf8'))
  assert.match(packageJson.scripts.build, /^npm run prepare:macos-icons && vite build/)
  assert.match(packageJson.scripts.dev, /^npm run prepare:macos-icons && vite/)
})

test('native symbols are rendered with the regular SF Symbols weight', () => {
  const renderer = fs.readFileSync(
    path.join(frontendRoot, 'scripts/render-macos-symbols.swift'),
    'utf8',
  )

  assert.match(renderer, /SymbolConfiguration\(pointSize: 82, weight: \.regular\)/)
  assert.doesNotMatch(renderer, /weight: \.(?:ultraLight|thin|light)/)
})
