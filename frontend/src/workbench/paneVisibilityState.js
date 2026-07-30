export function normalizeWorkspacePaneVisibility(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {}

  return {
    primary: typeof source.primary === 'boolean' ? source.primary : true,
    context: typeof source.context === 'boolean' ? source.context : true,
  }
}
