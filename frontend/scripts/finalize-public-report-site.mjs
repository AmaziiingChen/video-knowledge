import { mkdir, readFile, readdir, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const outputRoot = new URL('../dist-public-report/', import.meta.url)
const reportsRoot = new URL('../dist-public-report/reports/', import.meta.url)

async function reportDirectories(root) {
  try {
  const rootPath = fileURLToPath(root)
    const names = await readdir(rootPath)
    const results = await Promise.all(names.map(async (name) => ({
      name,
      isDirectory: (await stat(join(rootPath, name))).isDirectory(),
    })))
    return results.filter((item) => item.isDirectory).map((item) => item.name)
  } catch {
    return []
  }
}

const reportIndex = (await readFile(new URL('index.html', outputRoot), 'utf8'))
  .replaceAll('./assets/', '../../assets/')
  .replace('<title>知识简报 · 校园生活周报</title>', '<title>知识简报 · 报告</title>')

for (const slug of await reportDirectories(reportsRoot)) {
  const reportDir = new URL(`${slug}/`, reportsRoot)
  await mkdir(reportDir, { recursive: true })
  await writeFile(new URL('index.html', reportDir), reportIndex, 'utf8')
}
