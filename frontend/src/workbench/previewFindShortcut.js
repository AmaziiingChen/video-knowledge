export function isPreviewFindShortcut(event) {
  return Boolean(
    (event?.metaKey || event?.ctrlKey)
    && !event?.altKey
    && String(event?.key || '').toLocaleLowerCase() === 'f'
  )
}
