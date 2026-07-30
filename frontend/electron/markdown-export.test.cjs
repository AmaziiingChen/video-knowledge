const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
  exportMarkdownDocument,
  safeMarkdownFilename,
} = require('./markdown-export.cjs')

test('Markdown export uses the configured folder and deliberately overwrites by title', () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'knowledgehub-export-'))
  const exportPath = path.join(dataDir, 'exports')
  fs.writeFileSync(
    path.join(dataDir, 'obsidian_settings.json'),
    JSON.stringify({ export_path: exportPath }),
  )

  const first = exportMarkdownDocument({ dataDir, title: '校园问答', markdown: '# 第一次' })
  const second = exportMarkdownDocument({ dataDir, title: '校园问答', markdown: '# 第二次' })

  assert.equal(first.path, path.join(exportPath, '校园问答.md'))
  assert.equal(first.overwritten, false)
  assert.equal(second.overwritten, true)
  assert.equal(fs.readFileSync(second.path, 'utf8'), '# 第二次')
})

test('Markdown filenames stay portable across macOS and Windows', () => {
  assert.equal(safeMarkdownFilename('a/b:c*'), 'a_b_c_.md')
  assert.equal(safeMarkdownFilename('CON'), '_CON.md')
})
