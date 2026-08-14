<template>
  <aside class="file-sidebar" :class="{ 'prompt-sidebar': activeView === 'prompts' }">
    <LibrarySidebar
      ref="librarySidebar"
      :active="activeView === 'library'"
      v-bind="libraryProps"
      @update:search-query="emit('update:searchQuery', $event)"
      @update:share-text="emit('update:shareText', $event)"
      @update:search-scope="emit('update:search-scope', $event)"
      @search="emit('search')"
      @clear-search="emit('clear-search')"
      @input-change="emit('input-change')"
      @run-full-pipeline="emit('run-full-pipeline')"
      @open-content="emit('open-content', $event)"
      @create-folder="emit('create-folder', $event)"
      @rename-folder="emit('rename-folder', $event)"
      @set-folder-pinned="emit('set-folder-pinned', $event)"
      @delete-folder="emit('delete-folder', $event)"
      @rename-content="emit('rename-content', $event)"
      @delete-content="emit('delete-content', $event)"
      @move-node="emit('move-node', $event)"
      @move-nodes="emit('move-nodes', $event)"
      @delete-selected="emit('delete-selected', $event)"
      @set-content-viewed="emit('set-content-viewed', $event)"
      @reveal-library-node="emit('reveal-library-node', $event)"
      @load-folder-history="emit('load-folder-history', $event)"
      @retry-content-pages="emit('retry-content-pages')"
      @import-markdown="emit('import-markdown', $event)"
      @load-trash="emit('load-trash')"
      @restore-trash="emit('restore-trash', $event)"
      @permanently-delete-trash="emit('permanently-delete-trash', $event)"
      @empty-trash="emit('empty-trash')"
    />

    <PromptFileTree
      v-if="activeView === 'prompts'"
      :task-options="promptTaskOptions"
      :folders="promptFolders"
      :templates="promptTemplates"
      :report-prompts="wechatReportPrompts"
      :system-prompts="systemPrompts"
      :prompt-contexts="promptContexts"
      :active-node-id="activePromptNodeId"
      :trash-entries="promptTrashEntries"
      :loading-trash="loadingPromptTrash"
      @open-prompt="emit('open-prompt', $event)"
      @open-system-prompt="emit('open-system-prompt', $event)"
      @open-prompt-context="emit('open-prompt-context', $event)"
      @create-folder="emit('create-prompt-folder', $event)"
      @create-prompt="emit('create-prompt-file', $event)"
      @rename-folder="emit('rename-prompt-folder', $event)"
      @rename-prompt="emit('rename-prompt-file', $event)"
      @rename-report-prompt="emit('rename-report-prompt-file', $event)"
      @delete-folder="emit('delete-prompt-folder', $event)"
      @delete-prompt="emit('delete-prompt-file', $event)"
      @move-node="emit('move-prompt-node', $event)"
      @load-trash="emit('load-prompt-trash')"
      @restore-trash="emit('restore-prompt-trash', $event)"
      @permanently-delete-trash="emit('permanently-delete-prompt-trash', $event)"
    />
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import LibrarySidebar from './LibrarySidebar.vue'
import PromptFileTree from './PromptFileTree.vue'

const props = defineProps({
  activeView: { type: String, required: true },
  libraryMode: { type: String, default: 'files' },
  searchScope: { type: String, default: 'all' },
  searchQuery: { type: String, default: '' },
  shareText: { type: String, default: '' },
  running: { type: Boolean, default: false },
  result: { type: Object, default: () => ({}) },
  sidebarTreeItems: { type: Array, default: () => [] },
  libraryContentItems: { type: Array, default: () => [] },
  libraryContentLoadStatus: { type: Object, default: () => ({ state: 'idle', loaded: 0, total: 0 }) },
  viewedContentIds: { type: Array, default: () => [] },
  explicitlyUnreadContentIds: { type: Array, default: () => [] },
  contentViewedBefore: { type: String, default: '' },
  libraryFolders: { type: Array, default: () => [] },
  folderHistoryStates: { type: Object, default: () => ({}) },
  revealedLibraryFolderIds: { type: Array, default: () => [] },
  trashEntries: { type: Array, default: () => [] },
  loadingTrash: { type: Boolean, default: false },
  selectedContentItem: { type: Object, default: null },
  promptTaskOptions: { type: Array, default: () => [] },
  promptTemplates: { type: Array, default: () => [] },
  promptFolders: { type: Array, default: () => [] },
  wechatReportPrompts: { type: Array, default: () => [] },
  systemPrompts: { type: Array, default: () => [] },
  promptContexts: { type: Array, default: () => [] },
  activePromptNodeId: { type: String, default: '' },
  promptTrashEntries: { type: Array, default: () => [] },
  loadingPromptTrash: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:searchQuery',
  'update:search-scope',
  'update:shareText',
  'search',
  'clear-search',
  'input-change',
  'run-full-pipeline',
  'open-content',
  'create-folder',
  'rename-folder',
  'set-folder-pinned',
  'delete-folder',
  'rename-content',
  'delete-content',
  'move-node',
  'move-nodes',
  'delete-selected',
  'set-content-viewed',
  'reveal-library-node',
  'load-folder-history',
  'retry-content-pages',
  'import-markdown',
  'load-trash',
  'restore-trash',
  'permanently-delete-trash',
  'empty-trash',
  'open-prompt',
  'open-system-prompt',
  'open-prompt-context',
  'create-prompt-folder',
  'create-prompt-file',
  'rename-prompt-folder',
  'rename-prompt-file',
  'rename-report-prompt-file',
  'delete-prompt-folder',
  'delete-prompt-file',
  'move-prompt-node',
  'load-prompt-trash',
  'restore-prompt-trash',
  'permanently-delete-prompt-trash',
])

const librarySidebar = ref(null)
const libraryProps = computed(() => ({
  libraryMode: props.libraryMode,
  searchScope: props.searchScope,
  searchQuery: props.searchQuery,
  shareText: props.shareText,
  running: props.running,
  result: props.result,
  sidebarTreeItems: props.sidebarTreeItems,
  libraryContentItems: props.libraryContentItems,
  libraryContentLoadStatus: props.libraryContentLoadStatus,
  viewedContentIds: props.viewedContentIds,
  explicitlyUnreadContentIds: props.explicitlyUnreadContentIds,
  contentViewedBefore: props.contentViewedBefore,
  libraryFolders: props.libraryFolders,
  folderHistoryStates: props.folderHistoryStates,
  revealedLibraryFolderIds: props.revealedLibraryFolderIds,
  trashEntries: props.trashEntries,
  loadingTrash: props.loadingTrash,
  selectedContentItem: props.selectedContentItem,
}))

defineExpose({
  focusLibrarySearch: () => librarySidebar.value?.focusLibrarySearch?.(),
  showLibrarySearch: () => librarySidebar.value?.showLibrarySearch?.(),
  showLibraryFiles: () => librarySidebar.value?.showLibraryFiles?.(),
  chooseLocalFileImport: () => librarySidebar.value?.chooseLocalFileImport?.(),
})
</script>

<style scoped>
.file-sidebar {
  height: 100%;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  background: var(--vk-bg-quiet);
  border-right: 0;
  padding: 8px 8px 10px;
  color: var(--vk-text);
}

.file-sidebar.prompt-sidebar {
  padding-right: 0;
}

@media (max-width: 900px) {
  .file-sidebar {
    display: none;
  }
}
</style>
