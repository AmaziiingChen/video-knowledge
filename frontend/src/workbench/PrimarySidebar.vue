<template>
  <aside class="file-sidebar" :class="{ 'prompt-sidebar': activeView === 'prompts' }">
    <div v-if="activeView === 'library'" class="sidebar-tool-stack">
      <input ref="markdownImportInput" class="sidebar-file-picker" type="file" multiple accept=".md,.markdown,.txt,.html,.htm,.pdf,.docx,.mp4,.mov,.m4v,.mkv,.webm,.flv,.avi,.mp3,.m4a,.wav,.aac,.flac,.ogg,.opus,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,text/plain,text/markdown,text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,video/*,audio/*,image/*" @change="importMarkdownFile" />

      <div
        v-if="libraryMode === 'files'"
        class="sidebar-section sidebar-file-toolbar"
        aria-label="文件树工具"
        @dragover.prevent
        @drop.prevent="importDroppedFiles"
      >
        <el-tooltip content="新建文件夹" placement="bottom">
          <button class="sidebar-icon-button" type="button" aria-label="新建文件夹" @click="startNewFolder(null)">
            <SvgMaskIcon :src="folderAddIcon" :size="24" />
          </button>
        </el-tooltip>
        <el-tooltip content="导入本地资料" placement="bottom">
          <button class="sidebar-icon-button" type="button" aria-label="导入本地资料" @click="chooseMarkdownFile">
            <SvgMaskIcon :src="markdownImportIcon" :size="24" />
          </button>
        </el-tooltip>
      </div>

      <section v-else class="sidebar-search-workspace" aria-label="资料搜索">
        <label class="sidebar-search-input">
          <SvgMaskIcon :src="magnifyingglassIcon" :size="17" />
          <el-input
            ref="librarySearchInput"
            :model-value="searchQuery"
            clearable
            name="library-search"
            autocomplete="off"
            aria-label="搜索资料库内容"
            placeholder="输入并开始搜索…"
            @update:model-value="$emit('update:searchQuery', $event)"
            @keyup.enter="$emit('search')"
            @clear="$emit('clear-search')"
          />
          <span aria-hidden="true">Aa</span>
        </label>
        <div class="sidebar-search-options">
          <div class="sidebar-search-options-heading">
            <strong>搜索范围</strong>
            <small>结果实时更新</small>
          </div>
          <button
            v-for="option in searchScopeOptions"
            :key="option.value"
            type="button"
            :class="{ active: searchScope === option.value }"
            @click="$emit('update:search-scope', option.value)"
          >
            <strong>{{ option.label }}</strong>
            <span>{{ option.description }}</span>
          </button>
        </div>
      </section>

      <div
        class="sidebar-section sidebar-tree-shell"
        :class="{ 'is-search-mode': libraryMode === 'search' }"
      >
        <div
          ref="treeRef"
          class="sidebar-tree"
          tabindex="0"
          @scroll.passive="handleTreeScroll"
          @pointerdown="startBoxSelection"
          @contextmenu="openTreeContextMenu"
        >
        <Transition name="sidebar-selection-bar">
          <div v-if="selectedNodes.length > 1" class="sidebar-selection-bar">
            <span>{{ selectedNodes.length }}</span>
            <el-tooltip content="移入回收站" placement="top">
              <button class="sidebar-action-button danger" type="button" aria-label="将选中项移入回收站" @click.stop="requestDeleteSelected">
                <el-icon><Delete /></el-icon>
              </button>
            </el-tooltip>
          </div>
        </Transition>
        <template v-if="(libraryMode === 'files' || searchActive) && (renderedLibraryNodes.length || editingNode?.isNew)">
          <SidebarTreeRow
            v-if="editingNode?.isNew && editingNode.parentFolderId === null"
            kind="folder"
            editing
            :depth="0"
          >
            <template #editing>
              <SvgMaskIcon :src="folderIcon" :size="14" />
              <input
                ref="editingInput"
                v-model="editingNode.value"
                class="sidebar-inline-input"
                name="library-node-name"
                autocomplete="off"
                aria-label="新文件夹名称"
                @keydown.enter.prevent="commitEditing"
                @keydown.esc.prevent="cancelEditing"
                @blur="cancelEditing"
              />
            </template>
          </SidebarTreeRow>

          <div class="sidebar-tree-virtual-canvas" :style="virtualTreeCanvasStyle">
          <TransitionGroup
            name="sidebar-node-list"
            tag="div"
            class="sidebar-node-list"
            :class="{ 'is-scrolling': treeIsScrolling }"
            :style="virtualTreeListStyle"
          >
            <SidebarTreeRow
              v-for="node in virtualLibraryNodes"
              :key="`${node.type}:${node.id}`"
              :data-node-key="nodeKey(node)"
              :kind="isGroupSeparatorNode(node) ? 'separator' : isFolderNode(node) ? 'folder' : 'file'"
              :label="node.name"
              :label-title="contentNodeTitle(node)"
              :meta="node.meta ?? ''"
              :icon="isContentNode(node) ? contentIcon(node.raw) : isFolderHistoryNode(node) ? folderIcon : ''"
              :depth="node.depth"
              :active="isContentNode(node) && selectedContentItem?.id === node.raw?.id"
              :selected="isNodeSelected(node)"
              :tone="node.type === 'pinned-root' ? 'medium' : 'normal'"
              :unread="Boolean(node.unread)"
              :has-new-descendants="Boolean(node.hasNewDescendants)"
              :unread-count="Number(node.unreadCount || 0)"
              :high-contrast-unread-count="node.type === 'unread-root'"
              :aria-label="nodeAriaLabel(node)"
              :open="isFolderNode(node) && isNodeOpen(node)"
              :editing="node.type === 'draft-folder' || isEditing(node)"
              :drop-position="isDropTarget(node, 'inside') ? 'inside' : isDropTarget(node, 'before') ? 'before' : isDropTarget(node, 'after') ? 'after' : ''"
              :action-width="node.type === 'folder' ? 68 : node.type === 'unread-root' ? 28 : isContentNode(node) ? 44 : 0"
              :draggable="(isMutableLibraryNode(node) || node.type === 'user-group-separator') && !searchActive"
              :interactive="node.type === 'user-group-separator'"
              @activate="activateNode($event, node)"
              @expand-unread="expandUnreadInNode(node)"
              @dragstart="(isMutableLibraryNode(node) || node.type === 'user-group-separator') && onDragStart($event, node)"
              @dragover.prevent="handleNodeDragOver($event, node)"
              @dragleave="clearDropState"
              @drop.prevent="handleNodeDrop($event, node)"
              @dragend="clearDragState"
              @contextmenu="openLibraryContextMenu($event, node)"
            >
              <template #editing>
                <SvgMaskIcon :src="node.type === 'content' ? contentIcon(node.raw) : folderIcon" :size="14" />
                <input
                  ref="editingInput"
                  v-model="editingNode.value"
                  class="sidebar-inline-input"
                  name="library-node-name"
                  autocomplete="off"
                  :aria-label="node.type === 'draft-folder' ? '新文件夹名称' : `重命名 ${node.name}`"
                  @keydown.enter.prevent="commitEditing"
                  @keydown.esc.prevent="cancelEditing"
                  @blur="cancelEditing"
                />
              </template>

              <template v-if="isMutableLibraryNode(node) || node.type === 'unread-root'" #actions>
                <el-tooltip v-if="node.type === 'unread-root'" content="全部标记为已读" placement="top">
                  <button class="sidebar-tree-action" type="button" aria-label="全部标记为已读" @click.stop="markAllUnreadViewed">
                    <el-icon><CircleCheck /></el-icon>
                  </button>
                </el-tooltip>
                <template v-if="isMutableLibraryNode(node)">
                  <el-tooltip v-if="node.type === 'folder'" content="新建文件夹" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="新建子文件夹" @click.stop="startNewFolder(node.id)">
                      <el-icon><Plus /></el-icon>
                    </button>
                  </el-tooltip>
                  <el-tooltip :content="node.type === 'folder' ? '重命名文件夹' : '重命名内容'" placement="top">
                    <button class="sidebar-tree-action" type="button" :aria-label="node.type === 'folder' ? '重命名文件夹' : '重命名内容'" @click.stop="startRename(node)">
                      <SvgMaskIcon :src="highlighterIcon" :size="14" />
                    </button>
                  </el-tooltip>
                  <el-tooltip v-if="node.type === 'folder' && node.hasNewDescendants" content="将文件夹内全部内容标记为已读" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="将文件夹内全部内容标记为已读" @click.stop="markFolderViewed(node)">
                      <el-icon><CircleCheck /></el-icon>
                    </button>
                  </el-tooltip>
                  <el-tooltip content="移入回收站" placement="top">
                    <button class="sidebar-tree-action danger" type="button" aria-label="移入回收站" @click.stop="requestDelete(node)">
                      <SvgMaskIcon :src="trashIcon" :size="14" />
                    </button>
                  </el-tooltip>
                </template>
              </template>
            </SidebarTreeRow>
          </TransitionGroup>
          </div>
        </template>
        <div v-else class="sidebar-empty">
          {{ libraryMode === 'search' && !searchActive ? '输入关键词开始搜索' : searchActive ? '未找到匹配内容' : '空' }}
        </div>
          <div
            v-if="selectionBox"
            class="sidebar-selection-box"
            :style="selectionBoxStyle"
          ></div>
          <div
            v-if="['loading', 'partial'].includes(libraryContentLoadStatus.state) && !searchActive"
            class="sidebar-library-loading"
            :class="{ 'is-partial': libraryContentLoadStatus.state === 'partial' }"
            role="status"
            aria-live="polite"
          >
            <span>{{ libraryContentLoadLabel }}</span>
            <button
              v-if="libraryContentLoadStatus.state === 'partial'"
              type="button"
              @click="$emit('retry-content-pages')"
            >重试</button>
          </div>
        </div>

        <LibraryTrashPanel
          v-if="libraryMode === 'files'"
          :entries="trashEntries"
          :loading="loadingTrash"
          @load="$emit('load-trash')"
          @restore="$emit('restore-trash', $event)"
          @permanently-delete="$emit('permanently-delete-trash', $event)"
          @empty="$emit('empty-trash')"
        />
      </div>

      <SidebarLinkDock
        v-if="libraryMode === 'files'"
        :share-text="shareText"
        :running="running"
        :task-id="result.task_id"
        @update:share-text="$emit('update:shareText', $event)"
        @input-change="$emit('input-change')"
        @run="$emit('run-full-pipeline')"
      />
    </div>

    <PromptFileTree
      v-else-if="activeView === 'prompts'"
      :task-options="promptTaskOptions"
      :folders="promptFolders"
      :templates="promptTemplates"
      :report-prompts="wechatReportPrompts"
      :system-prompts="systemPrompts"
      :prompt-contexts="promptContexts"
      :active-node-id="activePromptNodeId"
      :trash-entries="promptTrashEntries"
      :loading-trash="loadingPromptTrash"
      @open-prompt="$emit('open-prompt', $event)"
      @open-system-prompt="$emit('open-system-prompt', $event)"
      @open-prompt-context="$emit('open-prompt-context', $event)"
      @create-folder="$emit('create-prompt-folder', $event)"
      @create-prompt="$emit('create-prompt-file', $event)"
      @rename-folder="$emit('rename-prompt-folder', $event)"
      @rename-prompt="$emit('rename-prompt-file', $event)"
      @rename-report-prompt="$emit('rename-report-prompt-file', $event)"
      @delete-folder="$emit('delete-prompt-folder', $event)"
      @delete-prompt="$emit('delete-prompt-file', $event)"
      @move-node="$emit('move-prompt-node', $event)"
      @load-trash="$emit('load-prompt-trash')"
      @restore-trash="$emit('restore-prompt-trash', $event)"
      @permanently-delete-trash="$emit('permanently-delete-prompt-trash', $event)"
    />

    <LibraryContextMenu
      :menu="contentContextMenu"
      @close="closeContentContextMenu($event)"
      @select="handleContextMenuSelect"
    />
  </aside>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { contentIsUnread } from '../features/library/contentReadState.js'
