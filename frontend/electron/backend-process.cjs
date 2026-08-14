const fs = require('fs')
const path = require('path')

function backendSpawnOptions(platform = process.platform) {
  // Give the local backend its own process group. This lets Electron stop the
  // server and any child media workers without touching another app.
  return { detached: platform !== 'win32' }
}

function backendStartupAction({ health, hasManagedProcess, hasBridgeSession }) {
  if (health?.ready) {
    return hasManagedProcess && hasBridgeSession ? 'reuse' : 'replace-stale'
  }
  return health?.reachable ? 'reject-occupied' : 'start'
}

function backendLeasePath(runDir) {
  return path.join(runDir, 'backend-process.json')
}

function writeBackendLease(runDir, child, { fileSystem = fs } = {}) {
  const pid = Number(child?.pid)
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    fileSystem.mkdirSync(runDir, { recursive: true })
    fileSystem.writeFileSync(
      backendLeasePath(runDir),
      JSON.stringify({ pid, created_at: new Date().toISOString() }),
      { encoding: 'utf8', mode: 0o600 },
    )
    return true
  } catch {
    return false
  }
}

function clearBackendLease(runDir, pid = null, { fileSystem = fs } = {}) {
  const leasePath = backendLeasePath(runDir)
  try {
    if (pid !== null) {
      const parsed = JSON.parse(fileSystem.readFileSync(leasePath, 'utf8'))
      if (Number(parsed?.pid) !== Number(pid)) return false
    }
    fileSystem.unlinkSync(leasePath)
    return true
  } catch (error) {
    return error?.code === 'ENOENT'
  }
}

function readBackendLease(runDir, { fileSystem = fs } = {}) {
  try {
    const parsed = JSON.parse(fileSystem.readFileSync(backendLeasePath(runDir), 'utf8'))
    const pid = Number(parsed?.pid)
    return Number.isInteger(pid) && pid > 0 ? { pid } : null
  } catch {
    return null
  }
}

function terminateLeasedBackend(runDir, {
  fileSystem = fs,
  isExpectedBackendProcess = () => false,
  ...options
} = {}) {
  const lease = readBackendLease(runDir, { fileSystem })
  if (!lease) return false
  // A PID can eventually be reused. Only terminate a process that has both
  // our private lease and an explicit KnowledgeHub-backend identity.
  if (!isExpectedBackendProcess(lease.pid)) {
    clearBackendLease(runDir, null, { fileSystem })
    return false
  }
  const stopped = terminateBackendProcess(lease, options)
  clearBackendLease(runDir, null, { fileSystem })
  return stopped
}

function terminateBackendProcess(child, {
  platform = process.platform,
  kill = process.kill,
} = {}) {
  const pid = Number(child?.pid)
  if (!Number.isInteger(pid) || pid <= 0) return false

  try {
    kill(platform === 'win32' ? pid : -pid, 'SIGTERM')
    return true
  } catch (error) {
    // The process may have already exited between Electron's shutdown event
    // and this cleanup attempt. That is a successful terminal state.
    return error?.code === 'ESRCH'
  }
}

module.exports = {
  backendStartupAction,
  backendSpawnOptions,
  backendLeasePath,
  clearBackendLease,
  readBackendLease,
  terminateBackendProcess,
  terminateLeasedBackend,
  writeBackendLease,
}
