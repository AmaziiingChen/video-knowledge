export function shouldKeepScheduleEditorOpen({
  timePickerOpen = false,
  timePickerClosing = false,
} = {}) {
  return Boolean(timePickerOpen || timePickerClosing)
}
