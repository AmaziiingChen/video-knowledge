function compactDiscoveryItem(item) {
  return {
    fakeid: String(item?.fakeid || ''),
    name: String(item?.name || '').slice(0, 120),
    description: String(item?.description || '').slice(0, 300),
    avatar_url: String(item?.avatar_url || '').slice(0, 1000)
  }
}

export function normalizeDiscoveryHistory(value) {
  if (!Array.isArray(value)) return []
  return value
    .filter((entry) => entry && typeof entry === 'object' && String(entry.query || '').trim())
    .map((entry) => ({
      query: String(entry.query).trim().slice(0, 80),
      searched_at: String(entry.searched_at || ''),
      results: (Array.isArray(entry.results) ? entry.results : [])
        .map(compactDiscoveryItem)
        .filter((item) => item.fakeid && item.name)
        .slice(0, 10)
    }))
    .slice(0, 6)
}

export function recordDiscovery(history, rawQuery, results, searchedAt = new Date().toISOString()) {
  const query = String(rawQuery || '').trim().slice(0, 80)
  if (!query) return normalizeDiscoveryHistory(history)
  const entry = normalizeDiscoveryHistory([{
    query,
    searched_at: searchedAt,
    results
  }])[0]
  return normalizeDiscoveryHistory([
    entry,
    ...normalizeDiscoveryHistory(history).filter((item) => item.query !== query)
  ])
}

export function discoveryRecommendations(history, subscriptions, limit = 6) {
  const subscribedFakeids = new Set(
    (Array.isArray(subscriptions) ? subscriptions : [])
      .map((subscription) => String(subscription?.fakeid || ''))
      .filter(Boolean)
  )
  const seen = new Set()
  const recommendations = []
  for (const entry of normalizeDiscoveryHistory(history)) {
    for (const item of entry.results) {
      if (subscribedFakeids.has(item.fakeid) || seen.has(item.fakeid)) continue
      seen.add(item.fakeid)
      recommendations.push(item)
      if (recommendations.length >= limit) return recommendations
    }
  }
  return recommendations
}
