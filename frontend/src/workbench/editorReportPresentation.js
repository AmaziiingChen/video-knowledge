export function createEditorReportPresentation({ contentForTab, workspaceTabById }) {
  function reportTitle(tabId) {
    return contentForTab(tabId)?.title || workspaceTabById(tabId)?.title || ''
  }

  function reportTypeLabel(tabId) {
    return reportTitle(tabId).includes('周报') ? '周报' : '日报'
  }

  function reportDisplayTitle(tabId) {
    const title = reportTitle(tabId)
    const groupName = title.includes('｜') ? title.split('｜').pop()?.trim() : ''
    return groupName ? `${groupName}${reportTypeLabel(tabId)}` : title
  }

  function reportDateLabel(tabId) {
    const dates = reportTitle(tabId).match(/\d{4}-\d{2}-\d{2}/g) || []
    if (!dates.length) return '生成报告'
    const formatDate = (value, showYear) => {
      const [year, month, day] = value.split('-').map(Number)
      return `${showYear ? `${year}年` : ''}${month}月${day}日`
    }
    if (dates.length === 1) return formatDate(dates[0], true)
    const sameYear = dates[0].slice(0, 4) === dates[1].slice(0, 4)
    return `${formatDate(dates[0], true)}—${formatDate(dates[1], !sameYear)}`
  }

  function reportGeneratedLabel(tabId) {
    const timestamp = contentForTab(tabId)?.created_at || workspaceTabById(tabId)?.opened_at
    if (!timestamp) return ''
    const date = new Date(timestamp)
    if (Number.isNaN(date.getTime())) return ''
    const hour = String(date.getHours()).padStart(2, '0')
    const minute = String(date.getMinutes()).padStart(2, '0')
    return `生成于 ${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${hour}:${minute}`
  }

  return { reportDateLabel, reportDisplayTitle, reportGeneratedLabel, reportTypeLabel }
}