import {
  buildLibraryTreeNodes,
  libraryFolderPaths,
  libraryTreeNodeTitle,
  sortLibraryNodes,
  unreadFolderCounts,
} from '../features/library/libraryTreeModel.js'
import { loadLibraryTreePreferences, loadOpenFolderIds as loadSavedOpenFolderIds, saveLibraryTreePreferences, saveOpenFolderIds as saveSavedOpenFolderIds } from '../features/library/libraryTreePreferences.js'
import {
  createDefaultSeparators,
  isRootLayoutNode,
  layoutSortOrder,
  migrateUserGroupSeparators,
  presentLibraryNodesWithSeparators,
  rootFolderNodes,
  separatorSortOrder,
  sortOrderBetween,
} from './libraryGroupLayout.js'
import { CircleCheck, Delete, Plus } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import LibraryTrashPanel from './LibraryTrashPanel.vue'
import LibraryContextMenu from './LibraryContextMenu.vue'
import PromptFileTree from './PromptFileTree.vue'
import SidebarLinkDock from './SidebarLinkDock.vue'
import SidebarTreeRow from './SidebarTreeRow.vue'
import { useLibraryTreeDragController } from './useLibraryTreeDragController.js'
import { useLibraryNodeEditingController } from './useLibraryNodeEditingController.js'
import { useTreeBoxSelectionController } from './useTreeBoxSelectionController.js'
import { useVirtualLibraryTreeController } from './useVirtualLibraryTreeController.js'
const folderIcon = 'folder'
const highlighterIcon = 'highlighter'
const trashIcon = 'trash'
const folderAddIcon = 'folder.badge.plus'
const markdownImportIcon = 'square.and.arrow.down'
const magnifyingglassIcon = 'magnifyingglass'
import { libraryContentIcon } from '../utils/contentIcons'

