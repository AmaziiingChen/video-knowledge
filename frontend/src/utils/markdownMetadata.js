export function stripMarkdownMetadata(markdown) {
  return String(markdown || '').replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, '').trimStart()
}
