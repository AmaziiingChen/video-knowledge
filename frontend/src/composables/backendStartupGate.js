export async function waitForDesktopBackend(waitForBackend) {
  if (typeof waitForBackend !== 'function') return
  await Promise.resolve().then(() => waitForBackend())
}