const props = defineProps({
  activeView: {
    type: String,
    required: true
  },
  libraryMode: {
    type: String,
    default: 'files',
    validator: (value) => ['files', 'search'].includes(value)
  },
  searchScope: {
    type: String,
    default: 'all',
    validator: (value) => ['all', 'title', 'source'].includes(value)
  },
  searchQuery: {
    type: String,
    default: ''
  },
  shareText: {
    type: String,
    default: ''
  },
  running: {
    type: Boolean,
    default: false
  },
  result: {
    type: Object,
    default: () => ({})
  },
  sidebarTreeItems: {
    type: Array,
    default: () => []
  },
  libraryContentItems: {
    type: Array,
    default: () => []
  },
  libraryContentLoadStatus: {
    type: Object,
    default: () => ({ state: 'idle', loaded: 0, total: 0 })
  },
  viewedContentIds: {
    type: Array,
    default: () => []
  },
  explicitlyUnreadContentIds: {
    type: Array,
    default: () => []
  },
  contentViewedBefore: {
    type: String,
    default: ''
  },
  libraryFolders: {
    type: Array,
    default: () => []
  },
  folderHistoryStates: {
    type: Object,
    default: () => ({})
  },
  revealedLibraryFolderIds: {
    type: Array,
    default: () => []
  },
  trashEntries: { type: Array, default: () => [] },
  loadingTrash: { type: Boolean, default: false },
  selectedContentItem: {
    type: Object,
    default: null
  },
  promptTaskOptions: {
    type: Array,
    default: () => []
  },
  promptTemplates: {
    type: Array,
    default: () => []
  },
  promptFolders: { type: Array, default: () => [] },
  wechatReportPrompts: { type: Array, default: () => [] },
  systemPrompts: { type: Array, default: () => [] },
  promptContexts: { type: Array, default: () => [] },
  activePromptNodeId: { type: String, default: '' },
  promptTrashEntries: { type: Array, default: () => [] },
  loadingPromptTrash: { type: Boolean, default: false }
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
  'permanently-delete-prompt-trash'
])

const libraryContentLoadLabel = computed(() => {
  const loaded = Math.max(0, Number(props.libraryContentLoadStatus?.loaded || 0))
  const total = Math.max(loaded, Number(props.libraryContentLoadStatus?.total || 0))
  const loadedLabel = loaded.toLocaleString('zh-CN')
  const totalLabel = total.toLocaleString('zh-CN')
  if (props.libraryContentLoadStatus?.state === 'partial') {
    return total > loaded
      ? `已载入 ${loadedLabel} / ${totalLabel} · 其余暂未载入`
      : '部分资料暂未载入'
  }
  return total > loaded
    ? `正在整理资料 · 已载入 ${loadedLabel} / ${totalLabel}`
    : `正在整理资料 · 已载入 ${loadedLabel}`
})

// v2 starts from a collapsed tree. The former eager tree restored every open
// branch and expected all article rows to be present at startup; that state is
// not compatible with the lazy per-folder loader below.
function loadUserGroupSeparators() { return loadLibraryTreePreferences() }
function saveUserGroupSeparators(groups) { saveLibraryTreePreferences(groups) }
function loadOpenFolderIds() { return loadSavedOpenFolderIds() }
function saveOpenFolderIds(folderIds) { saveSavedOpenFolderIds(folderIds) }

