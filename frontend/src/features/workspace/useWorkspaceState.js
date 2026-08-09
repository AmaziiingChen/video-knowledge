import { reactive, ref, watch } from 'vue'
import { clampPanePercent, clampPaneWidth } from '../../workbench/workspaceModel'

const WORKSPACE_TABS_KEY = 'video-knowledge.workspace-tabs.v1'
const WORKSPACE_LAYOUT_KEY = 'video-knowledge.workspace-layout.v1'

export function useWorkspaceState() {
  const workspaceTabs = ref([])
  const activeWorkspaceTabId = ref('')
  const workspaceLayout = reactive({
    primary: 22,
    editor: 50,
    context: 28
  })
  let workspaceLayoutPersistTimer = null

  function normalizeWorkspaceLayout() {
    workspaceLayout.primary = clampPanePercent(workspaceLayout.primary, 8, 45, 22)
    workspaceLayout.context = clampPanePercent(workspaceLayout.context, 12, 65, 28)
    if (workspaceLayout.primary + workspaceLayout.context > 82) {
      workspaceLayout.context = clampPanePercent(82 - workspaceLayout.primary, 12, 65, 28)
    }
    workspaceLayout.editor = clampPanePercent(
      100 - workspaceLayout.primary - workspaceLayout.context,
      18,
      80,
      50
    )
  }

  function restoreWorkspaceState() {
    try {
      const savedTabs = JSON.parse(localStorage.getItem(WORKSPACE_TABS_KEY) || '{}')
      workspaceTabs.value = Array.isArray(savedTabs.tabs) ? savedTabs.tabs.filter((tab) => tab?.id) : []
      activeWorkspaceTabId.value = workspaceTabs.value.some((tab) => tab.id === savedTabs.activeTabId)
        ? savedTabs.activeTabId
        : workspaceTabs.value[0]?.id || ''
    } catch {
      workspaceTabs.value = []
      activeWorkspaceTabId.value = ''
    }

    try {
      const savedLayout = JSON.parse(localStorage.getItem(WORKSPACE_LAYOUT_KEY) || '{}')
      if (Number.isFinite(Number(savedLayout.primary))) {
        workspaceLayout.primary = clampPanePercent(Number(savedLayout.primary), 8, 45, 22)
        workspaceLayout.context = clampPanePercent(Number(savedLayout.context), 12, 65, 28)
        workspaceLayout.editor = clampPanePercent(
          100 - workspaceLayout.primary - workspaceLayout.context,
          18,
          80,
          50
        )
      } else if (Number.isFinite(Number(savedLayout.left)) || Number.isFinite(Number(savedLayout.right))) {
        const left = clampPaneWidth(Number(savedLayout.left), 120, 680, 250)
        const right = clampPaneWidth(Number(savedLayout.right), 220, 980, 340)
        const total = Math.max(1024, left + right + 520)
        workspaceLayout.primary = clampPanePercent((left / total) * 100, 8, 45, 22)
        workspaceLayout.context = clampPanePercent((right / total) * 100, 12, 65, 28)
        workspaceLayout.editor = clampPanePercent(
          100 - workspaceLayout.primary - workspaceLayout.context,
          18,
          80,
          50
        )
      }
    } catch {
      workspaceLayout.primary = 22
      workspaceLayout.editor = 50
      workspaceLayout.context = 28
    }
    normalizeWorkspaceLayout()
  }

  function persistWorkspaceTabs() {
    localStorage.setItem(WORKSPACE_TABS_KEY, JSON.stringify({
      tabs: workspaceTabs.value,
      activeTabId: activeWorkspaceTabId.value
    }))
  }

  function writeWorkspaceLayout() {
    localStorage.setItem(WORKSPACE_LAYOUT_KEY, JSON.stringify({
      primary: workspaceLayout.primary,
      editor: workspaceLayout.editor,
      context: workspaceLayout.context
    }))
  }

  function persistWorkspaceLayout() {
    if (workspaceLayoutPersistTimer) clearTimeout(workspaceLayoutPersistTimer)
    workspaceLayoutPersistTimer = setTimeout(() => {
      workspaceLayoutPersistTimer = null
      writeWorkspaceLayout()
    }, 180)
  }

  function handleWorkspaceResize(payload) {
    const panes = payload?.panes || []
    if (panes.length === 2) {
      workspaceLayout.primary = clampPanePercent(panes[0].size, 8, 45, workspaceLayout.primary)
      workspaceLayout.editor = clampPanePercent(panes[1].size, 50, 92, workspaceLayout.editor)
      return
    }
    if (panes.length < 3) return
    workspaceLayout.primary = clampPanePercent(panes[0].size, 8, 45, workspaceLayout.primary)
    workspaceLayout.editor = clampPanePercent(panes[1].size, 18, 80, workspaceLayout.editor)
    workspaceLayout.context = clampPanePercent(panes[2].size, 12, 65, workspaceLayout.context)
    normalizeWorkspaceLayout()
  }

  watch(workspaceTabs, persistWorkspaceTabs, { deep: true })
  watch(activeWorkspaceTabId, persistWorkspaceTabs)
  watch(workspaceLayout, persistWorkspaceLayout)

  return {
    workspaceTabs,
    activeWorkspaceTabId,
    workspaceLayout,
    restoreWorkspaceState,
    handleWorkspaceResize
  }
}
