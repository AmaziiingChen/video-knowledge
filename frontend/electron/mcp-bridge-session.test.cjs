const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')

const {
  createMcpBridgeSession,
  refreshMcpBridgeLease,
  removeMcpBridgeSession,
} = require('./mcp-bridge-session.cjs')

function temporaryDirectory() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'knowledgehub-mcp-session-'))
}

test('creates, refreshes and removes a private per-session capability', () => {
  const root = temporaryDirectory()
  const runDir = path.join(root, 'run')
  try {
    const session = createMcpBridgeSession(runDir)
    const tokenStat = fs.lstatSync(session.tokenFile)
    const leaseStat = fs.lstatSync(session.leaseFile)
    const firstLease = JSON.parse(fs.readFileSync(session.leaseFile, 'utf8'))

    assert.equal(fs.lstatSync(runDir).mode & 0o777, 0o700)
    assert.equal(tokenStat.mode & 0o777, 0o600)
    assert.equal(leaseStat.mode & 0o777, 0o600)
    assert.match(fs.readFileSync(session.tokenFile, 'utf8').trim(), /^[A-Za-z0-9_-]{43}$/)
    assert.equal(firstLease.session_id, session.sessionId)
    assert.equal(firstLease.api_base, 'http://127.0.0.1:8000/api')

    refreshMcpBridgeLease(session)
    const secondLease = JSON.parse(fs.readFileSync(session.leaseFile, 'utf8'))
    assert.ok(secondLease.updated_at >= firstLease.updated_at)

    removeMcpBridgeSession(session)
    assert.equal(fs.existsSync(session.tokenFile), false)
    assert.equal(fs.existsSync(session.leaseFile), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('refuses to replace a symlink or broadly readable stale capability', () => {
  const root = temporaryDirectory()
  const runDir = path.join(root, 'run')
  fs.mkdirSync(runDir, { mode: 0o700 })
  const target = path.join(root, 'target')
  fs.writeFileSync(target, 'do-not-touch')
  fs.symlinkSync(target, path.join(runDir, 'mcp-bridge-token'))
  try {
    assert.throws(() => createMcpBridgeSession(runDir), /拒绝覆盖不安全/)
    assert.equal(fs.readFileSync(target, 'utf8'), 'do-not-touch')

    fs.unlinkSync(path.join(runDir, 'mcp-bridge-token'))
    fs.writeFileSync(path.join(runDir, 'mcp-bridge-token'), 'stale', { mode: 0o644 })
    assert.throws(() => createMcpBridgeSession(runDir), /权限过宽/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('refuses to issue a session for a non-loopback API endpoint', () => {
  const root = temporaryDirectory()
  try {
    assert.throws(
      () => createMcpBridgeSession(path.join(root, 'run'), 'https://attacker.invalid/api'),
      /本机回环地址/,
    )
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