// An empty saved state deliberately means that every folder starts collapsed.
const openFolderIds = ref(loadOpenFolderIds())
const librarySearchInput = ref(null)
const searchScope = computed(() => props.searchScope)
const selectedKeys = ref(new Set())
const anchorKey = ref(null)
const contentContextMenu = ref(null)
const separatorLayoutState = loadUserGroupSeparators()
const userGroupSeparators = ref(separatorLayoutState.separators)
const separatorLayoutInitialized = ref(separatorLayoutState.initialized)
const unreadRootOpen = ref(false)
const pinnedRootOpen = ref(true)
const TREE_ROW_HEIGHT = 26
const searchScopeOptions = [
  { value: 'all', label: '全部内容', description: '标题、摘要与正文' },
  { value: 'title', label: '文件名', description: '只匹配资料标题' },
  { value: 'source', label: '来源', description: '匹配来源名称与类型' },
]
defineExpose({
  focusLibrarySearch() {
    librarySearchInput.value?.focus?.()
  },
  async showLibrarySearch() {
    await nextTick()
    librarySearchInput.value?.focus?.()
  },
  showLibraryFiles() {
    librarySearchInput.value?.blur?.()
  },
})

const searchActive = computed(() => props.libraryMode === 'search' && Boolean(props.searchQuery.trim()))
const viewedContentIdSet = computed(() => new Set(props.viewedContentIds.map(String)))
const explicitlyUnreadContentIdSet = computed(() => new Set(props.explicitlyUnreadContentIds.map(String)))
function folderHistoryState(folderId) {
  return props.folderHistoryStates[String(folderId)] || null
}

function ensureFolderItemsLoaded(folderId) {
  const id = String(folderId || '')
  if (!id) return
  const page = folderHistoryState(id)
  if (!page?.loaded && !page?.loading) {
    emit('load-folder-history', { folderId: id, append: false })
  }
}

const folderContentCounts = computed(() => {
  // Counts come from the folder endpoint and include descendant folders. The
  // sidebar now loads article rows lazily, so deriving this from loaded rows
  // would incorrectly make collapsed sources look empty.
  return new Map(props.libraryFolders.map((folder) => [
    String(folder.id),
    Math.max(0, Number(folder.content_count || 0)),
  ]))
})

const folderUnreadCounts = computed(() => {
  return unreadFolderCounts({
    libraryFolders: props.libraryFolders,
    libraryContentItems: props.libraryContentItems,
    isUnreadContent,
  })
})

function isUnreadContent(item) {
  return contentIsUnread(item, {
    viewedContentIds: viewedContentIdSet.value,
    explicitlyUnreadContentIds: explicitlyUnreadContentIdSet.value,
    viewedBefore: props.contentViewedBefore,
  })
}

function nodeAriaLabel(node) {
  if (node?.unread) return `${node.name}，未读`
  if (node?.hasNewDescendants) return `${node.name}，包含 ${node.unreadCount || ''} 条未读内容`
  return ''
}

const folderPathById = computed(() => libraryFolderPaths(props.libraryFolders))

const unreadContentItems = computed(() => sortLibraryNodes(props.libraryContentItems.filter(isUnreadContent)))

const visibleLibraryNodes = computed(() => buildLibraryTreeNodes({
  searchActive: searchActive.value,
  libraryFolders: props.libraryFolders,
  sidebarTreeItems: props.sidebarTreeItems,
  unreadContentItems: unreadContentItems.value,
  isUnreadContent,
  isNodeOpen,
  isFolderOpen,
  folderHistoryState,
  folderContentCounts: folderContentCounts.value,
  folderUnreadCounts: folderUnreadCounts.value,
}))

const presentationLibraryNodes = computed(() => {
  if (searchActive.value || !userGroupSeparators.value.length) return visibleLibraryNodes.value
  return presentLibraryNodesWithSeparators(visibleLibraryNodes.value, userGroupSeparators.value)
})

const selectedNodes = computed(() => {
  const selected = selectedKeys.value
  return visibleLibraryNodes.value.filter((node) => selected.has(nodeKey(node)))
})
const selectedContentNodes = computed(() => selectedNodes.value.filter(isContentNode))
const {
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
} = useLibraryNodeEditingController({
  openFolderIds,
  selectedKeys,
  selectedNodes,
  saveOpenFolderIds,
  emit,
})

const renderedLibraryNodes = computed(() => {
  const draft = editingNode.value?.isNew ? editingNode.value : null
  if (!draft || draft.parentFolderId === null) return presentationLibraryNodes.value

  const result = []
  for (const node of presentationLibraryNodes.value) {
    result.push(node)
    if (node.type === 'folder' && node.id === draft.parentFolderId) {
      result.push({
        type: 'draft-folder',
        id: `new-folder:${node.id}`,
        name: draft.value,
        parentId: node.id,
        depth: node.depth + 1
      })
    }
  }
  return result
})

const {
  treeRef,
  treeIsScrolling,
  virtualLibraryNodes,
  virtualTreeCanvasStyle,
  virtualTreeListStyle,
  handleTreeScroll,
  mountVirtualTree,
  disposeVirtualTree,
} = useVirtualLibraryTreeController({
  renderedLibraryNodes,
  onScrollStart: () => closeContentContextMenu(),
  rowHeight: TREE_ROW_HEIGHT,
})

const {
  selectionBox,
  selectionBoxStyle,
  startBoxSelection,
  cancelBoxSelection,
} = useTreeBoxSelectionController({
  treeRef,
  selectedKeys,
  setSelectedKeys,
  setAnchorKey: (key) => { anchorKey.value = key || anchorKey.value },
})

const {
  onDragStart,
  handleNodeDragOver,
  handleNodeDrop,
  isDropTarget,
  clearDropState,
  clearDragState,
} = useLibraryTreeDragController({
  searchActive,
  visibleLibraryNodes,
  selectedKeys,
  nodeKey,
  setSelectedKeys,
  setAnchorKey: (key) => { anchorKey.value = key },
  libraryFolders: computed(() => props.libraryFolders),
  isMutableLibraryNode,
  sortOrderNearSeparator,
  moveUserSeparator,
  emit,
  cancelBoxSelection,
})

