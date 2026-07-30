<template>
  <aside class="file-sidebar" :class="{ 'prompt-sidebar': activeView === 'prompts' }">
    <div v-if="activeView === 'library'" class="sidebar-tool-stack">
      <div class="sidebar-section sidebar-search-row" @dragover.prevent @drop.prevent="importDroppedFiles">
        <el-input
          :model-value="searchQuery"
          clearable
          name="library-search"
          autocomplete="off"
          aria-label="搜索资料库内容"
          placeholder="搜索标题、摘要或正文…"
          @update:model-value="$emit('update:searchQuery', $event)"
          @keyup.enter="$emit('search')"
          @clear="$emit('clear-search')"
        />
        <el-tooltip content="新建文件夹" placement="bottom">
          <button class="sidebar-icon-button" type="button" aria-label="新建文件夹" @click="startNewFolder(null)">
            <SvgMaskIcon :src="folderAddIcon" :size="16" />
          </button>
        </el-tooltip>
        <input ref="markdownImportInput" class="sidebar-file-picker" type="file" multiple accept=".md,.markdown,.txt,.html,.htm,.pdf,.docx,.mp4,.mov,.m4v,.mkv,.webm,.flv,.avi,.mp3,.m4a,.wav,.aac,.flac,.ogg,.opus,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,text/plain,text/markdown,text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,video/*,audio/*,image/*" @change="importMarkdownFile" />
        <el-tooltip content="导入本地资料" placement="bottom">
          <button class="sidebar-icon-button" type="button" aria-label="导入本地资料" @click="chooseMarkdownFile">
            <SvgMaskIcon :src="markdownImportIcon" :size="16" />
          </button>
        </el-tooltip>
      </div>

      <div class="sidebar-section sidebar-tree-shell">
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
        <template v-if="renderedLibraryNodes.length || editingNode?.isNew">
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
              :unread="false"
              :has-new-descendants="node.type === 'unread-root'"
              :unread-count="node.type === 'unread-root' ? Number(node.unreadCount || 0) : 0"
              :high-contrast-unread-count="node.type === 'unread-root'"
              :aria-label="nodeAriaLabel(node)"
              :open="isFolderNode(node) && isNodeOpen(node)"
              :editing="node.type === 'draft-folder' || isEditing(node)"
              :drop-position="isDropTarget(node, 'inside') ? 'inside' : isDropTarget(node, 'before') ? 'before' : isDropTarget(node, 'after') ? 'after' : ''"
              :action-width="node.type === 'folder' ? 68 : node.type === 'unread-root' ? 28 : node.type === 'content' ? 44 : 0"
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
                  <el-tooltip v-if="node.type === 'unread-root'" content="全部标记为已查看" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="全部标记为已查看" @click.stop="markAllUnreadViewed">
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
                  <el-tooltip v-if="node.type === 'folder' && node.hasNewDescendants" content="将文件夹内全部内容标记为已查看" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="将文件夹内全部内容标记为已查看" @click.stop="markFolderViewed(node)">
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
        <div v-else class="sidebar-empty">{{ searchActive ? '未找到匹配内容' : '空' }}</div>
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

        <section class="sidebar-trash" :class="{ open: trashOpen }">
          <button class="sidebar-trash-toggle" type="button" @click="toggleTrash">
            <SvgMaskIcon :src="trashIcon" :size="14" />
            <span>回收站</span>
            <small>{{ trashEntries.length || '' }}</small>
            <el-icon class="sidebar-trash-arrow"><ArrowRight /></el-icon>
          </button>
          <Transition name="sidebar-trash-list">
            <div v-if="trashOpen" class="sidebar-trash-list" v-loading="loadingTrash">
              <div v-if="trashEntries.length" class="sidebar-trash-actions">
                <button type="button" class="danger" @click="requestEmptyTrash">清空回收站</button>
              </div>
              <div v-for="entry in trashEntries" :key="`${entry.entry_type}:${entry.id}`" class="sidebar-trash-entry">
                <SvgMaskIcon :src="trashEntryIcon(entry)" :size="14" />
                <span :title="entry.name">{{ entry.name }}</span>
                <button type="button" @click="$emit('restore-trash', entry)">恢复</button>
                <button type="button" class="danger" @click.stop="requestPermanentDeletion(entry)">删除</button>
              </div>
              <p v-if="!loadingTrash && !trashEntries.length" class="sidebar-trash-empty">回收站为空</p>
            </div>
          </Transition>
        </section>
      </div>

      <section class="sidebar-section sidebar-link-dock">
        <div class="sidebar-process-input">
          <el-input
            :model-value="shareText"
            type="textarea"
            name="source-link"
            autocomplete="off"
            aria-label="粘贴待处理链接"
            :rows="2"
            resize="none"
            placeholder="粘贴链接…"
            @update:model-value="$emit('update:shareText', $event)"
            @input="$emit('input-change')"
            @keydown.enter.exact.prevent="$emit('run-full-pipeline')"
          />
          <el-button
            class="sidebar-run-button"
            :loading="running && !result.task_id"
            :disabled="!shareText.trim() || running"
            aria-label="开始处理"
            @click="$emit('run-full-pipeline')"
          >
            <SvgMaskIcon :src="sendIcon" :size="19" />
          </el-button>
        </div>
      </section>
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

    <Teleport to="body">
      <Transition name="sidebar-context-menu">
        <div
          v-if="contentContextMenu"
          ref="contentContextMenuRef"
          class="sidebar-context-menu"
          :style="contentContextMenuStyle"
          role="menu"
          :aria-label="contentContextMenu.node?.name ? `${contentContextMenu.node.name} 操作菜单` : '文件树菜单'"
          @pointerdown.stop
          @contextmenu.prevent
          @keydown="handleContentContextMenuKeydown"
        >
          <template v-if="contentContextMenu.kind === 'blank'">
            <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="createUserGroupSeparator">
              <span class="sidebar-context-menu-divider-icon" aria-hidden="true"></span>
              <span>新建分割线</span>
            </button>
          </template>
          <template v-else-if="contentContextMenu.node?.type === 'user-group-separator'">
            <button type="button" role="menuitem" class="sidebar-context-menu-item is-danger" @click="deleteUserGroupSeparator">
              <SvgMaskIcon :src="trashIcon" :size="16" />
              <span>删除分割线</span>
            </button>
          </template>
          <template v-else>
            <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="revealContextMenuLocation">
              <SvgMaskIcon :src="finderIcon" :size="16" />
              <span>在 Finder 中显示</span>
            </button>
            <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="renameContextMenuNode">
              <SvgMaskIcon :src="highlighterIcon" :size="16" />
              <span>{{ contentContextMenu.node?.type === 'folder' ? '编辑文件夹名称' : '编辑文件名' }}</span>
            </button>
            <button
              v-if="contentContextMenu.node?.type === 'folder'"
              type="button"
              role="menuitem"
              class="sidebar-context-menu-item"
              @click="toggleFolderPin"
            >
              <SvgMaskIcon :src="folderPinIcon" :size="16" />
              <span>{{ contentContextMenu.node.raw?.is_pinned ? '取消置顶文件夹' : '置顶文件夹' }}</span>
            </button>
            <template v-if="isContentNode(contentContextMenu.node)">
              <div class="sidebar-context-menu-separator" role="separator"></div>
              <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="setSelectedContentViewed(true)">
                <SvgMaskIcon :src="markReadIcon" :size="16" />
                <span>标记为已读</span>
              </button>
              <button type="button" role="menuitem" class="sidebar-context-menu-item" @click="setSelectedContentViewed(false)">
                <SvgMaskIcon :src="markUnreadIcon" :size="16" />
                <span>标记为未读</span>
              </button>
            </template>
            <div class="sidebar-context-menu-separator" role="separator"></div>
            <button type="button" role="menuitem" class="sidebar-context-menu-item is-danger" @click="deleteContextMenuNode">
              <SvgMaskIcon :src="trashIcon" :size="16" />
              <span>{{ contentContextMenu.node?.type === 'folder' ? '删除文件夹' : '删除文件' }}</span>
            </button>
          </template>
        </div>
      </Transition>
    </Teleport>
  </aside>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { contentIsUnread } from '../features/library/contentReadState.js'
