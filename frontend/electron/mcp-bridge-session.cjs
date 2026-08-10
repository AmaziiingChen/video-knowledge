const { randomBytes, randomUUID } = require('crypto')
const fs = require('fs')
const path = require('path')

const TOKEN_FILENAME = 'mcp-bridge-token'
const LEASE_FILENAME = 'mcp-bridge-lease.json'
const LEASE_HEARTBEAT_MS = 5_000

function currentUid() {
  return typeof process.getuid === 'function' ? process.getuid() : null
}

function assertOwned(stat, label) {
  const uid = currentUid()
  if (uid !== null && stat.uid !== uid) throw new Error(`${label}不属于当前用户`)
}

function ensureSecureRunDirectory(runDir) {
  const resolved = path.resolve(runDir)
  fs.mkdirSync(resolved, { recursive: true, mode: 0o700 })
  const stat = fs.lstatSync(resolved)
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('MCP bridge 运行目录不是安全目录')
  assertOwned(stat, 'MCP bridge 运行目录')
  fs.chmodSync(resolved, 0o700)
  const checked = fs.lstatSync(resolved)
  if ((checked.mode & 0o077) !== 0) throw new Error('MCP bridge 运行目录权限过宽')
  return resolved
}

function assertSafeExistingFile(target) {
  let stat
  try {
    stat = fs.lstatSync(target)
  } catch (error) {
    if (error?.code === 'ENOENT') return false
    throw error
  }
  if (stat.isSymbolicLink() || !stat.isFile() || stat.nlink !== 1) {
    throw new Error(`拒绝覆盖不安全的 MCP bridge 文件：${path.basename(target)}`)
  }
  assertOwned(stat, 'MCP bridge 文件')
  if ((stat.mode & 0o077) !== 0) throw new Error('MCP bridge 文件权限过宽')
  return true
}

function atomicWriteSecureFile(target, content) {
  const directory = ensureSecureRunDirectory(path.dirname(target))
  assertSafeExistingFile(target)
  const temporary = path.join(directory, `.${path.basename(target)}.${randomUUID()}.tmp`)
  const flags = fs.constants.O_WRONLY
    | fs.constants.O_CREAT
    | fs.constants.O_EXCL
    | (fs.constants.O_NOFOLLOW || 0)
    | (fs.constants.O_CLOEXEC || 0)
  let descriptor
  try {
    descriptor = fs.openSync(temporary, flags, 0o600)
    fs.fchmodSync(descriptor, 0o600)
    fs.writeFileSync(descriptor, content, { encoding: 'utf8' })
    fs.fsyncSync(descriptor)
    fs.closeSync(descriptor)
    descriptor = undefined
    fs.renameSync(temporary, target)
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor)
    try {
      fs.unlinkSync(temporary)
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
  }
}

function safeUnlinkSecureFile(target) {
  if (!assertSafeExistingFile(target)) return
  fs.unlinkSync(target)
}

function validatedLoopbackApiBase(value) {
  const parsed = new URL(value)
  const hostAllowed = parsed.hostname === '127.0.0.1' || parsed.hostname === '[::1]'
  if (
    parsed.protocol !== 'http:'
    || !hostAllowed
    || !parsed.port
    || parsed.username
    || parsed.password
    || parsed.search
    || parsed.hash
    || !['/api', '/api/'].includes(parsed.pathname)
  ) {
    throw new Error('MCP bridge API 必须是明确端口的本机回环地址')
  }
  return `${parsed.protocol}//${parsed.host}/api`
}

function leasePayload(session) {
  return JSON.stringify({
    session_id: session.sessionId,
    updated_at: Date.now() / 1000,
    api_base: session.apiBase,
  }) + '\n'
}

function createMcpBridgeSession(runDir, apiBase = 'http://127.0.0.1:8000/api') {
  const canonicalApiBase = validatedLoopbackApiBase(apiBase)
  const directory = ensureSecureRunDirectory(runDir)
  const tokenFile = path.join(directory, TOKEN_FILENAME)
  const leaseFile = path.join(directory, LEASE_FILENAME)
  safeUnlinkSecureFile(leaseFile)
  safeUnlinkSecureFile(tokenFile)
  const session = {
    token: randomBytes(32).toString('base64url'),
    sessionId: randomUUID(),
    tokenFile,
    leaseFile,
    apiBase: canonicalApiBase,
  }
  try {
    atomicWriteSecureFile(tokenFile, `${session.token}\n`)
    atomicWriteSecureFile(leaseFile, leasePayload(session))
  } catch (error) {
    try { safeUnlinkSecureFile(leaseFile) } catch { /* preserve the creation failure */ }
    try { safeUnlinkSecureFile(tokenFile) } catch { /* preserve the creation failure */ }
    throw error
  }
  return session
}

function refreshMcpBridgeLease(session) {
  atomicWriteSecureFile(session.leaseFile, leasePayload(session))
}

function removeMcpBridgeSession(session) {
  if (!session) return
  safeUnlinkSecureFile(session.leaseFile)
  safeUnlinkSecureFile(session.tokenFile)
}

module.exports = {
  LEASE_HEARTBEAT_MS,
  atomicWriteSecureFile,
  createMcpBridgeSession,
  ensureSecureRunDirectory,
  refreshMcpBridgeLease,
  removeMcpBridgeSession,
  validatedLoopbackApiBase,
}
