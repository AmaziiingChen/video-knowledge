import { readonly, ref } from 'vue'

const activeDestructiveConfirmation = ref(null)

export const destructiveConfirmation = readonly(activeDestructiveConfirmation)

export function requestDestructiveConfirmation({
  title = '删除项目',
  message = '',
  confirmLabel = '删除',
  cancelLabel = '保留',
} = {}) {
  return new Promise((resolve) => {
    activeDestructiveConfirmation.value?.resolve(false)
    activeDestructiveConfirmation.value = {
      title,
      message,
      confirmLabel,
      cancelLabel,
      resolve,
    }
  })
}

export function settleDestructiveConfirmation(confirmed) {
  const current = activeDestructiveConfirmation.value
  activeDestructiveConfirmation.value = null
  current?.resolve(Boolean(confirmed))
}