import { ArrowRight, CircleCheck, Delete, Plus } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import PromptFileTree from './PromptFileTree.vue'
import SidebarTreeRow from './SidebarTreeRow.vue'
import { requestDestructiveConfirmation } from '../composables/useDestructiveConfirm'
import sendIcon from '../../assets/arrow.up.circle.fill.svg'
import folderIcon from '../../assets/folder.svg'
import highlighterIcon from '../../assets/highlighter.svg'
import trashIcon from '../../assets/trash.svg'
import folderPinIcon from '../../assets/arrow.up.to.line.svg'
import finderIcon from '../../assets/finder.svg'
import markReadIcon from '../../assets/checkmark.circle.svg'
import markUnreadIcon from '../../assets/x.circle.svg'
import folderAddIcon from '../../assets/folder.badge.plus.svg'
import markdownImportIcon from '../../assets/square.and.arrow.down.svg'
import { libraryContentIcon } from '../utils/contentIcons'

async function requestPermanentDeletion(entry) {
  const confirmed = await requestDestructiveConfirmation({
    title: '彻底删除',
    message: '彻底删除后将同时清理相关缓存，无法恢复。',
    confirmLabel: '彻底删除',
  })
  if (confirmed) emit('permanently-delete-trash', entry)
}

async function requestEmptyTrash() {
  const count = props.trashEntries.length
  if (!count) return
  const confirmed = await requestDestructiveConfirmation({
    title: '清空回收站',
    message: `将彻底删除回收站中的 ${count} 个项目及相关缓存，无法恢复。`,
    confirmLabel: '清空回收站',
  })
  if (confirmed) emit('empty-trash')
}

const props = defineProps({
  activeView: {
    type: String,
    required: true
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
  promptTaskType: {
    type: String,
    default: 'summary'
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
  loadingPromptTrash: { type: Boolean, default: false },
  statusLabel: {
    type: Function,
    required: true
  },
  sourceProviderLabel: {
    type: Function,
    required: true
  },
  promptTaskLabel: {
    type: Function,
    required: true
  },
  formatBytes: {
    type: Function,
    required: true
  }
})

const emit = defineEmits([
  'update:searchQuery',
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
  'update:promptTaskType',
  'load-prompts',
  'select-wechat-report-prompt'
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
const FOLDER_TREE_STATE_KEY = 'knowledgehub:file-tree-open-folders:v2'
const USER_GROUP_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-separators:v2'
const LEGACY_USER_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-user-separators:v1'
const LEGACY_USER_GROUP_SEPARATOR_STATE_KEY = 'knowledgehub:file-tree-user-groups:v1'

function loadUserGroupSeparators() {
  try {
    const saved = window.localStorage.getItem(USER_GROUP_SEPARATOR_STATE_KEY)
    const legacy = window.localStorage.getItem(LEGACY_USER_SEPARATOR_STATE_KEY)
      || window.localStorage.getItem(LEGACY_USER_GROUP_SEPARATOR_STATE_KEY)
    const stored = JSON.parse(saved || legacy || '[]')
    const separators = Array.isArray(stored) ? stored : stored?.separators
    if (!Array.isArray(separators)) return { initialized: Boolean(stored?.initialized), separators: [] }
    return {
      initialized: saved ? Boolean(stored?.initialized) : true,
      separators: separators
      .filter((group) => group && typeof group === 'object' && String(group.id || '').trim())
      .map((group) => ({
        id: String(group.id),
        sortOrder: Number.isFinite(Number(group.sortOrder)) ? Number(group.sortOrder) : null,
        beforeFolderId: group.beforeFolderId ? String(group.beforeFolderId) : null,
      })),
    }
  } catch {
    return { initialized: false, separators: [] }
  }
}

function saveUserGroupSeparators(groups) {
  try {
    window.localStorage.setItem(USER_GROUP_SEPARATOR_STATE_KEY, JSON.stringify({
      version: 2,
      initialized: true,
      separators: groups,
    }))
  } catch {
    // Group separators are presentation-only; a storage failure must not make
    // the library tree unusable.
  }
}

function loadOpenFolderIds() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(FOLDER_TREE_STATE_KEY) || '[]')
    return new Set(Array.isArray(stored) ? stored.map(String) : [])
  } catch {
    return new Set()
  }
}

function saveOpenFolderIds(folderIds) {
  try {
    window.localStorage.setItem(FOLDER_TREE_STATE_KEY, JSON.stringify([...folderIds]))
  } catch {
    // Keep the tree usable when browser storage is unavailable.
  }
}

// An empty saved state deliberately means that every folder starts collapsed.
const openFolderIds = ref(loadOpenFolderIds())
const editingNode = ref(null)
const editingInput = ref(null)
const markdownImportInput = ref(null)
const dragNode = ref(null)
const dragNodes = ref([])
const dropState = ref(null)
const selectedKeys = ref(new Set())
const anchorKey = ref(null)
const treeRef = ref(null)
const treeScrollTop = ref(0)
const treeViewportHeight = ref(0)
const treeIsScrolling = ref(false)
const selectionBox = ref(null)
const selectionStart = ref(null)
const trashOpen = ref(false)
const contentContextMenu = ref(null)
const contentContextMenuRef = ref(null)
const separatorLayoutState = loadUserGroupSeparators()
const userGroupSeparators = ref(separatorLayoutState.separators)
const separatorLayoutInitialized = ref(separatorLayoutState.initialized)
const unreadRootOpen = ref(false)
const pinnedRootOpen = ref(true)
const TREE_ROW_HEIGHT = 26
const TREE_VIRTUAL_OVERSCAN = 12
const ROOT_LIBRARY_GROUPS = {
  inbox: new Set(['待整理收藏']),
  video: new Set(['抖音', 'B站']),
  sources: new Set(['微信公众号', '微信小程序', '校园官网', 'RSS订阅', '外部导入']),
  reports: new Set(['日报', '周报', '月报', '区间汇总', '报告']),
}
const ROOT_LIBRARY_GROUP_ORDER = ['inbox', 'video', 'sources', 'reports', 'other']
let treeResizeObserver = null
let treeScrollEndTimer = null

const searchActive = computed(() => Boolean(props.searchQuery.trim()))
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
  const foldersById = new Map(props.libraryFolders.map((folder) => [String(folder.id), folder]))
  const counts = new Map(props.libraryFolders.map((folder) => [String(folder.id), 0]))
  for (const item of props.libraryContentItems) {
    if (!isUnreadContent(item)) continue
    let folderId = item?.library_folder_id ? String(item.library_folder_id) : ''
    const visited = new Set()
    while (folderId && foldersById.has(folderId) && !visited.has(folderId)) {
      visited.add(folderId)
      counts.set(folderId, (counts.get(folderId) || 0) + 1)
      folderId = foldersById.get(folderId)?.parent_folder_id
        ? String(foldersById.get(folderId).parent_folder_id)
        : ''
    }
  }
  return counts
})

