import { nextTick, ref } from 'vue'

/**
 * Owns the local editing and import gestures for the library tree. Persisting
 * or deleting the resulting data remains an explicit parent event.
 */
export function useLibraryNodeEditingController({
  openFolderIds,
  selectedKeys,
  selectedNodes,
  saveOpenFolderIds,
  emit,
}) {
  const editingNode = ref(null)
  const editingInput = ref(null)
  const markdownImportInput = ref(null)

  function focusEditingInput() {
    nextTick(() => {
      const target = Array.isArray(editingInput.value) ? editingInput.value.at(-1) : editingInput.value
      target?.focus()
      target?.select()
    })
  }

  function startNewFolder(parentFolderId) {
    if (parentFolderId) {
      const next = new Set(openFolderIds.value)
      next.add(String(parentFolderId))
      openFolderIds.value = next
      saveOpenFolderIds(next)
    }
    editingNode.value = {
      type: 'folder',
      id: `new:${Date.now()}`,
      value: '新建文件夹',
      isNew: true,
      parentFolderId: parentFolderId || null,
    }
    focusEditingInput()
  }

  function chooseMarkdownFile() {
    markdownImportInput.value?.click()
  }

  function importMarkdownFile(event) {
    const files = Array.from(event.target?.files || [])
    if (!files.length) return
    const targetFolder = selectedNodes.value.find((node) => node.type === 'folder')
    emit('import-markdown', {
      files,
      libraryFolderId: targetFolder?.id || null,
    })
    event.target.value = ''
  }

  function importDroppedFiles(event) {
    const files = Array.from(event.dataTransfer?.files || [])
    if (!files.length) return
    const targetFolder = selectedNodes.value.find((node) => node.type === 'folder')
    emit('import-markdown', { files, libraryFolderId: targetFolder?.id || null })
  }

  function startRename(node) {
    editingNode.value = {
      type: node.type,
      id: node.id,
      value: node.name,
      isNew: false,
    }
    focusEditingInput()
  }

  function isEditing(node) {
    return editingNode.value && !editingNode.value.isNew && editingNode.value.type === node.type && editingNode.value.id === node.id
  }

  function cancelEditing() {
    editingNode.value = null
  }

  function commitEditing() {
    const current = editingNode.value
    const value = current?.value?.trim()
    if (!current || !value) {
      cancelEditing()
      return
    }

    if (current.isNew) {
      emit('create-folder', {
        name: value,
        parent_folder_id: current.parentFolderId,
      })
    } else if (current.type === 'folder') {
      emit('rename-folder', { id: current.id, name: value })
    } else {
      emit('rename-content', { id: current.id, title: value })
    }
    editingNode.value = null
  }

  function requestDelete(node) {
    if (node.type === 'folder') {
      emit('delete-folder', node.raw)
    } else {
      emit('delete-content', node.raw)
    }
  }

  function requestDeleteSelected() {
    if (!selectedNodes.value.length) return
    emit('delete-selected', selectedNodes.value.map((node) => {
      const type = node.type === 'unread-content' ? 'content' : node.type
      if (node.raw) return { ...node.raw, type }
      return type === node.type ? node : { ...node, type }
    }))
    selectedKeys.value = new Set()
  }

  return {
    editingNode,
    editingInput,
    markdownImportInput,
    startNewFolder,
    chooseMarkdownFile,
    importMarkdownFile,
    importDroppedFiles,
    startRename,
    isEditing,
    commitEditing,
    cancelEditing,
    requestDelete,
    requestDeleteSelected,
  }
}
