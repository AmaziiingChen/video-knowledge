import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname, '..')
const SOURCE_ROOT = path.join(ROOT, 'src')
const EXTENSIONS = ['.js', '.vue']
const ENTRYPOINTS = [
  path.join(SOURCE_ROOT, 'main.js'),
  path.join(SOURCE_ROOT, 'public-report-site', 'main.js'),
  path.join(SOURCE_ROOT, 'public-report-site', 'archive.js'),
]

function isProductionSource(filename) {
  return EXTENSIONS.includes(path.extname(filename)) && !/\.(?:test|spec)\.js$/u.test(filename)
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(async (entry) => {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(target)
    return isProductionSource(entry.name) ? [target] : []
  }))
  return files.flat()
}

function resolveImport(fromFile, specifier, knownFiles) {
  if (!specifier.startsWith('.')) return null
  const base = path.resolve(path.dirname(fromFile), specifier)
  const candidates = [
    base,
    ...EXTENSIONS.map((extension) => `${base}${extension}`),
    ...EXTENSIONS.map((extension) => path.join(base, `index${extension}`)),
  ]
  return candidates.find((candidate) => knownFiles.has(candidate)) || null
}

function importSpecifiers(source) {
  const expression = /(?:\bimport\s*(?:[^'"()]*?\s+from\s*)?|\bexport\s+[^'"()]*?\s+from\s*|\bimport\s*\()(['"])([^'"]+)\1/g
  return [...source.matchAll(expression)].map((match) => match[2])
}

const files = await sourceFiles(SOURCE_ROOT)
const knownFiles = new Set(files)
const reachable = new Set()
const queue = ENTRYPOINTS.filter((entry) => knownFiles.has(entry))

while (queue.length) {
  const current = queue.pop()
  if (!current || reachable.has(current)) continue
  reachable.add(current)
  const source = await readFile(current, 'utf8')
  for (const specifier of importSpecifiers(source)) {
    const resolved = resolveImport(current, specifier, knownFiles)
    if (resolved && !reachable.has(resolved)) queue.push(resolved)
  }
}

const candidates = files
  .filter((file) => !reachable.has(file))
  .map((file) => path.relative(ROOT, file))
  .sort()

console.log(`reachable source files: ${reachable.size}/${files.length}`)
if (!candidates.length) {
  console.log('unreachable source candidates: none')
  process.exit(0)
}

console.log('unreachable source candidates (review before deletion):')
for (const candidate of candidates) console.log(`- ${candidate}`)