function isUnreadContent(item) {
  return contentIsUnread(item, {
    viewedContentIds: viewedContentIdSet.value,
    explicitlyUnreadContentIds: explicitlyUnreadContentIdSet.value,
    viewedBefore: props.contentViewedBefore,
  })
}

function nodeAriaLabel(node) {
  if (node?.unread) return `${node.name}，新内容`
  if (node?.hasNewDescendants) return `${node.name}，包含 ${node.unreadCount || ''} 条新内容`
  return ''
}

const folderPathById = computed(() => {
  const folders = new Map(props.libraryFolders.map((folder) => [folder.id, folder]))
  const paths = new Map()
  const resolve = (folderId, visiting = new Set()) => {
    if (!folderId || visiting.has(folderId)) return ''
    if (paths.has(folderId)) return paths.get(folderId)
    const folder = folders.get(folderId)
    if (!folder) return ''
    visiting.add(folderId)
    const parentPath = resolve(folder.parent_folder_id || null, visiting)
    visiting.delete(folderId)
    const path = parentPath ? `${parentPath} / ${folder.name}` : folder.name
    paths.set(folderId, path)
    return path
  }
  for (const folderId of folders.keys()) resolve(folderId)
  return paths
})

const unreadContentItems = computed(() => sortNodes(
  props.libraryContentItems.filter(isUnreadContent)
))

function unreadSourcePath(item) {
  return folderPathById.value.get(item?.library_folder_id)
    || item?.source_name
    || '资料库'
}

function toggleTrash() {
  trashOpen.value = !trashOpen.value
  if (trashOpen.value) emit('load-trash')
}

const visibleLibraryNodes = computed(() => {
  if (searchActive.value) {
    return props.sidebarTreeItems.map((item) => ({
      type: 'content',
      id: item.id,
      name: item.title || item.canonical_source_id || '未命名内容',
      parentId: item.library_folder_id || null,
      sortOrder: Number(item.sort_order || 0),
      depth: 0,
      ancestorIds: [],
      unread: isUnreadContent(item),
      raw: item
    }))
  }
  const foldersByParent = new Map()
  const itemsByParent = new Map()
  const foldersById = new Map(props.libraryFolders.map((folder) => [String(folder.id), folder]))

  for (const folder of props.libraryFolders) {
    const parentId = folder.parent_folder_id || null
    if (!foldersByParent.has(parentId)) foldersByParent.set(parentId, [])
    foldersByParent.get(parentId).push(folder)
  }
  for (const item of props.sidebarTreeItems) {
    const parentId = item.library_folder_id || null
    if (!itemsByParent.has(parentId)) itemsByParent.set(parentId, [])
    itemsByParent.get(parentId).push(item)
  }

  const result = []
  const unreadRoot = {
    type: 'unread-root',
    id: '__unread__',
    name: '未读',
    depth: 0,
    hasNewDescendants: true,
    unreadCount: unreadContentItems.value.length,
    raw: null,
  }
  if (unreadContentItems.value.length) {
    result.push(unreadRoot)
    if (isNodeOpen(unreadRoot)) {
      for (const item of unreadContentItems.value) {
        result.push({
          type: 'unread-content',
          id: item.id,
          name: item.title || item.canonical_source_id || '未命名内容',
          depth: 1,
          unread: true,
          raw: item,
        })
      }
    }
  }
  const pinnedFolderIds = new Set(
    props.libraryFolders.filter((folder) => Boolean(folder.is_pinned)).map((folder) => String(folder.id))
  )
  const pinnedRootFolders = props.libraryFolders.filter((folder) => {
    if (!folder.is_pinned) return false
    let parentId = folder.parent_folder_id ? String(folder.parent_folder_id) : ''
    const visited = new Set([String(folder.id)])
    while (parentId && !visited.has(parentId)) {
      visited.add(parentId)
      if (pinnedFolderIds.has(parentId)) return false
      parentId = foldersById.get(parentId)?.parent_folder_id
        ? String(foldersById.get(parentId).parent_folder_id)
        : ''
    }
    return true
  })
  if (pinnedRootFolders.length) {
    result.push({
      type: 'pinned-root',
      id: '__pinned__',
      name: '置顶',
      depth: 0,
      meta: pinnedRootFolders.length,
      raw: null,
    })
  }
  // Unread and pinned views stay ahead of the ordinary tree. The ordinary
  // root order itself is user-controlled through folder and separator drag.
  const appendChildren = (parentId, depth, ancestorIds = [], withinPinnedTree = false) => {
    const folderNodes = sortNodes((foldersByParent.get(parentId) || []).filter((folder) => (
      withinPinnedTree || !folder.is_pinned
    ))).map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      parentId: folder.parent_folder_id || null,
      sortOrder: Number(folder.sort_order || 0),
      depth,
      ancestorIds,
      meta: folderContentCounts.value.get(String(folder.id)) ?? 0,
      hasNewDescendants: Boolean(folderUnreadCounts.value.get(String(folder.id))),
      unreadCount: folderUnreadCounts.value.get(String(folder.id)) || 0,
      raw: folder
    }))
    const contentNodes = sortNodes(itemsByParent.get(parentId) || []).map((item) => ({
      type: 'content',
      id: item.id,
      name: item.title || item.canonical_source_id || '未命名内容',
      parentId: item.library_folder_id || null,
      sortOrder: Number(item.sort_order || 0),
      depth,
      ancestorIds,
      unread: isUnreadContent(item),
      raw: item
    }))

    const nodes = [...folderNodes, ...contentNodes].sort(compareTreeNode)
    for (const node of nodes) {
      result.push(node)
      if (node.type === 'folder' && isFolderOpen(node.id)) {
        appendChildren(node.id, depth + 1, [...ancestorIds, node.id], withinPinnedTree || Boolean(node.raw?.is_pinned))
        const history = folderHistoryState(node.id)
        if (history?.loading || history?.hasMore) {
          result.push({
            type: 'folder-history-more',
            id: `${node.id}:history`,
            parentId: node.id,
            name: history.loading ? '正在加载资料…' : '加载更多资料',
            depth: depth + 1,
            loading: Boolean(history.loading),
          })
        }
      }
    }
  }

  if (pinnedRootFolders.length && pinnedRootOpen.value) {
    const pinnedNodes = sortNodes(pinnedRootFolders).map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      parentId: folder.parent_folder_id || null,
      sortOrder: Number(folder.sort_order || 0),
      depth: 1,
      ancestorIds: [],
      meta: folderContentCounts.value.get(String(folder.id)) ?? 0,
      hasNewDescendants: Boolean(folderUnreadCounts.value.get(String(folder.id))),
      unreadCount: folderUnreadCounts.value.get(String(folder.id)) || 0,
      raw: folder,
    }))
    for (const node of pinnedNodes) {
      result.push(node)
      if (isFolderOpen(node.id)) {
        appendChildren(node.id, 2, [node.id], true)
        const history = folderHistoryState(node.id)
        if (history?.loading || history?.hasMore) {
          result.push({
            type: 'folder-history-more',
            id: `${node.id}:history`,
            parentId: node.id,
            name: history.loading ? '正在加载资料…' : '加载更多资料',
            depth: 2,
            loading: Boolean(history.loading),
          })
        }
      }
    }
  }
  appendChildren(null, 0)
  return result
})

