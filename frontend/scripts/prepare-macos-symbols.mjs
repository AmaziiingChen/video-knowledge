import { mkdir, readFile, rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const manifestPath = path.join(frontendRoot, 'src/components/macosSymbolManifest.json')
const swiftScript = path.join(frontendRoot, 'scripts/render-macos-symbols.swift')
const outputDir = path.join(frontendRoot, 'public/generated/sf-symbols')
const moduleCacheDir = path.join(frontendRoot, 'node_modules/.cache/knowledgehub-swift-modules')

if (process.platform !== 'darwin') {
  console.log('Skipping SF Symbols generation: KnowledgeHub desktop targets macOS.')
  process.exit(0)
}

const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
const expectedAssets = [...new Set(
  Object.values(manifest)
    .filter((entry) => entry.kind !== 'brand')
    .map((entry) => entry.asset),
)]

await rm(outputDir, { recursive: true, force: true })
await mkdir(outputDir, { recursive: true })
await mkdir(moduleCacheDir, { recursive: true })

const result = spawnSync(
  '/usr/bin/xcrun',
  ['swift', swiftScript, manifestPath, outputDir],
  {
    cwd: frontendRoot,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLANG_MODULE_CACHE_PATH: moduleCacheDir,
      SWIFT_MODULECACHE_PATH: moduleCacheDir,
    },
  },
)

if (result.stdout) process.stdout.write(result.stdout)
if (result.stderr) process.stderr.write(result.stderr)
if (result.status !== 0) {
  throw new Error(`SF Symbols generation failed with exit code ${result.status ?? 'unknown'}`)
}

const rendered = String(result.stdout || '')
  .split('\n')
  .filter((line) => line.startsWith('rendered:'))
  .map((line) => line.slice('rendered:'.length).trim())

if (rendered.length !== expectedAssets.length) {
  throw new Error(`Expected ${expectedAssets.length} SF Symbol assets, rendered ${rendered.length}`)
}

console.log(`Prepared ${rendered.length} native SF Symbols for the macOS renderer.`)
