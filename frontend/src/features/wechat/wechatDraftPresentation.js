export function wechatDraftTaskStageLabel(stage) {
  return ({
    queued: '正在排队',
    starting: '正在准备草稿',
    checking_wechat_ip: '正在检查公众号 IP 白名单',
    preparing_report: '正在准备报告正文',
    exporting_public_report: '正在导出公开阅读页',
    deploying_public_site: '正在部署公开阅读页',
    verifying_public_link: '正在校验阅读原文链接',
    requesting_wechat_token: '正在连接微信公众号',
    wechat_connection_verified: '公众号连接已验证',
    uploading_cover: '正在上传文章封面',
    creating_wechat_draft: '正在创建公众号草稿',
    completed: '草稿已创建',
    already_created: '草稿已创建',
    interrupted: '任务已中断',
    failed: '任务未完成',
  })[String(stage || '')] || '正在处理中'
}

export function wechatDraftSubmitState(context = {}) {
  const taskRunning = ['queued', 'running'].includes(context.task?.status)
  const alreadyCreated = (
    ['draft_created', 'published'].includes(context.latestPublication?.status)
    && context.latestPublication?.is_current_source === true
  )
  const disabled = (
    Boolean(context.loadingDefaults)
    || context.ipPreflight?.can_submit !== true
    || taskRunning
    || alreadyCreated
    || !String(context.title || '').trim()
    || !context.coverUrl
  )
  const label = alreadyCreated
    ? '草稿已创建'
    : context.task?.status === 'failed' ? '重新存入草稿箱' : '存入草稿箱'
  return { alreadyCreated, disabled, label, taskRunning }
}

export function truncateWechatDigest(value, maxBytes = 120) {
  const text = String(value || '').trim()
  const encoder = new TextEncoder()
  let bytes = 0
  let output = ''
  for (const character of text) {
    const size = encoder.encode(character).length
    if (bytes + size > maxBytes) break
    output += character
    bytes += size
  }
  return output
}