const presentationLibraryNodes = computed(() => {
  if (searchActive.value || !userGroupSeparators.value.length) return visibleLibraryNodes.value
  const rootsById = new Map(
    visibleLibraryNodes.value
      .filter((node) => node.type === 'folder' && node.depth === 0)
      .map((node) => [String(node.id), node]),
  )
  const separators = userGroupSeparators.value
    .map((separator) => ({
      ...separator,
      sortOrder: separatorSortOrder(separator, rootsById),
    }))
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id))
  const result = []
  let separatorIndex = 0
  const appendBefore = (sortOrder) => {
    while (separatorIndex < separators.length && separators[separatorIndex].sortOrder <= sortOrder) {
      const separator = separators[separatorIndex]
      result.push({
        type: 'user-group-separator',
        id: separator.id,
        name: '',
        depth: 0,
        sortOrder: separator.sortOrder,
        raw: separator,
      })
      separatorIndex += 1
    }
  }
  for (const node of visibleLibraryNodes.value) {
    if (node.type === 'folder' && node.depth === 0) appendBefore(Number(node.sortOrder || 0))
    result.push(node)
  }
  while (separatorIndex < separators.length) {
    const separator = separators[separatorIndex]
    result.push({
      type: 'user-group-separator',
      id: separator.id,
      name: '',
      depth: 0,
      sortOrder: separator.sortOrder,
      raw: separator,
    })
    separatorIndex += 1
  }
  return result
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

const virtualTreeStart = computed(() => {
  if (!renderedLibraryNodes.value.length) return 0
  return Math.max(0, Math.floor(treeScrollTop.value / TREE_ROW_HEIGHT) - TREE_VIRTUAL_OVERSCAN)
})

const virtualTreeEnd = computed(() => {
  const viewportRows = Math.ceil(treeViewportHeight.value / TREE_ROW_HEIGHT)
  return Math.min(
    renderedLibraryNodes.value.length,
    virtualTreeStart.value + viewportRows + TREE_VIRTUAL_OVERSCAN * 2
  )
})

const virtualLibraryNodes = computed(() => renderedLibraryNodes.value.slice(virtualTreeStart.value, virtualTreeEnd.value))

const virtualTreeCanvasStyle = computed(() => ({
  height: `${renderedLibraryNodes.value.length * TREE_ROW_HEIGHT}px`
}))

const virtualTreeListStyle = computed(() => ({
  transform: `translateY(${virtualTreeStart.value * TREE_ROW_HEIGHT}px)`
}))

const selectedNodes = computed(() => {
  const selected = selectedKeys.value
  return visibleLibraryNodes.value.filter((node) => selected.has(nodeKey(node)))
})

const selectedContentNodes = computed(() => selectedNodes.value.filter((node) => (
  node.type === 'content' || node.type === 'unread-content'
)))

const contentContextMenuStyle = computed(() => {
  if (!contentContextMenu.value) return {}
  return {
    left: `${contentContextMenu.value.x}px`,
    top: `${contentContextMenu.value.y}px`,
    visibility: contentContextMenu.value.positioned ? 'visible' : 'hidden',
  }
})

function isRootLayoutNode(node) {
  return node?.type === 'user-group-separator' || (node?.type === 'folder' && node.depth === 0)
}

function layoutSortOrder(node) {
  return Number(node?.sortOrder ?? node?.raw?.sortOrder ?? 0)
}

function sortOrderBetween(previous, next) {
  const before = previous ? layoutSortOrder(previous) : null
  const after = next ? layoutSortOrder(next) : null
  if (before !== null && after !== null && after > before) return (before + after) / 2
  if (before !== null) return before + 1
  if (after !== null) return after - 1
  return 0
}

