const path = require('path')

function applyUserDataDirectoryOverride(app, value = process.env.KNOWLEDGEHUB_USER_DATA_DIR) {
  const configured = String(value || '').trim()
  if (!configured) return ''
  if (!path.isAbsolute(configured)) {
    throw new Error('KNOWLEDGEHUB_USER_DATA_DIR 必须是绝对路径')
  }
  const resolved = path.resolve(configured)
  app.setPath('userData', resolved)
  return resolved
}

module.exports = { applyUserDataDirectoryOverride }