function rootLayoutEntries({ excludeFolderIds = new Set(), excludeSeparatorIds = new Set() } = {}) {
  const folders = visibleLibraryNodes.value.filter((node) => (
    node.type === 'folder' && node.depth === 0 && !excludeFolderIds.has(String(node.id))
  ))
  const separators = userGroupSeparators.value
    .filter((separator) => !excludeSeparatorIds.has(String(separator.id)))
    .map((separator) => ({
      type: 'user-group-separator',
      id: separator.id,
      sortOrder: separatorSortOrder(separator, rootFolderNodes(props.libraryFolders)),
      raw: separator,
    }))
  return [...folders, ...separators].sort((left, right) => (
    layoutSortOrder(left) - layoutSortOrder(right)
    || (left.type === right.type ? String(left.id).localeCompare(String(right.id)) : left.type === 'user-group-separator' ? -1 : 1)
  ))
}

function separatorSortOrderAt(startIndex) {
  const nodes = renderedLibraryNodes.value
  const previous = [...nodes.slice(0, startIndex)].reverse().find(isRootLayoutNode)
  const next = nodes.slice(startIndex).find(isRootLayoutNode)
  return sortOrderBetween(previous, next)
}

function nextSeparatorSortOrder() {
  return sortOrderBetween(rootLayoutEntries().at(-1), null)
}

function sortOrderNearSeparator(separator, position, drags = []) {
  const excludedFolderIds = new Set(drags.filter((node) => node?.type === 'folder').map((node) => String(node.id)))
  const entries = rootLayoutEntries({ excludeFolderIds: excludedFolderIds })
  const index = entries.findIndex((entry) => entry.type === 'user-group-separator' && entry.id === separator.id)
  if (index === -1) return nextSeparatorSortOrder()
  return position === 'before'
    ? sortOrderBetween(entries[index - 1], entries[index])
    : sortOrderBetween(entries[index], entries[index + 1])
}

function moveUserSeparator(separatorId, target, position) {
  const entries = rootLayoutEntries({ excludeSeparatorIds: new Set([String(separatorId)]) })
  const index = entries.findIndex((entry) => entry.type === target.type && entry.id === target.id)
  if (index === -1) return
  const sortOrder = position === 'before'
    ? sortOrderBetween(entries[index - 1], entries[index])
    : sortOrderBetween(entries[index], entries[index + 1])
  const separators = userGroupSeparators.value.map((separator) => (
    String(separator.id) === String(separatorId)
      ? { ...separator, sortOrder, beforeFolderId: undefined }
      : separator
  ))
  userGroupSeparators.value = separators
  saveUserGroupSeparators(separators)
}

watch(
  () => props.libraryFolders.map((folder) => `${folder.id}:${folder.parent_folder_id || ''}:${folder.sort_order}:${folder.is_pinned ? 1 : 0}`).join('|'),
  () => {
    const roots = rootFolderNodes(props.libraryFolders)
    if (!roots.length) return
    if (!separatorLayoutInitialized.value) {
      userGroupSeparators.value = createDefaultSeparators(props.libraryFolders)
      separatorLayoutInitialized.value = true
      saveUserGroupSeparators(userGroupSeparators.value)
      return
    }
    const migrated = migrateUserGroupSeparators(userGroupSeparators.value, props.libraryFolders)
    if (migrated.some((separator, index) => separator.sortOrder !== userGroupSeparators.value[index]?.sortOrder || userGroupSeparators.value[index]?.beforeFolderId)) {
      userGroupSeparators.value = migrated
      saveUserGroupSeparators(migrated)
    }
  },
  { immediate: true },
)

function contentNodeTitle(node) {
  if (!isContentNode(node)) return node?.name || ''
  return libraryTreeNodeTitle(node, folderPathById.value)
}

function contentIcon(item) {
  return libraryContentIcon(item)
}

onMounted(() => {
  mountVirtualTree()
})

onBeforeUnmount(() => {
  cancelBoxSelection()
  disposeVirtualTree()
})

function isFolderOpen(id) {
  return openFolderIds.value.has(String(id))
}

function folderNodeOpenKey(node) {
  if (node.type === 'unread-root') return 'unread:root'
  if (node.type === 'pinned-root') return 'pinned:root'
  return String(node.id)
}

function isFolderNode(node) {
  return ['folder', 'draft-folder', 'unread-root', 'pinned-root'].includes(node?.type)
}

function isGroupSeparatorNode(node) {
  return node?.type === 'group-separator' || node?.type === 'user-group-separator'
}

function isContentNode(node) {
  return ['content', 'unread-content'].includes(node?.type)
}

function isFolderHistoryNode(node) {
  return node?.type === 'folder-history-more'
}

function isMutableLibraryNode(node) {
  return node?.type === 'folder' || node?.type === 'content'
}

function isNodeOpen(node) {
  if (node?.type === 'unread-root') return unreadRootOpen.value
  if (node?.type === 'pinned-root') return pinnedRootOpen.value
  return isFolderOpen(folderNodeOpenKey(node))
}

function toggleFolder(id) {
  const folderId = String(id)
  const open = new Set(openFolderIds.value)
  if (open.has(folderId)) {
    open.delete(folderId)
  } else {
    open.add(folderId)
    ensureFolderItemsLoaded(folderId)
  }
  openFolderIds.value = open
  saveOpenFolderIds(open)
}

function revealLibraryFolders(folderIds) {
  const foldersById = new Map(props.libraryFolders.map((folder) => [String(folder.id), folder]))
  const open = new Set(openFolderIds.value)
  let changed = false
  for (const rawId of folderIds || []) {
    let folderId = String(rawId || '')
    const visited = new Set()
    while (folderId && foldersById.has(folderId) && !visited.has(folderId)) {
      visited.add(folderId)
      if (!open.has(folderId)) {
        open.add(folderId)
        changed = true
      }
      folderId = foldersById.get(folderId)?.parent_folder_id
        ? String(foldersById.get(folderId).parent_folder_id)
        : ''
    }
  }
  if (changed) {
    openFolderIds.value = open
    saveOpenFolderIds(open)
  }
}

