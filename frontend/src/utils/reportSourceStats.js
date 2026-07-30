export function extractReportSourceStats(markdown) {
  const source = String(markdown || '')
  const analyzedMatch = source.match(/(?:分析文章|来源文章)\s*[：:]\s*(\d+)\s*篇/)
  const referencedMatch = source.match(/(?:正文引用|参考文章|引用文章)\s*[：:]\s*(\d+)\s*篇/)
  const referencedDefinitionIds = new Set(
    Array.from(source.matchAll(/^\[\^([A-Za-z0-9_-]+)\]:/gm), (match) => match[1])
  )
  return {
    analyzed: analyzedMatch ? Number(analyzedMatch[1]) : 0,
    referenced: referencedMatch ? Number(referencedMatch[1]) : referencedDefinitionIds.size,
  }
}