function rootLayoutEntries({ excludeFolderIds = new Set(), excludeSeparatorIds = new Set() } = {}) {
  const folders = visibleLibraryNodes.value.filter((node) => (
    node.type === 'folder' && node.depth === 0 && !excludeFolderIds.has(String(node.id))
  ))
  const separators = userGroupSeparators.value
    .filter((separator) => !excludeSeparatorIds.has(String(separator.id)))
    .map((separator) => ({
      type: 'user-group-separator',
      id: separator.id,
      sortOrder: separatorSortOrder(separator),
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

const selectionBoxStyle = computed(() => {
  const box = selectionBox.value
  if (!box) return {}
  return {
    left: `${box.left}px`,
    top: `${box.top}px`,
    width: `${box.width}px`,
    height: `${box.height}px`,
  }
})

function sortNodes(nodes) {
  return [...nodes].sort((left, right) => {
    if (isContentItem(left) || isContentItem(right)) {
      return recentTimestamp(right) - recentTimestamp(left)
        || String(right.created_at || '').localeCompare(String(left.created_at || ''))
        || String(left.title || left.name || '').localeCompare(String(right.title || right.name || ''))
    }
    return Number(left.sort_order || 0) - Number(right.sort_order || 0)
      || String(right.created_at || '').localeCompare(String(left.created_at || ''))
      || String(left.title || left.name || '').localeCompare(String(right.title || right.name || ''))
  })
}

function compareTreeNode(left, right) {
  if (left.type === 'content' && right.type === 'content') {
    return recentTimestamp(right.raw) - recentTimestamp(left.raw)
      || left.name.localeCompare(right.name)
  }
  return left.sortOrder - right.sortOrder
    || (left.type === right.type ? 0 : left.type === 'folder' ? -1 : 1)
    || left.name.localeCompare(right.name)
}

function compareRootTreeNode(left, right) {
  const groupOrder = ROOT_LIBRARY_GROUP_ORDER.indexOf(rootLibraryGroup(left))
  const otherGroupOrder = ROOT_LIBRARY_GROUP_ORDER.indexOf(rootLibraryGroup(right))
  if (groupOrder !== otherGroupOrder) return groupOrder - otherGroupOrder
  return compareTreeNode(left, right)
}

function rootLibraryGroup(node) {
  if (node?.type !== 'folder') return 'other'
  const presentationGroup = String(node.raw?.presentation_group || '')
  if (presentationGroup === 'manual:default') return 'inbox'
  if (presentationGroup.startsWith('provider:')) {
    const provider = presentationGroup.slice('provider:'.length)
    if (provider === 'douyin' || provider === 'bilibili') return 'video'
    if (['wechat', 'campus', 'wechat_miniprogram', 'rss', 'xiaohongshu'].includes(provider)) return 'sources'
  }
  if (presentationGroup === 'external') return 'sources'
  // Legacy folders may not have a stable binding until the next backend
  // refresh. Retain the old name fallback for those existing rows only.
  const name = String(node.name || '').trim()
  if (ROOT_LIBRARY_GROUPS.inbox.has(name)) return 'inbox'
  if (ROOT_LIBRARY_GROUPS.video.has(name)) return 'video'
  if (ROOT_LIBRARY_GROUPS.sources.has(name)) return 'sources'
  if (ROOT_LIBRARY_GROUPS.reports.has(name)) return 'reports'
  return 'other'
}

function rootFolderNodes() {
  return props.libraryFolders
    .filter((folder) => !folder.parent_folder_id && !folder.is_pinned)
    .map((folder) => ({
      type: 'folder',
      id: folder.id,
      name: folder.name,
      sortOrder: Number(folder.sort_order || 0),
      raw: folder,
    }))
}

function separatorSortOrder(separator, rootsById = null) {
  const saved = Number(separator?.sortOrder)
  if (Number.isFinite(saved)) return saved
  const roots = rootsById || new Map(rootFolderNodes().map((node) => [String(node.id), node]))
  const anchor = roots.get(String(separator?.beforeFolderId || ''))
  if (anchor) return Number(anchor.sortOrder || 0) - 0.5
  const last = [...roots.values()].sort(compareTreeNode).at(-1)
  return last ? Number(last.sortOrder || 0) + 1 : 0
}

function createDefaultSeparators() {
  const roots = rootFolderNodes().sort(compareRootTreeNode)
  const separators = []
  let previous = null
  for (const node of roots) {
    if (previous && rootLibraryGroup(node) !== rootLibraryGroup(previous)) {
      const before = Number(previous.sortOrder || 0)
      const after = Number(node.sortOrder || 0)
      separators.push({
        id: window.crypto?.randomUUID?.() || `separator-${Date.now()}-${separators.length}`,
        sortOrder: after > before ? (before + after) / 2 : after - 0.5,
      })
    }
    previous = node
  }
  return separators
}

watch(
  () => props.libraryFolders.map((folder) => `${folder.id}:${folder.parent_folder_id || ''}:${folder.sort_order}:${folder.is_pinned ? 1 : 0}`).join('|'),
  () => {
    const roots = rootFolderNodes()
    if (!roots.length) return
    if (!separatorLayoutInitialized.value) {
      userGroupSeparators.value = createDefaultSeparators()
      separatorLayoutInitialized.value = true
      saveUserGroupSeparators(userGroupSeparators.value)
      return
    }
    const rootsById = new Map(roots.map((node) => [String(node.id), node]))
    const migrated = userGroupSeparators.value.map((separator) => ({
      ...separator,
      sortOrder: separatorSortOrder(separator, rootsById),
      beforeFolderId: undefined,
    }))
    if (migrated.some((separator, index) => separator.sortOrder !== userGroupSeparators.value[index]?.sortOrder || userGroupSeparators.value[index]?.beforeFolderId)) {
      userGroupSeparators.value = migrated
      saveUserGroupSeparators(migrated)
    }
  },
  { immediate: true },
)

function isContentItem(node) {
  return Boolean(node && ('source_provider' in node || 'content_type' in node || 'canonical_source_id' in node))
}

function recentTimestamp(item) {
  const value = item?.published_at || item?.created_at || item?.updated_at || ''
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : 0
}

function contentNodeTitle(node) {
  if (!isContentNode(node)) return node?.name || ''
  if (node.type === 'unread-content') {
    return `${node.name}\n${unreadSourcePath(node.raw)}`
  }
  const source = [node.raw?.source_name, node.raw?.source_section].filter(Boolean).join(' · ')
  return source ? `${node.name}\n${source}` : node.name
}

function contentIcon(item) {
  return libraryContentIcon(item)
}

function trashEntryIcon(entry) {
  return entry?.entry_type === 'content' ? contentIcon(entry) : folderIcon
}

function handleTreeScroll(event) {
  closeContentContextMenu()
  treeScrollTop.value = event.currentTarget.scrollTop
  treeIsScrolling.value = true
  window.clearTimeout(treeScrollEndTimer)
  treeScrollEndTimer = window.setTimeout(() => {
    treeIsScrolling.value = false
  }, 80)
}

onMounted(() => {
  const tree = treeRef.value
  if (!tree) return
  treeScrollTop.value = tree.scrollTop
  treeViewportHeight.value = tree.clientHeight
  treeResizeObserver = new ResizeObserver(() => {
    treeViewportHeight.value = tree.clientHeight
  })
  treeResizeObserver.observe(tree)
  window.addEventListener('pointerdown', closeContentContextMenu)
  window.addEventListener('keydown', closeContentContextMenuOnEscape)
})

onBeforeUnmount(() => {
  cancelBoxSelection()
  treeResizeObserver?.disconnect()
  treeResizeObserver = null
  window.clearTimeout(treeScrollEndTimer)
  treeScrollEndTimer = null
  window.removeEventListener('pointerdown', closeContentContextMenu)
  window.removeEventListener('keydown', closeContentContextMenuOnEscape)
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

function expandUnreadInNode(node) {
  if (!node?.unreadCount) return
  if (node.type === 'unread-root') {
    unreadRootOpen.value = !unreadRootOpen.value
    return
  }
  const open = new Set(openFolderIds.value)

  if (node.type === 'folder') {
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
  } else {
    return
  }

  openFolderIds.value = open
  saveOpenFolderIds(open)
}

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
    positioned: false,
  }
  nextTick(positionContentContextMenu)
}

function positionContentContextMenu() {
  const menu = contentContextMenu.value
  const element = contentContextMenuRef.value
  if (!menu || !element) return
  const margin = 8
  const x = Math.max(margin, Math.min(menu.x, window.innerWidth - element.offsetWidth - margin))
  const y = Math.max(margin, Math.min(menu.y, window.innerHeight - element.offsetHeight - margin))
  contentContextMenu.value = { ...menu, x, y, positioned: true }
  nextTick(() => {
    contentContextMenuRef.value?.querySelector('[role="menuitem"]:not(:disabled)')?.focus()
  })
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

function closeContentContextMenuOnEscape(event) {
  if (event.key !== 'Escape' || !contentContextMenu.value) return
  event.preventDefault()
  closeContentContextMenu({ restoreFocus: true })
}

function handleContentContextMenuKeydown(event) {
  if (event.key === 'Tab') {
    event.preventDefault()
    closeContentContextMenu({ restoreFocus: true })
    return
  }
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End']
  if (!keys.includes(event.key)) return
  const menuItems = Array.from(contentContextMenuRef.value?.querySelectorAll('[role="menuitem"]:not(:disabled)') || [])
  if (!menuItems.length) return
  event.preventDefault()
  const focusedIndex = menuItems.indexOf(document.activeElement)
  const currentIndex = focusedIndex >= 0 ? focusedIndex : 0
  let nextIndex = currentIndex
  if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1 + menuItems.length) % menuItems.length
  if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + menuItems.length) % menuItems.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = menuItems.length - 1
  menuItems[nextIndex]?.focus()
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

function markFolderViewed(folderNode) {
  const folderIds = new Set([String(folderNode.id)])
  let changed = true
  while (changed) {
    changed = false
    for (const folder of props.libraryFolders) {
      const folderId = String(folder.id)
      if (folderIds.has(folderId) || !folder.parent_folder_id) continue
      if (folderIds.has(String(folder.parent_folder_id))) {
        folderIds.add(folderId)
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
    parentFolderId: parentFolderId || null
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
    isNew: false
  }
  focusEditingInput()
}

function isEditing(node) {
  return editingNode.value && !editingNode.value.isNew && editingNode.value.type === node.type && editingNode.value.id === node.id
}

function focusEditingInput() {
  nextTick(() => {
    const target = Array.isArray(editingInput.value) ? editingInput.value.at(-1) : editingInput.value
    target?.focus()
    target?.select()
  })
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
      parent_folder_id: current.parentFolderId
    })
  } else if (current.type === 'folder') {
    emit('rename-folder', { id: current.id, name: value })
  } else {
    emit('rename-content', { id: current.id, title: value })
  }
  editingNode.value = null
}

function cancelEditing() {
  editingNode.value = null
}

function requestDelete(node) {
  if (node.type === 'folder') {
    emit('delete-folder', node.raw)
  } else {
    emit('delete-content', node.raw)
  }
}

function onDragStart(event, node) {
  if (searchActive.value) return
  if (node.type === 'user-group-separator') {
    dragNode.value = node
    dragNodes.value = []
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', '分割线')
    return
  }
  const key = nodeKey(node)
  if (!selectedKeys.value.has(key)) {
    setSelectedKeys([key])
    anchorKey.value = key
  }
  dragNode.value = node
  dragNodes.value = visibleLibraryNodes.value.filter((item) => selectedKeys.value.has(nodeKey(item)))
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', dragNodes.value.map((item) => item.name).join(', '))
}

function hasExternalFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes('Files')
}

function externalImportTargetFolderId(node) {
  let folderId = node.type === 'folder' ? node.id : node.parentId
  const folders = new Map(props.libraryFolders.map((folder) => [String(folder.id), folder]))
  const visited = new Set()
  while (folderId && !visited.has(String(folderId))) {
    const folder = folders.get(String(folderId))
    if (!folder) return null
    if (folder.name === '外部导入') return String(node.type === 'folder' ? node.id : node.parentId)
    visited.add(String(folderId))
    folderId = folder.parent_folder_id ? String(folder.parent_folder_id) : null
  }
  return null
}

function handleNodeDragOver(event, node) {
  if (hasExternalFiles(event)) {
    const folderId = externalImportTargetFolderId(node)
    if (!folderId) return
    event.dataTransfer.dropEffect = 'copy'
    dropState.value = { targetType: node.type, targetId: node.id, position: 'inside' }
    return
  }
  if (node.type === 'user-group-separator') {
    onSeparatorDragOver(event, node)
  } else if (isMutableLibraryNode(node)) {
    onDragOver(event, node)
  }
}

function handleNodeDrop(event, node) {
  if (hasExternalFiles(event)) {
    const files = Array.from(event.dataTransfer?.files || [])
    const libraryFolderId = externalImportTargetFolderId(node)
    clearDragState()
    if (files.length && libraryFolderId) emit('import-markdown', { files, libraryFolderId })
    return
  }
  if (node.type === 'user-group-separator') {
    onSeparatorDrop(node)
  } else if (dragNode.value?.type === 'user-group-separator') {
    onSeparatorDropOnFolder(node)
  } else if (isMutableLibraryNode(node)) {
    onDrop(node)
  }
}

function canDropOnUserSeparator() {
  if (dragNode.value?.type === 'user-group-separator') return true
  const candidates = dragNodes.value.length ? dragNodes.value : [dragNode.value]
  return candidates.length > 0 && candidates.every((node) => (
    node?.type === 'folder' && !node.parentId
  ))
}

function onSeparatorDragOver(event, node) {
  if (searchActive.value || !dragNode.value || !canDropOnUserSeparator()) return
  const rect = event.currentTarget.getBoundingClientRect()
  const position = event.clientY - rect.top < rect.height / 2 ? 'before' : 'after'
  event.dataTransfer.dropEffect = 'move'
  dropState.value = { targetType: node.type, targetId: node.id, position }
}

function separatorDropTarget(node) {
  return node
}

function onSeparatorDrop(node) {
  if (searchActive.value || !dragNode.value || !dropState.value || !canDropOnUserSeparator()) {
    clearDragState()
    return
  }
  if (dragNode.value.type === 'user-group-separator') {
    moveUserSeparator(dragNode.value.id, node, dropState.value.position)
    clearDragState()
    return
  }
  const target = separatorDropTarget(node)
  const sortOrder = sortOrderNearSeparator(node, dropState.value.position, dragNodes.value)
  const payload = {
    drag: dragNode.value,
    drags: dragNodes.value.length ? dragNodes.value : [dragNode.value],
    target,
    position: dropState.value.position,
    parentId: null,
    sortOrder,
  }
  if (payload.drags.length > 1) emit('move-nodes', payload)
  else emit('move-node', payload)
  clearDragState()
}

function onSeparatorDropOnFolder(target) {
  if (searchActive.value || !dragNode.value || !dropState.value || target.type !== 'folder' || target.depth !== 0) {
    clearDragState()
    return
  }
  moveUserSeparator(dragNode.value.id, target, dropState.value.position)
  clearDragState()
}

function onDragOver(event, node) {
  if (searchActive.value) return
  if (!dragNode.value || dragNodes.value.some((item) => item.type === node.type && item.id === node.id)) return
  if (dragNode.value.type === 'user-group-separator' && (node.type !== 'folder' || node.depth !== 0)) return
  const rect = event.currentTarget.getBoundingClientRect()
  const y = event.clientY - rect.top
  const ratio = rect.height ? y / rect.height : 0.5
  let position = 'inside'
  if (ratio < 0.28) position = 'before'
  else if (ratio > 0.72) position = 'after'
  else if (node.type !== 'folder' || dragNode.value.type === 'user-group-separator') position = 'after'
  dropState.value = { targetType: node.type, targetId: node.id, position }
}

function onDrop(node) {
  if (searchActive.value) {
    clearDragState()
    return
  }
  if (!dragNode.value || !dropState.value) return
  const payload = {
    drag: dragNode.value,
    drags: dragNodes.value.length ? dragNodes.value : [dragNode.value],
    target: node,
    position: dropState.value.position
  }
  if (payload.drags.length > 1) emit('move-nodes', payload)
  else emit('move-node', payload)
  clearDragState()
}

function isDropTarget(node, position) {
  return dropState.value
    && dropState.value.targetType === node.type
    && dropState.value.targetId === node.id
    && dropState.value.position === position
}

function clearDropState() {
  dropState.value = null
}

function clearDragState() {
  dragNode.value = null
  dragNodes.value = []
  dropState.value = null
  cancelBoxSelection()
}

function requestDeleteSelected() {
  if (!selectedNodes.value.length) return
  emit('delete-selected', selectedNodes.value.map((node) => node.raw ? { ...node.raw, type: node.type } : node))
  selectedKeys.value = new Set()
}

function startBoxSelection(event) {
  if (event.button !== 0) return
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('[data-node-key],button,input,.sidebar-tree-row-actions,.sidebar-selection-bar,.el-popper')) return
  const tree = treeRef.value
  if (!tree) return
  tree.setPointerCapture?.(event.pointerId)
  const rect = tree.getBoundingClientRect()
  selectionStart.value = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top + tree.scrollTop,
    additive: event.metaKey || event.ctrlKey,
    base: new Set(event.metaKey || event.ctrlKey ? selectedKeys.value : []),
  }
  selectionBox.value = {
    left: selectionStart.value.x,
    top: selectionStart.value.y,
    width: 0,
    height: 0,
  }
  tree.addEventListener('pointermove', updateBoxSelection)
  tree.addEventListener('pointerup', finishBoxSelection, { once: true })
}