watch(
  () => props.revealedLibraryFolderIds,
  (folderIds) => revealLibraryFolders(folderIds),
  { immediate: true, deep: true },
)

function expandUnreadInNode(node) {
  if (!node?.unreadCount) return
  if (node.type === 'unread-root') {
    unreadRootOpen.value = !unreadRootOpen.value
    return
  }
  if (node.type !== 'folder') return
  const open = new Set(openFolderIds.value)
  const rootId = String(node.id)
  const foldersById = new Map(props.libraryFolders.map((folder) => [String(folder.id), folder]))
  for (const folder of props.libraryFolders) {
    const folderId = String(folder.id)
    if (!(folderUnreadCounts.value.get(folderId) || 0)) continue
    let currentId = folderId
    const visited = new Set()
    while (currentId && !visited.has(currentId)) {
      visited.add(currentId)
      if (currentId === rootId) {
        open.add(folderId)
        break
      }
      currentId = foldersById.get(currentId)?.parent_folder_id
        ? String(foldersById.get(currentId).parent_folder_id)
        : ''
    }
  }
  openFolderIds.value = open
  saveOpenFolderIds(open)
}

// Re-opening the application should restore only the branches the user chose
// to keep open, and hydrate those branches independently. This never asks for
// a global article page.
watch(
  [
    () => props.libraryFolders.map((folder) => String(folder.id)).join('|'),
    () => [...openFolderIds.value].sort().join('|'),
  ],
  () => {
    const knownFolderIds = new Set(props.libraryFolders.map((folder) => String(folder.id)))
    for (const folderId of openFolderIds.value) {
      if (knownFolderIds.has(String(folderId))) ensureFolderItemsLoaded(folderId)
    }
  },
  { immediate: true },
)

function nodeKey(node) {
  if (node.type === 'draft-folder') return node.id
  return `${node.type}:${node.id}`
}

function isNodeSelected(node) {
  return selectedKeys.value.has(nodeKey(node))
}

function setSelectedKeys(keys) {
  selectedKeys.value = new Set(keys)
}

function activateNode(event, node) {
  if (node.type === 'unread-root') {
    unreadRootOpen.value = !unreadRootOpen.value
    return
  }
  if (node.type === 'pinned-root') {
    pinnedRootOpen.value = !pinnedRootOpen.value
    return
  }
  if (node.type === 'unread-content') {
    updateSelection(event, node)
    emit('open-content', node.raw)
    return
  }
  if (isFolderHistoryNode(node)) {
    if (!node.loading) emit('load-folder-history', { folderId: node.parentId, append: true })
    return
  }
  updateSelection(event, node)
  if (node.type === 'folder') {
    toggleFolder(node.id)
    return
  }
  emit('open-content', node.raw)
}

