import { localApiAuthHeaders, localApiRequestUrl } from '../../utils/localApiAuth.js'

export async function consumeReportEventStream(url, payload, onProgress, {
  request = fetch,
  requestUrl = localApiRequestUrl,
  authHeaders = localApiAuthHeaders,
} = {}) {
  const response = await request(requestUrl(url), {
    method: 'POST',
    headers: await authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    let detail = `报告生成服务返回 ${response.status}`
    try {
      const errorPayload = await response.json()
      detail = errorPayload?.detail || detail
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(detail)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let result = null
  let streamError = ''

  const handleBlock = (block) => {
    const data = block.split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (event.event === 'progress') onProgress?.(event)
    if (event.event === 'complete') result = event.result || {}
    if (event.event === 'error') streamError = event.message || '报告生成失败'
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) handleBlock(block)
    if (done) break
  }
  if (buffer.trim()) handleBlock(buffer)
  if (streamError) throw new Error(streamError)
  if (!result) throw new Error('报告生成连接已结束，但没有收到完成结果')
  return result
}
