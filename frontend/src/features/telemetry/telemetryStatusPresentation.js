export function telemetryStatusPresentation({
  enabled = false,
  pendingEvents = 0,
  loading = false,
  loaded = false,
  error = '',
  uploadResult = '',
  lastAttemptAt = '',
  lastSuccessAt = '',
} = {}) {
  if (loading) return { label: '正在读取', tone: 'is-idle', description: '正在读取当前诊断状态。' }
  if (error) return { label: '状态不可用', tone: 'is-invalid', description: error }
  if (!loaded) return { label: '尚未读取', tone: 'is-idle', description: '正在读取当前诊断状态。' }
  if (!enabled) return { label: '已关闭', tone: 'is-idle', description: '诊断已关闭，本机待发送数据已清除。' }
  const pending = pendingEvents > 0 ? `本机有 ${pendingEvents} 条待发送事件。` : '本机没有待发送事件。'
  if (uploadResult === 'failed') {
    return { label: '连接失败', tone: 'is-invalid', description: `${pending}上次连接 Cloudflare 失败，应用会自动重试。` }
  }
  const completedAt = lastSuccessAt || lastAttemptAt
  const description = completedAt
    ? `${pending}上次检查：${new Date(completedAt).toLocaleString('zh-CN', { hour12: false })}。`
    : `${pending}应用启动后会低频自动上传，也可立即重试。`
  return {
    label: pendingEvents > 0 ? '等待上传' : '已同步',
    tone: pendingEvents > 0 ? 'is-warning' : 'is-valid',
    description,
  }
}