function updateSelection(event, node) {
  const key = nodeKey(node)
  if (event?.shiftKey && anchorKey.value) {
    selectRange(anchorKey.value, key)
    return
  }
  if (event?.metaKey || event?.ctrlKey) {
    const next = new Set(selectedKeys.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setSelectedKeys(next)
    anchorKey.value = key
    return
  }
  setSelectedKeys([key])
  anchorKey.value = key
}

function contextMenuPosition(event, trigger) {
  if (!event.clientX && !event.clientY && trigger) {
    const rect = trigger.getBoundingClientRect()
    return { x: rect.left + 6, y: rect.bottom + 4 }
  }
  return { x: event.clientX, y: event.clientY }
}

function openContentContextMenu(menu, event) {
  const trigger = event.target?.closest?.('.sidebar-tree-row-main') || null
  contentContextMenu.value = {
    ...menu,
    ...contextMenuPosition(event, trigger),
    trigger,
  }
}

function openTreeContextMenu(event) {
  if (searchActive.value || event.target.closest('.sidebar-tree-row')) return
  event.preventDefault()
  const tree = treeRef.value
  const rect = tree?.getBoundingClientRect()
  const offset = rect ? event.clientY - rect.top + tree.scrollTop : 0
  const start = Math.max(0, Math.floor(offset / TREE_ROW_HEIGHT))
  openContentContextMenu({
    kind: 'blank',
    sortOrder: separatorSortOrderAt(start),
  }, event)
}

function openLibraryContextMenu(event, node) {
  if (!isMutableLibraryNode(node) && !isContentNode(node) && node?.type !== 'user-group-separator') return
  event.preventDefault()
  if (node.type === 'user-group-separator') {
    openContentContextMenu({
      kind: 'user-group-separator',
      node,
    }, event)
    return
  }
  const key = nodeKey(node)
  if (!selectedKeys.value.has(key)) {
    setSelectedKeys([key])
    anchorKey.value = key
  }
  openContentContextMenu({
    kind: 'node',
    node,
  }, event)
}

function closeContentContextMenu({ restoreFocus = false } = {}) {
  const trigger = contentContextMenu.value?.trigger
  contentContextMenu.value = null
  if (restoreFocus && trigger) nextTick(() => trigger.focus())
}

function setSelectedContentViewed(viewed) {
  const contentItemIds = selectedContentNodes.value.map((node) => node.raw?.id || node.id).filter(Boolean)
  if (contentItemIds.length) emit('set-content-viewed', { contentItemIds, viewed })
  closeContentContextMenu()
}

function revealContextMenuLocation() {
  const node = contentContextMenu.value?.node
  if (node) emit('reveal-library-node', node)
  closeContentContextMenu()
}

function toggleFolderPin() {
  const folder = contentContextMenu.value?.node?.raw
  if (folder?.id) emit('set-folder-pinned', { folder, pinned: !folder.is_pinned })
  closeContentContextMenu()
}

function renameContextMenuNode() {
  const node = contextMenuMutableNode()
  closeContentContextMenu()
  if (node && isMutableLibraryNode(node)) startRename(node)
}

function deleteContextMenuNode() {
  const node = contextMenuMutableNode()
  closeContentContextMenu()
  if (node && isMutableLibraryNode(node)) requestDelete(node)
}

function contextMenuMutableNode() {
  const node = contentContextMenu.value?.node
  return node?.type === 'unread-content' ? { ...node, type: 'content' } : node
}

function createUserGroupSeparator() {
  const sortOrder = Number(contentContextMenu.value?.sortOrder)
  closeContentContextMenu()
  const id = window.crypto?.randomUUID?.() || `user-group-${Date.now()}`
  const groups = [...userGroupSeparators.value, {
    id,
    sortOrder: Number.isFinite(sortOrder) ? sortOrder : nextSeparatorSortOrder(),
  }]
  userGroupSeparators.value = groups
  saveUserGroupSeparators(groups)
}

function deleteUserGroupSeparator() {
  const groupId = contentContextMenu.value?.node?.raw?.id
  closeContentContextMenu()
  if (!groupId) return
  const groups = userGroupSeparators.value.filter((group) => group.id !== groupId)
  userGroupSeparators.value = groups
  saveUserGroupSeparators(groups)
}

function handleContextMenuSelect({ id, payload } = {}) {
  switch (id) {
    case 'create-separator': createUserGroupSeparator(); break
    case 'delete-separator': deleteUserGroupSeparator(); break
    case 'reveal': revealContextMenuLocation(); break
    case 'rename': renameContextMenuNode(); break
    case 'toggle-pin': toggleFolderPin(); break
    case 'set-viewed': setSelectedContentViewed(Boolean(payload)); break
    case 'delete': deleteContextMenuNode(); break
  }
}

function markFolderViewed(folderNode) {
  const folderIds = new Set([String(folderNode.id)])
  let changed = true
  while (changed) {
    changed = false
    for (const folder of props.libraryFolders) {
      const parentId = folder.parent_folder_id ? String(folder.parent_folder_id) : ''
      if (parentId && folderIds.has(parentId) && !folderIds.has(String(folder.id))) {
        folderIds.add(String(folder.id))
        changed = true
      }
    }
  }
  const contentItemIds = props.libraryContentItems
    .filter((item) => folderIds.has(String(item?.library_folder_id || '')))
    .map((item) => item.id)
    .filter(Boolean)
  if (contentItemIds.length) emit('set-content-viewed', { contentItemIds, viewed: true })
}

function markAllUnreadViewed() {
  const contentItemIds = unreadContentItems.value.map((item) => item.id).filter(Boolean)
  if (contentItemIds.length) emit('set-content-viewed', { contentItemIds, viewed: true })
}

function selectRange(fromKey, toKey) {
  const keys = visibleLibraryNodes.value.map(nodeKey)
  const from = keys.indexOf(fromKey)
  const to = keys.indexOf(toKey)
  if (from === -1 || to === -1) {
    setSelectedKeys([toKey])
    anchorKey.value = toKey
    return
  }
  const [start, end] = from < to ? [from, to] : [to, from]
  setSelectedKeys(keys.slice(start, end + 1))
}

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

.sidebar-tool-stack {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 0;
}

.sidebar-section {
  display: grid;
  gap: 2px;
  padding: 6px 0;
  border-top: 1px solid var(--vk-border);
}

.sidebar-section:first-child {
  border-top: 0;
}

.sidebar-file-toolbar {
  grid-template-columns: repeat(2, 36px);
  align-items: center;
  justify-content: center;
  gap: var(--vk-space-control);
  min-height: 36px;
  padding-block: 0;
  padding-inline: 0;
  border-top: 0;
}

.sidebar-file-toolbar .sidebar-icon-button {
  width: 36px;
  height: 36px;
}

.sidebar-file-picker {
  position: fixed;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.sidebar-search-workspace {
  display: grid;
  gap: var(--vk-space-control);
  padding: var(--vk-space-control);
}

.sidebar-search-input {
  min-width: 0;
  height: 34px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--vk-space-xs);
  padding: 0 var(--vk-space-control);
  border: 1px solid var(--vk-border);
  border-radius: var(--vk-radius-pill);
  background: var(--vk-bg-panel);
  color: var(--vk-muted);
}

.sidebar-search-input :deep(.el-input__wrapper) {
  min-height: 30px;
  padding: 0;
  border: 0;
  border-radius: 0 !important;
  background: transparent;
  box-shadow: none !important;
}

.sidebar-search-input > span {
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
}

.sidebar-search-options {
  display: grid;
  gap: var(--vk-space-xs);
  padding: var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-border) 82%, transparent);
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-bg-panel) 82%, transparent);
}

.sidebar-search-options-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-control);
  padding: 0 var(--vk-space-xs) var(--vk-space-xs);
}

.sidebar-search-options-heading strong {
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-strong);
}

.sidebar-search-options-heading small {
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
}

.sidebar-search-options button {
  min-width: 0;
  min-height: 38px;
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  align-items: center;
  gap: var(--vk-space-control);
  padding: 0 var(--vk-space-control);
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.sidebar-search-options button:hover,
.sidebar-search-options button.active {
  background: var(--vk-bg-hover);
}

.sidebar-search-options button strong {
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-medium);
}

.sidebar-search-options button span {
  overflow: hidden;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-icon-button,
.sidebar-action-button {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--vk-muted);
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease;
}

.sidebar-icon-button:hover,
.sidebar-action-button:hover {
  background: var(--vk-bg-hover);
  color: var(--vk-text);
}

.sidebar-icon-button:disabled {
  opacity: 0.32;
  cursor: default;
  pointer-events: none;
}


.sidebar-action-button.danger:hover {
  color: var(--vk-danger);
  background: color-mix(in srgb, var(--vk-danger) 10%, transparent);
}

