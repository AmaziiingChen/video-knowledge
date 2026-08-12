const FALLBACK_BASE_URL = './'

export function macosSymbolAssetPath(iconAsset) {
  const directory = iconAsset?.kind === 'brand'
    ? 'brand-icons'
    : 'generated/sf-symbols'
  return `${directory}/${iconAsset.asset}`
}

export function resolveMacosSymbolAssetUrl(iconAsset, baseUrl = globalThis.document?.baseURI) {
  const assetPath = macosSymbolAssetPath(iconAsset)
  try {
    return new URL(assetPath, baseUrl).href
  } catch {
    return `${FALLBACK_BASE_URL}${assetPath}`
  }
}
