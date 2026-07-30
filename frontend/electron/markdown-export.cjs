const fs = require('fs')
const path = require('path')

const WINDOWS_RESERVED_NAMES = new Set([
  'CON', 'PRN', 'AUX', 'NUL',
  ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`),
])

function safeMarkdownFilename(title) {
  let stem = String(title || '').trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
  stem = stem.replace(/[ .]+$/g, '').slice(0, 120) || 'AI 对话'
  if (WINDOWS_RESERVED_NAMES.has(stem.toUpperCase())) stem = `_${stem}`
  return `${stem}.md`
}

function configuredExportDirectory(dataDir) {
  const fallback = path.resolve(dataDir, 'markdown')
  const settingsPath = path.resolve(dataDir, 'obsidian_settings.json')
  try {
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'))
    const configured = String(settings?.export_path || settings?.vault_path || '').trim()
    return configured && path.isAbsolute(configured) ? path.resolve(configured) : fallback
  } catch {
    return fallback
  }
}

function exportMarkdownDocument({ dataDir, title, markdown }) {
  const body = String(markdown || '')
  if (!body) throw new Error('没有可导出的 Markdown 内容')
  if (Buffer.byteLength(body, 'utf8') > 5_000_000) throw new Error('Markdown 内容超过 5 MB，无法导出')

  const outputDirectory = configuredExportDirectory(dataDir)
  fs.mkdirSync(outputDirectory, { recursive: true })
  const destination = path.join(outputDirectory, safeMarkdownFilename(title))
  const overwritten = fs.existsSync(destination)
  const temporary = path.join(
    outputDirectory,
    `.${path.basename(destination, '.md')}-${process.pid}-${Date.now()}.tmp`,
  )
  try {
    fs.writeFileSync(temporary, body, { encoding: 'utf8', mode: 0o600 })
    try {
      fs.renameSync(temporary, destination)
    } catch (error) {
      // Windows does not consistently let rename replace an existing file.
      // Keep the documented replace-by-name behavior on both desktop targets.
      if (!overwritten || !['EEXIST', 'EPERM', 'EACCES'].includes(error?.code)) throw error
      fs.unlinkSync(destination)
      fs.renameSync(temporary, destination)
    }
  } finally {
    try {
      fs.unlinkSync(temporary)
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
  }
  return { path: destination, overwritten }
}

module.exports = {
  configuredExportDirectory,
  exportMarkdownDocument,
  safeMarkdownFilename,
}
