export function discoveryInputHint(value, strategy = 'direct') {
  const text = String(value || '').trim()
  if (strategy === 'seed') {
    if (!text) return '粘贴一篇种子文章，将从公开搜索发现同公众号候选'
    const urls = text.match(/https?:\/\/(?:mp\.weixin\.qq\.com|mp\.wechat\.qq\.com)\/[^\s]+/gi) || []
    if (urls.length === 1 && /\/s(?:[/?]|$)/i.test(urls[0])) {
      return '将先验证种子身份，再搜索并严格校验同一公众号候选'
    }
    return '种子扩展一次需要且只能使用一篇公众号文章链接'
  }
  if (!text) return '支持文章链接、多行批量链接或一个公众号合集链接'
  const urls = text.match(/https?:\/\/(?:mp\.weixin\.qq\.com|mp\.wechat\.qq\.com)\/[^\s]+/gi) || []
  if (isWechatAlbumInput(text)) {
    return '已识别为公众号合集，将逐页发现并校验合集文章'
  }
  if (urls.length) return `已识别 ${urls.length} 个微信链接，将逐条校验后导入`
  return '没有识别到微信文章或合集链接'
}

export function isWechatAlbumInput(value) {
  const text = String(value || '').trim()
  const urls = text.match(/https?:\/\/(?:mp\.weixin\.qq\.com|mp\.wechat\.qq\.com)\/[^\s]+/gi) || []
  return urls.length === 1 && /\/mp\/appmsgalbum(?:[/?]|$)/i.test(urls[0])
}

export function albumSourceScheduleText(source, formatter = defaultDateTimeFormatter) {
  if (!source?.enabled) return '自动检测已暂停'
  if (source?.last_error) return `上次检查失败：${source.last_error}`
  if (source?.next_sync_at) return `下次检查 ${formatter(source.next_sync_at)}`
  return '等待后台检查'
}

function defaultDateTimeFormatter(value) {
  const timestamp = Date.parse(value || '')
  if (!Number.isFinite(timestamp)) return '稍后'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(timestamp)
}

export function discoveryRunStatusLabel(status) {
  return {
    queued: '等待开始',
    running: '正在处理',
    succeeded: '导入完成',
    failed: '导入失败',
    cancelled: '已取消'
  }[status] || '未知状态'
}

export function discoveryRunDisplayStatus(run) {
  if (['queued', 'running'].includes(run?.review_import_status)) return '正在导入选中项'
  if (run?.review_required) return '等待确认'
  return discoveryRunStatusLabel(run?.status)
}

export function discoveryRunSummary(run) {
  const candidates = Number(run?.candidate_count || 0)
  const verified = Number(run?.verified_count || 0)
  const imported = Number(run?.imported_count || 0)
  const duplicates = Number(run?.duplicate_count || 0)
  const failed = Number(run?.failed_count || 0)
  return `发现 ${candidates} · 校验 ${verified} · 新增 ${imported} · 重复 ${duplicates} · 失败 ${failed}`
}