function updateBoxSelection(event) {
  const tree = treeRef.value
  const start = selectionStart.value
  if (!tree || !start) return
  const rect = tree.getBoundingClientRect()
  const currentX = event.clientX - rect.left
  const currentY = event.clientY - rect.top + tree.scrollTop
  const left = Math.min(start.x, currentX)
  const top = Math.min(start.y, currentY)
  const right = Math.max(start.x, currentX)
  const bottom = Math.max(start.y, currentY)
  selectionBox.value = {
    left,
    top,
    width: right - left,
    height: bottom - top,
  }
  const next = new Set(start.base)
  tree.querySelectorAll('[data-node-key]').forEach((element) => {
    const nodeRect = element.getBoundingClientRect()
    const elementBox = {
      left: nodeRect.left - rect.left,
      right: nodeRect.right - rect.left,
      top: nodeRect.top - rect.top + tree.scrollTop,
      bottom: nodeRect.bottom - rect.top + tree.scrollTop,
    }
    const intersects = elementBox.left < right
      && elementBox.right > left
      && elementBox.top < bottom
      && elementBox.bottom > top
    if (intersects) next.add(element.dataset.nodeKey)
  })
  setSelectedKeys(next)
}

function finishBoxSelection() {
  cancelBoxSelection()
  anchorKey.value = [...selectedKeys.value].at(-1) || anchorKey.value
}

