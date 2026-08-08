function backendSpawnOptions(platform = process.platform) {
  // Give the local backend its own process group. This lets Electron stop the
  // server and any child media workers without touching another app.
  return { detached: platform !== 'win32' }
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
  backendSpawnOptions,
  terminateBackendProcess,
}
