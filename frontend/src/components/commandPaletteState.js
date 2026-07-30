function searchText(value) {
  return String(value || '').trim().toLocaleLowerCase()
}

export function commandItemSearchText(item = {}) {
  return [item.title, item.subtitle, item.group, ...(Array.isArray(item.keywords) ? item.keywords : [])]
    .map(searchText)
    .filter(Boolean)
    .join(' ')
}

export function filterCommandItems(items = [], query = '') {
  const terms = searchText(query).split(/\s+/).filter(Boolean)
  if (!terms.length) return [...items]
  return items.filter((item) => {
    const haystack = commandItemSearchText(item)
    return terms.every((term) => haystack.includes(term))
  })
}