function cancelBoxSelection() {
  treeRef.value?.removeEventListener('pointermove', updateBoxSelection)
  selectionBox.value = null
  selectionStart.value = null
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

.sidebar-search-row {
  grid-template-columns: minmax(0, 1fr) 26px 26px;
  align-items: center;
  gap: 4px;
}

.sidebar-file-picker {
  position: fixed;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.sidebar-search-row :deep(.el-input__wrapper) {
  height: 30px;
  min-height: 30px;
  padding-top: 0;
  padding-bottom: 0;
  border-radius: 999px !important;
  background: color-mix(in srgb, var(--vk-bg-panel) 88%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--vk-border) 78%, transparent);
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

.sidebar-trash {
  min-width: 0;
  margin: 0 calc(var(--vk-space-control) + 4px) 0 4px;
  border-top: 1px solid var(--vk-border);
  padding-top: 5px;
  background: var(--vk-bg-quiet);
}

.sidebar-trash-toggle {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto 14px;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 28px;
  padding: 0 6px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--vk-muted);
  text-align: left;
  cursor: pointer;
}

.sidebar-trash-toggle:hover { background: var(--vk-bg-hover); color: var(--vk-text); }
.sidebar-trash-toggle small { color: var(--vk-muted); font-size: var(--vk-type-micro-size); }
.sidebar-trash-arrow { transition: transform 0.16s ease; }
.sidebar-trash.open .sidebar-trash-arrow { transform: rotate(90deg); }
.sidebar-trash-list {
  --el-loading-spinner-size: 14px;
  display: grid;
  gap: 2px;
  min-height: 28px;
  padding: 3px 0 0 18px;
}
.sidebar-trash-list-enter-active { transition: opacity var(--vk-motion-standard) var(--vk-ease-out), transform var(--vk-motion-standard) var(--vk-ease-out); }
.sidebar-trash-list-leave-active { transition: opacity var(--vk-motion-fast) var(--vk-ease-out), transform var(--vk-motion-fast) var(--vk-ease-out); }
.sidebar-trash-list-enter-from,
.sidebar-trash-list-leave-to { opacity: 0; transform: translateY(-4px); }
.sidebar-trash-list :deep(.el-loading-spinner) {
  margin-top: -7px;
}
.sidebar-trash-list :deep(.el-loading-spinner .circular) {
  width: 14px;
  height: 14px;
}
.sidebar-trash-actions { display: flex; justify-content: flex-end; min-height: 23px; padding-right: 2px; }
.sidebar-trash-actions button { padding: 2px 3px; border: 0; background: transparent; color: var(--vk-error-text); font: inherit; font-size: var(--vk-type-meta-size); cursor: pointer; }
.sidebar-trash-entry { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto auto; align-items: center; gap: 5px; min-height: 27px; color: var(--vk-muted); font-size: var(--vk-type-meta-size); }
.sidebar-trash-entry > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-trash-entry button { padding: 2px 3px; border: 0; background: transparent; color: var(--vk-accent-strong); font: inherit; cursor: pointer; }
.sidebar-trash-entry button.danger { color: var(--vk-error-text); }
.sidebar-trash-empty { margin: 5px 0; color: var(--vk-muted); font-size: var(--vk-type-meta-size); }

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

.sidebar-link-dock {
  padding: 8px 2px 0;
  border-top: 1px solid var(--vk-border);
}

.sidebar-process-input {
  position: relative;
  min-width: 0;
  border: 1px solid color-mix(in srgb, var(--vk-border) 80%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--vk-bg-panel) 84%, transparent);
  box-shadow: 0 5px 14px color-mix(in srgb, var(--vk-text) 3%, transparent);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    background-color 0.16s ease;
}