.sidebar-tree {
  position: relative;
  display: grid;
  gap: 1px;
  align-content: start;
  min-height: 0;
  overflow-y: auto;
  /* Keep the native scrollbar in the sidebar's outer padding. Reserving its
     gutter prevents tree rows from changing width when overflow begins. */
  scrollbar-gutter: stable;
  padding: 2px 0 0;
  user-select: none;
}

.sidebar-library-loading {
  position: absolute;
  right: 8px;
  bottom: 6px;
  z-index: 7;
  padding: 3px 7px;
  border: 1px solid color-mix(in srgb, var(--vk-border) 74%, transparent);
  border-radius: var(--vk-radius-control);
  background: color-mix(in srgb, var(--vk-bg-panel) 88%, transparent);
  box-shadow: 0 4px 12px color-mix(in srgb, var(--vk-text) 6%, transparent);
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  line-height: 1.2;
  pointer-events: none;
  display: flex;
  align-items: center;
  gap: var(--vk-space-control);
}

.sidebar-library-loading.is-partial {
  color: var(--vk-warning);
  pointer-events: auto;
}

.sidebar-library-loading button {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--vk-accent);
  font: inherit;
  cursor: pointer;
}

.sidebar-library-loading button:hover {
  text-decoration: underline;
}

.sidebar-tree-shell {
  width: calc(100% + var(--vk-space-control));
  min-height: 160px;
  margin-right: calc(-1 * var(--vk-space-control));
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 0;
  padding: 2px 0 0;
  overflow: hidden;
}

.sidebar-tree-shell.is-search-mode {
  min-height: 0;
  border-top: 0;
}


.sidebar-node-list {
  display: grid;
  grid-auto-rows: min-content;
  align-self: start;
  align-content: start;
  gap: 0;
}

.sidebar-node-list.is-scrolling {
  will-change: transform;
}

.sidebar-tree-virtual-canvas {
  position: relative;
  width: 100%;
  min-height: 100%;
}

.sidebar-tree-virtual-canvas > .sidebar-node-list {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
}

.sidebar-node-list-move {
  transition: transform var(--vk-motion-standard) var(--vk-ease-out);
}

.sidebar-node-list-enter-active {
  transition:
    transform var(--vk-motion-standard) var(--vk-ease-out),
    opacity var(--vk-motion-fast) var(--vk-ease-out);
}

.sidebar-node-list-enter-from {
  opacity: 0;
  transform: translateY(-3px);
}

.sidebar-node-list-leave-active {
  position: absolute;
  right: 0;
  left: 0;
  visibility: hidden;
  opacity: 0;
  pointer-events: none;
  transition: none;
}

.sidebar-node-list-leave-to {
  opacity: 0;
  transform: none;
}

.sidebar-node-list.is-scrolling .sidebar-node-list-move,
.sidebar-node-list.is-scrolling .sidebar-node-list-enter-active,
.sidebar-node-list.is-scrolling .sidebar-node-list-leave-active {
  transition: none;
}

.sidebar-selection-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  min-height: 24px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  padding: 1px 2px;
  background: color-mix(in srgb, var(--vk-bg-quiet) 92%, transparent);
  border-bottom: 1px solid var(--vk-border);
}

.sidebar-selection-bar-enter-active { transition: opacity var(--vk-motion-standard) var(--vk-ease-out), transform var(--vk-motion-standard) var(--vk-ease-out); }
.sidebar-selection-bar-leave-active { transition: opacity var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out); }
.sidebar-selection-bar-enter-from,
.sidebar-selection-bar-leave-to { opacity: 0; transform: translateY(-4px); }

.sidebar-selection-bar span {
  min-width: 18px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  text-align: center;
}

.sidebar-selection-box {
  position: absolute;
  z-index: 6;
  pointer-events: none;
  border: 1px solid var(--vk-drag-indicator);
  background: var(--vk-drag-fill);
}

.sidebar-inline-input {
  width: 100%;
  min-width: 0;
  height: 22px;
  border: 1px solid var(--vk-accent);
  background: var(--vk-bg-center);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  outline: none;
  padding: 0 4px;
}

.sidebar-filter,
.sidebar-file {
  width: 100%;
  min-width: 0;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  text-align: left;
  cursor: pointer;
}

@media (prefers-reduced-motion: reduce) {
  .sidebar-node-list-move,
  .sidebar-node-list-enter-active,
  .sidebar-node-list-leave-active,
  .sidebar-trash-arrow {
    transition: none;
  }

  .sidebar-selection-bar-enter-active,
  .sidebar-selection-bar-leave-active,
  .sidebar-trash-list-enter-active,
  .sidebar-trash-list-leave-active {
    transition: opacity var(--vk-motion-fast) ease;
  }

  .sidebar-node-list-enter-from,
  .sidebar-node-list-leave-to,
  .sidebar-selection-bar-enter-from,
  .sidebar-selection-bar-leave-to,
  .sidebar-trash-list-enter-from,
  .sidebar-trash-list-leave-to {
    transform: none;
  }
}

.sidebar-file:hover,
.sidebar-file.active {
  background: var(--vk-bg-hover);
}

.sidebar-file.active {
  color: var(--vk-selected-fg);
  background: var(--vk-selected-bg);
}

.sidebar-file {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  margin: 2px 8px 2px 0;
  padding: 5px 10px;
  border-radius: 6px;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
}

.sidebar-file-with-icon {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sidebar-file span {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: inherit;
  font-size: var(--vk-type-label-size);
  font-weight: var(--vk-weight-regular);
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-file em,
.sidebar-empty {
  color: var(--vk-muted);
  font-size: var(--vk-type-label-size);
  font-style: normal;
}

.sidebar-empty {
  padding: 8px 5px;
}

@media (max-width: 900px) {
  .file-sidebar {
    display: none;
  }
}
</style>