.sidebar-process-input :deep(.el-textarea__inner) {
  min-height: 54px !important;
  padding: 9px 42px 9px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  box-shadow: none;
  color: var(--vk-text);
  line-height: 1.45;
}

.sidebar-process-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.sidebar-run-button {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0;
  border: 0;
  background: transparent !important;
  color: var(--vk-accent-strong) !important;
  box-shadow: none !important;
}

.sidebar-run-button:hover:not(:disabled),
.sidebar-run-button:focus-visible {
  background: transparent !important;
  color: var(--vk-accent-strong) !important;
  box-shadow: none !important;
}

.sidebar-run-button:disabled {
  background: transparent !important;
  color: var(--vk-muted) !important;
  opacity: 0.42;
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

.sidebar-context-menu {
  position: fixed;
  z-index: 3200;
  display: grid;
  width: max-content;
  min-width: 196px;
  max-width: min(280px, calc(100vw - 16px));
  padding: 5px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--vk-border) 78%, transparent);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
  transform-origin: top left;
}

.sidebar-context-menu-item {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  align-items: center;
  min-height: 32px;
  gap: var(--vk-space-control);
  width: 100%;
  padding: 0 9px;
  border: 0;
  border-radius: var(--vk-radius-control);
  background: transparent;
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.sidebar-context-menu-item > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-context-menu-item :deep(.svg-mask-icon) { opacity: .72; }

.sidebar-context-menu-item:hover,
.sidebar-context-menu-item:focus-visible {
  outline: none;
  background: color-mix(in srgb, var(--vk-bg-hover) 78%, var(--vk-bg-panel));
}

.sidebar-context-menu-item:hover :deep(.svg-mask-icon),
.sidebar-context-menu-item:focus-visible :deep(.svg-mask-icon) { opacity: 1; }

.sidebar-context-menu-item.is-danger {
  color: var(--vk-danger, var(--vk-error-text));
}

.sidebar-context-menu-item.is-danger:hover,
.sidebar-context-menu-item.is-danger:focus-visible {
  background: color-mix(in srgb, var(--vk-danger, var(--vk-error-text)) 8%, var(--vk-bg-panel));
}

.sidebar-context-menu-separator {
  height: 1px;
  margin: 5px 4px;
  background: color-mix(in srgb, var(--vk-border) 72%, transparent);
}

.sidebar-context-menu-divider-icon {
  position: relative;
  display: block;
  width: 16px;
  height: 16px;
}

.sidebar-context-menu-divider-icon::after {
  position: absolute;
  top: 50%;
  right: 1px;
  left: 1px;
  height: 1px;
  background: currentColor;
  content: '';
  opacity: .66;
}

.sidebar-context-menu-enter-active,
.sidebar-context-menu-leave-active {
  transition: opacity 120ms var(--vk-ease-out), transform 120ms var(--vk-ease-out);
}

.sidebar-context-menu-enter-from,
.sidebar-context-menu-leave-to {
  opacity: 0;
  transform: scale(0.97);
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
  .sidebar-trash-list-leave-active,
  .sidebar-context-menu-enter-active,
  .sidebar-context-menu-leave-active {
    transition: opacity var(--vk-motion-fast) ease;
  }

  .sidebar-node-list-enter-from,
  .sidebar-node-list-leave-to,
  .sidebar-selection-bar-enter-from,
  .sidebar-selection-bar-leave-to,
  .sidebar-trash-list-enter-from,
  .sidebar-trash-list-leave-to,
  .sidebar-context-menu-enter-from,
  .sidebar-context-menu-leave-to {
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
