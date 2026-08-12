<template>
  <div class="prompt-file-tree">
    <div class="prompt-tree-scroll">
      <section v-if="groupedSystemPrompts.length" class="prompt-tree-group">
        <SidebarTreeRow
          class="prompt-tree-root"
          kind="folder"
          tone="strong"
          label="系统提示词"
          label-title="固定系统规则，仅供查看；可配置提示词请在对应功能目录编辑"
          :meta="groupedSystemPromptCount"
          :open="isOpen('system-prompts')"
          @activate="toggleOpen('system-prompts')"
        />

        <Transition name="prompt-tree-branch">
          <div v-show="isOpen('system-prompts')" class="prompt-tree-branch">
            <template v-for="group in groupedSystemPrompts" :key="group.id">
              <SidebarTreeRow
                class="prompt-tree-task"
                kind="folder"
                tone="medium"
                :label="group.name"
                :meta="group.prompts.length"
                :depth="1"
                :open="isOpen(`system-group:${group.id}`)"
                @activate="toggleOpen(`system-group:${group.id}`)"
              />
              <Transition name="prompt-tree-branch">
                <div v-show="isOpen(`system-group:${group.id}`)" class="prompt-tree-branch">
                  <SidebarTreeRow
                    v-for="prompt in group.prompts"
                    :key="prompt.id"
                    class="prompt-tree-file prompt-tree-system-file"
                    kind="file"
                    :label="prompt.name"
                    :label-title="prompt.description"
                    :icon="appendPageIcon"
                    :depth="2"
                    :active="activeNodeId === `system:${prompt.id}`"
                    status="只读"
                    @activate="emit('open-system-prompt', prompt)"
                  />
                </div>
              </Transition>
            </template>
          </div>
        </Transition>
      </section>

      <section v-if="groupedPromptContexts.length" class="prompt-tree-group">
        <SidebarTreeRow
          class="prompt-tree-root"
          kind="folder"
          tone="strong"
          label="任务上下文"
          label-title="随任务发送给模型的上下文，不属于 system prompt"
          :meta="groupedPromptContextCount"
          :open="isOpen('prompt-contexts')"
          @activate="toggleOpen('prompt-contexts')"
        />

        <Transition name="prompt-tree-branch">
          <div v-show="isOpen('prompt-contexts')" class="prompt-tree-branch">
            <template v-for="group in groupedPromptContexts" :key="group.id">
              <SidebarTreeRow
                class="prompt-tree-task"
                kind="folder"
                tone="medium"
                :label="group.name"
                :meta="group.prompts.length"
                :depth="1"
                :open="isOpen(`context-group:${group.id}`)"
                @activate="toggleOpen(`context-group:${group.id}`)"
              />
              <Transition name="prompt-tree-branch">
                <div v-show="isOpen(`context-group:${group.id}`)" class="prompt-tree-branch">
                  <SidebarTreeRow
                    v-for="prompt in group.prompts"
                    :key="prompt.id"
                    class="prompt-tree-file"
                    kind="file"
                    :label="prompt.name"
                    :label-title="prompt.description"
                    :icon="appendPageIcon"
                    :depth="2"
                    :active="activeNodeId === `context:${prompt.id}`"
                    status="只读"
                    @activate="emit('open-prompt-context', prompt)"
                  />
                </div>
              </Transition>
            </template>
          </div>
        </Transition>
      </section>

      <section v-for="group in groupedTasks" :key="group.id" class="prompt-tree-group">
        <SidebarTreeRow
          class="prompt-tree-root"
          kind="folder"
          tone="strong"
          :label="group.label"
          :meta="group.count"
          :open="isOpen(`group:${group.id}`)"
          @activate="toggleOpen(`group:${group.id}`)"
        />

        <Transition name="prompt-tree-branch">
          <div v-show="isOpen(`group:${group.id}`)" class="prompt-tree-branch">
            <template v-for="task in group.tasks" :key="task.value">
              <SidebarTreeRow
                v-if="task.value !== 'wechat_reports'"
                class="prompt-tree-task"
                kind="folder"
                tone="medium"
                :label="task.label"
                :meta="task.count"
                :depth="1"
                :open="isOpen(`task:${task.value}`)"
                :drop-position="dropKey === `task:${task.value}` ? 'inside' : ''"
                :action-width="44"
                @activate="toggleOpen(`task:${task.value}`)"
                @dragover.prevent="handleDragOver($event, task.value, null, `task:${task.value}`)"
                @dragleave="dropKey = ''"
                @drop.prevent="handleDrop(task.value, null)"
              >
                <template v-if="task.value !== 'wechat_reports'" #actions>
                  <el-tooltip content="新建提示词" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="新建提示词" @click.stop="requestNewPrompt(task.value, null)">
                      <SvgMaskIcon :src="appendPageIcon" :size="14" />
                    </button>
                  </el-tooltip>
                  <el-tooltip content="新建子文件夹" placement="top">
                    <button class="sidebar-tree-action" type="button" aria-label="新建子文件夹" @click.stop="startNewFolder(task.value, null)">
                      <el-icon><Plus /></el-icon>
                    </button>
                  </el-tooltip>
                </template>
              </SidebarTreeRow>

              <Transition name="prompt-tree-branch">
                <div v-show="task.value === 'wechat_reports' || isOpen(`task:${task.value}`)" class="prompt-tree-branch">
                  <template v-if="task.value === 'wechat_reports'">
                    <template v-for="group in groupedReportPrompts" :key="group.id">
                      <SidebarTreeRow
                        class="prompt-tree-task"
                        kind="folder"
                        tone="medium"
                        :label="group.name"
                        :label-title="group.name"
                        :meta="group.prompts.length"
                        :depth="1"
                        :open="isOpen(`report-group:${group.id}`)"
                        @activate="toggleOpen(`report-group:${group.id}`)"
                      />
                      <Transition name="prompt-tree-branch">
                        <div v-show="isOpen(`report-group:${group.id}`)" class="prompt-tree-branch">
                          <SidebarTreeRow
                            v-for="prompt in group.prompts"
                            :key="prompt.id"
                            class="prompt-tree-file prompt-tree-report-file"
                            kind="file"
                            :label="prompt.display_name"
                            :label-title="prompt.display_name"
                            :icon="appendPageIcon"
                            :depth="2"
                            :active="activeNodeId === `report:${prompt.id}`"
                            @activate="emit('open-prompt', { kind: 'report', prompt })"
                          />
                        </div>
                      </Transition>
                    </template>
                    <p v-if="!reportPrompts.length" class="prompt-tree-empty">先创建报告分组</p>
                  </template>

                  <template v-else>
                    <template v-for="node in visibleTaskNodes(task.value)" :key="`${node.kind}:${node.id}`">
                      <SidebarTreeRow
                        v-if="node.kind === 'draft-folder' || node.kind === 'draft-prompt'"
                        :kind="node.kind === 'draft-folder' ? 'folder' : 'file'"
                        editing
                        :depth="node.depth"
                      >
                        <template #editing>
                          <span v-if="node.kind === 'draft-folder'" class="prompt-tree-edit-spacer" aria-hidden="true"></span>
                          <SvgMaskIcon v-else :src="appendPageIcon" :size="14" />
                          <input
                            ref="editingInputs"
                            v-model="editingValue"
                            class="prompt-tree-input"
                            :name="node.kind === 'draft-folder' ? 'prompt-folder-name' : 'prompt-file-name'"
                            autocomplete="off"
                            :aria-label="node.kind === 'draft-folder' ? '新提示词文件夹名称' : '新提示词名称'"
                            @keydown.enter.prevent="node.kind === 'draft-folder' ? commitNewFolder() : commitNewPrompt()"
                            @keydown.esc.prevent="cancelEditing"
                            @blur="cancelEditing"
                          />
                        </template>
                      </SidebarTreeRow>

                      <SidebarTreeRow
                        v-else-if="node.kind === 'folder'"
                        class="prompt-tree-user-folder"
                        kind="folder"
                        :label="node.name"
                        :label-title="node.name"
                        :depth="node.depth"
                        :open="isOpen(`folder:${node.id}`)"
                        :editing="editingKey === `folder:${node.id}`"
                        :drop-position="dropKey === `folder:${node.id}` ? 'inside' : ''"
                        :action-width="92"
                        draggable="true"
                        @activate="toggleOpen(`folder:${node.id}`)"
                        @dragstart="startDrag('folder', node.raw)"
                        @dragover.prevent="handleDragOver($event, task.value, node.id, `folder:${node.id}`)"
                        @dragleave="dropKey = ''"
                        @drop.prevent="handleDrop(task.value, node.id)"
                        @dragend="clearDrag"
                      >
                        <template #editing>
                          <span class="prompt-tree-edit-spacer" aria-hidden="true"></span>
                          <input
                            ref="editingInputs"
                            v-model="editingValue"
                            class="prompt-tree-input"
                            name="prompt-folder-name"
                            autocomplete="off"
                            :aria-label="`重命名 ${node.name}`"
                            @keydown.enter.prevent="commitRename"
                            @keydown.esc.prevent="cancelEditing"
                            @blur="cancelEditing"
                          />
                        </template>
                        <template #actions>
                            <el-tooltip content="新建提示词" placement="top">
                              <button class="sidebar-tree-action" type="button" aria-label="新建提示词" @click.stop="requestNewPrompt(task.value, node.id)">
                                <SvgMaskIcon :src="appendPageIcon" :size="14" />
                              </button>
                            </el-tooltip>
                            <el-tooltip content="新建子文件夹" placement="top">
                              <button class="sidebar-tree-action" type="button" aria-label="新建子文件夹" @click.stop="startNewFolder(task.value, node.id)">
                                <el-icon><Plus /></el-icon>
                              </button>
                            </el-tooltip>
                            <el-tooltip content="重命名" placement="top">
                              <button class="sidebar-tree-action" type="button" aria-label="重命名" @click.stop="startRename('folder', node.raw, node.name)">
                                <SvgMaskIcon :src="highlighterIcon" :size="14" />
                              </button>
                            </el-tooltip>
                            <el-tooltip content="移入回收站" placement="top">
                              <button class="sidebar-tree-action danger" type="button" aria-label="移入回收站" @click.stop="emit('delete-folder', node.raw)">
                                <SvgMaskIcon :src="trashIcon" :size="14" />
                              </button>
                            </el-tooltip>
                        </template>
                      </SidebarTreeRow>

                      <SidebarTreeRow
                        v-else
                        class="prompt-tree-file"
                        kind="file"
                        :label="promptTemplateDisplayName(node.raw)"
                        :label-title="promptTemplateDisplayName(node.raw)"
                        :icon="appendPageIcon"
                        :depth="node.depth"
                        :active="activeNodeId === `prompt:${node.id}`"
                        :status="promptStatus(node.raw)"
                        :editing="editingKey === `prompt:${node.id}`"
                        :action-width="44"
                        draggable="true"
                        @dragstart="startDrag('prompt', node.raw)"
                        @dragend="clearDrag"
                        @activate="emit('open-prompt', { kind: 'prompt', prompt: node.raw })"
                      >
                        <template #editing>
                          <SvgMaskIcon :src="appendPageIcon" :size="14" />
                          <input
                            ref="editingInputs"
                            v-model="editingValue"
                            class="prompt-tree-input"
                            name="prompt-file-name"
                            autocomplete="off"
                            :aria-label="`重命名 ${promptTemplateDisplayName(node.raw)}`"
                            @keydown.enter.prevent="commitRename"
                            @keydown.esc.prevent="cancelEditing"
                            @blur="cancelEditing"
                          />
                        </template>
                        <template #actions>
                          <button class="sidebar-tree-action" type="button" aria-label="重命名" title="重命名" @click.stop="startRename('prompt', node.raw, promptTemplateDisplayName(node.raw))">
                            <SvgMaskIcon :src="highlighterIcon" :size="14" />
                          </button>
                          <button
                            class="sidebar-tree-action danger"
                            type="button"
                            :disabled="!canDeletePrompt(node.raw)"
                            :aria-label="canDeletePrompt(node.raw) ? '移入回收站' : '每项功能至少保留一个提示词'"
                            :title="canDeletePrompt(node.raw) ? '移入回收站' : '每项功能至少保留一个提示词'"
                            @click.stop="canDeletePrompt(node.raw) && emit('delete-prompt', node.raw)"
                          >
                            <SvgMaskIcon :src="trashIcon" :size="14" />
                          </button>
                        </template>
                      </SidebarTreeRow>
                    </template>
                    <p v-if="!visibleTaskNodes(task.value).length" class="prompt-tree-empty">暂无提示词</p>
                  </template>
                </div>
              </Transition>
            </template>
          </div>
        </Transition>
      </section>
    </div>

    <section class="prompt-tree-trash" :class="{ open: trashOpen }">
      <button class="prompt-tree-trash-toggle" type="button" @click="toggleTrash">
        <el-icon><Delete /></el-icon>
        <span>回收站</span>
        <small>{{ trashEntries.length || '' }}</small>
        <el-icon class="prompt-tree-disclosure"><ArrowRight /></el-icon>
      </button>
      <Transition name="prompt-tree-branch">
        <div v-if="trashOpen" class="prompt-tree-trash-list" v-loading="loadingTrash">
          <div v-for="entry in trashEntries" :key="`${entry.entry_type}:${entry.id}`" class="prompt-tree-trash-entry">
            <SvgMaskIcon :src="entry.entry_type === 'folder' ? folderIcon : appendPageIcon" :size="14" />
            <span :title="entry.name">{{ entry.name }}</span>
            <small v-if="entry.item_count > 1">{{ entry.item_count }}</small>
            <button type="button" @click="emit('restore-trash', entry)">恢复</button>
            <button class="danger" type="button" @click.stop="requestPermanentDeletion(entry)">删除</button>
          </div>
          <p v-if="!loadingTrash && !trashEntries.length" class="prompt-tree-empty">回收站为空</p>
        </div>
      </Transition>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ArrowRight, Delete, Plus } from '@element-plus/icons-vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import SidebarTreeRow from './SidebarTreeRow.vue'
import { promptTaskGroups, promptTemplateDisplayName } from '../config/promptInterface'
import { requestDestructiveConfirmation } from '../composables/useDestructiveConfirm'
const appendPageIcon = 'append.page'
const folderIcon = 'folder'
const highlighterIcon = 'highlighter'
const trashIcon = 'trash'

const props = defineProps({
  taskOptions: { type: Array, default: () => [] },
  folders: { type: Array, default: () => [] },
  templates: { type: Array, default: () => [] },
  reportPrompts: { type: Array, default: () => [] },
  systemPrompts: { type: Array, default: () => [] },
  promptContexts: { type: Array, default: () => [] },
  activeNodeId: { type: String, default: '' },
  trashEntries: { type: Array, default: () => [] },
  loadingTrash: { type: Boolean, default: false },
})

const emit = defineEmits([
  'open-prompt',
  'open-system-prompt',
  'open-prompt-context',
  'create-folder',
  'create-prompt',
  'rename-folder',
  'rename-prompt',
  'rename-report-prompt',
  'delete-folder',
  'delete-prompt',
  'move-node',
  'load-trash',
  'restore-trash',
  'permanently-delete-trash',
])

const OPEN_KEY = 'knowledgehub:prompt-tree-open:v1'

async function requestPermanentDeletion(entry) {
  const confirmed = await requestDestructiveConfirmation({
    title: '彻底删除',
    message: '彻底删除后无法恢复。',
    confirmLabel: '彻底删除',
  })
  if (confirmed) emit('permanently-delete-trash', entry)
}

function initialOpenKeys() {
  try {
    const stored = JSON.parse(localStorage.getItem(OPEN_KEY) || 'null')
    if (Array.isArray(stored)) return new Set(stored.map(String))
  } catch {
    // Fall through to the useful first-run state.
  }
  return new Set([
    ...promptTaskGroups.map((group) => `group:${group.id}`),
    ...props.taskOptions.map((task) => `task:${task.value}`),
  ])
}

const openKeys = ref(initialOpenKeys())
const editingKey = ref('')
const editingValue = ref('')
const editingTarget = ref(null)
const editingInputs = ref([])
const draftFolder = ref(null)
const draftPrompt = ref(null)
const dragNode = ref(null)
const dropKey = ref('')
const trashOpen = ref(false)

const groupedTasks = computed(() => promptTaskGroups.map((group) => {
  const tasks = group.taskTypes
    .map((taskType) => props.taskOptions.find((option) => option.value === taskType))
    .filter(Boolean)
    .map((task) => ({ ...task, count: taskCount(task.value) }))
  return {
    ...group,
    tasks,
    count: tasks.reduce((total, task) => total + task.count, 0),
  }
}))

const groupedReportPrompts = computed(() => {
  const groups = new Map()
  for (const prompt of props.reportPrompts) {
    const id = String(prompt.group_id || '')
    if (!id) continue
    if (!groups.has(id)) groups.set(id, { id, name: prompt.group_name || '未命名分组', prompts: [] })
    groups.get(id).prompts.push(prompt)
  }
  return [...groups.values()]
})

const groupedSystemPrompts = computed(() => {
  const groups = new Map()
  for (const prompt of props.systemPrompts) {
    const category = String(prompt.category || '其他系统规则')
    if (!groups.has(category)) {
      groups.set(category, { id: category, name: category, prompts: [] })
    }
    groups.get(category).prompts.push(prompt)
  }
  return [...groups.values()].map((group) => ({
    ...group,
    prompts: group.prompts.slice().sort((left, right) => String(left.name).localeCompare(String(right.name), 'zh-CN')),
  }))
})

const groupedSystemPromptCount = computed(() => props.systemPrompts.length)

function groupedReadOnlyPrompts(entries) {
  const groups = new Map()
  for (const prompt of entries) {
    const category = String(prompt.category || '其他规则')
    if (!groups.has(category)) groups.set(category, { id: category, name: category, prompts: [] })
    groups.get(category).prompts.push(prompt)
  }
  return [...groups.values()].map((group) => ({
    ...group,
    prompts: group.prompts.slice().sort((left, right) => String(left.name).localeCompare(String(right.name), 'zh-CN')),
  }))
}

const groupedPromptContexts = computed(() => groupedReadOnlyPrompts(props.promptContexts))
const groupedPromptContextCount = computed(() => props.promptContexts.length)

function taskCount(taskType) {
  if (taskType === 'wechat_reports') return props.reportPrompts.length
  return props.templates.filter((template) => template.task_type === taskType).length
}

function isOpen(key) {
  return openKeys.value.has(key)
}

function toggleOpen(key) {
  const next = new Set(openKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openKeys.value = next
  localStorage.setItem(OPEN_KEY, JSON.stringify([...next]))
}

function ensureOpen(key) {
  if (openKeys.value.has(key)) return
  toggleOpen(key)
}

function visibleTaskNodes(taskType) {
  const folders = props.folders.filter((folder) => folder.task_type === taskType)
  const templates = props.templates.filter((template) => template.task_type === taskType)
  const foldersByParent = new Map()
  const templatesByFolder = new Map()
  for (const folder of folders) {
    const parentId = folder.parent_folder_id || null
    if (!foldersByParent.has(parentId)) foldersByParent.set(parentId, [])
    foldersByParent.get(parentId).push(folder)
  }
  for (const template of templates) {
    const folderId = template.folder_id || null
    if (!templatesByFolder.has(folderId)) templatesByFolder.set(folderId, [])
    templatesByFolder.get(folderId).push(template)
  }
  const nodes = []
  const appendChildren = (parentId, depth) => {
    if (draftFolder.value?.taskType === taskType && draftFolder.value.parentFolderId === parentId) {
      nodes.push({ kind: 'draft-folder', id: 'new', depth })
    }
    if (draftPrompt.value?.taskType === taskType && draftPrompt.value.folderId === parentId) {
      nodes.push({ kind: 'draft-prompt', id: 'new', depth })
    }
    const childFolders = [...(foldersByParent.get(parentId) || [])]
      .sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || a.name.localeCompare(b.name, 'zh-CN'))
    const childTemplates = [...(templatesByFolder.get(parentId) || [])]
      .sort((a, b) => Number(a.sort_order || 0) - Number(b.sort_order || 0) || promptTemplateDisplayName(a).localeCompare(promptTemplateDisplayName(b), 'zh-CN'))
    for (const folder of childFolders) {
      nodes.push({ kind: 'folder', id: folder.id, name: folder.name, depth, raw: folder })
      if (isOpen(`folder:${folder.id}`)) appendChildren(folder.id, depth + 1)
    }
    for (const template of childTemplates) {
      nodes.push({ kind: 'prompt', id: template.id, name: promptTemplateDisplayName(template), depth, raw: template })
    }
  }
  appendChildren(null, 2)
  return nodes
}

function canDeletePrompt(prompt) {
  return props.templates.filter((template) => template.task_type === prompt.task_type).length > 1
}

function promptStatus(prompt) {
  return prompt.is_active ? '已启用' : ''
}

function requestNewPrompt(taskType, folderId) {
  ensureOpen(`task:${taskType}`)
  if (folderId) ensureOpen(`folder:${folderId}`)
  draftPrompt.value = { taskType, folderId }
  editingKey.value = 'new-prompt'
  editingValue.value = ''
  nextTick(focusEditor)
}

function startNewFolder(taskType, parentFolderId) {
  ensureOpen(`task:${taskType}`)
  if (parentFolderId) ensureOpen(`folder:${parentFolderId}`)
  draftFolder.value = { taskType, parentFolderId }
  editingKey.value = 'new-folder'
  editingValue.value = ''
  nextTick(focusEditor)
}

function commitNewFolder() {
  const name = editingValue.value.trim()
  if (!name || !draftFolder.value) return cancelEditing()
  emit('create-folder', { ...draftFolder.value, name })
  cancelEditing()
}

function commitNewPrompt() {
  const name = editingValue.value.trim()
  if (!name || !draftPrompt.value) return cancelEditing()
  emit('create-prompt', { ...draftPrompt.value, name })
  cancelEditing()
}

function startRename(kind, target, name) {
  editingKey.value = `${kind}:${target.id}`
  editingTarget.value = { kind, target }
  editingValue.value = name
  nextTick(focusEditor)
}

function commitRename() {
  const name = editingValue.value.trim()
  const target = editingTarget.value
  if (!name || !target) return cancelEditing()
  if (target.kind === 'folder') emit('rename-folder', { folder: target.target, name })
  if (target.kind === 'prompt') emit('rename-prompt', { prompt: target.target, name })
  if (target.kind === 'report') emit('rename-report-prompt', { prompt: target.target, name })
  cancelEditing()
}

function cancelEditing() {
  editingKey.value = ''
  editingValue.value = ''
  editingTarget.value = null
  draftFolder.value = null
  draftPrompt.value = null
}

function focusEditor() {
  const inputs = Array.isArray(editingInputs.value) ? editingInputs.value : [editingInputs.value]
  const input = inputs.find((element) => element?.offsetParent !== null) || inputs[0]
  input?.focus?.()
  input?.select?.()
}

function startDrag(kind, node) {
  dragNode.value = { kind, node }
}

function handleDragOver(event, taskType, folderId, key) {
  if (!dragNode.value || dragNode.value.node.task_type !== taskType) return
  if (dragNode.value.kind === 'folder' && dragNode.value.node.id === folderId) return
  event.dataTransfer.dropEffect = 'move'
  dropKey.value = key
}

function handleDrop(taskType, folderId) {
  if (!dragNode.value || dragNode.value.node.task_type !== taskType) return clearDrag()
  emit('move-node', { ...dragNode.value, folderId })
  clearDrag()
}

function clearDrag() {
  dragNode.value = null
  dropKey.value = ''
}

function toggleTrash() {
  trashOpen.value = !trashOpen.value
  if (trashOpen.value) emit('load-trash')
}
</script>

<style scoped>
.prompt-file-tree {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  height: 100%;
  min-height: 0;
  color: var(--vk-text);
  background: var(--vk-bg-quiet);
}

.prompt-tree-scroll {
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: var(--vk-space-sm) var(--vk-space-control) var(--vk-space-sm) var(--vk-space-xs);
  scrollbar-gutter: stable;
}

.prompt-tree-group + .prompt-tree-group { margin-top: var(--vk-space-xs); }

.prompt-tree-trash-toggle {
  display: flex;
  align-items: center;
  width: 100%;
  min-width: 0;
  gap: var(--vk-space-xs);
  min-height: 28px;
  padding: 0 var(--vk-space-xs);
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--vk-muted);
  font: inherit;
  font-size: var(--vk-type-label-size);
  text-align: left;
  cursor: pointer;
}

.prompt-tree-trash-toggle small {
  margin-left: auto;
  color: var(--vk-muted);
  font-size: var(--vk-type-micro-size);
  font-variant-numeric: tabular-nums;
}

.prompt-tree-disclosure {
  flex: 0 0 auto;
  font-size: 12px;
  transition: transform var(--vk-motion-fast) var(--vk-ease-out);
}

.prompt-tree-trash.open .prompt-tree-trash-toggle .prompt-tree-disclosure { transform: rotate(90deg); }

.prompt-tree-edit-spacer { width: 16px; flex: 0 0 16px; }

.prompt-tree-input {
  min-width: 0;
  flex: 1 1 auto;
  height: 22px;
  padding: 0 var(--vk-space-xs);
  border: 1px solid var(--vk-border-strong);
  border-radius: var(--vk-radius-compact);
  outline: none;
  background: var(--vk-bg-panel);
  color: var(--vk-text);
  font: inherit;
  font-size: var(--vk-type-label-size);
  box-shadow: var(--vk-focus-ring);
}

.prompt-tree-branch-enter-active,
.prompt-tree-branch-leave-active {
  transition: opacity var(--vk-motion-standard) var(--vk-ease-out), transform var(--vk-motion-standard) var(--vk-ease-out);
  transform-origin: top;
}
.prompt-tree-branch-leave-active { transition-duration: var(--vk-motion-fast); }
.prompt-tree-branch-enter-from,
.prompt-tree-branch-leave-to { opacity: 0; transform: translateY(-4px); }

.prompt-tree-empty {
  margin: var(--vk-space-xs) var(--vk-space-control) var(--vk-space-sm) 42px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.prompt-tree-trash {
  border-top: 1px solid var(--vk-border);
  padding: var(--vk-space-xs);
}

.prompt-tree-trash-toggle:hover { background: var(--vk-bg-hover); color: var(--vk-text); }

.prompt-tree-trash-list {
  max-height: 180px;
  overflow: auto;
  padding: var(--vk-space-xs);
  overscroll-behavior: contain;
}

.prompt-tree-trash-entry {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: var(--vk-space-xs);
  min-height: 27px;
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
}

.prompt-tree-trash-entry > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-tree-trash-entry > small { font-variant-numeric: tabular-nums; }
.prompt-tree-trash-entry button { padding: 2px 3px; border: 0; background: transparent; color: var(--vk-accent-strong); font: inherit; cursor: pointer; }
.prompt-tree-trash-entry button.danger { color: var(--vk-danger); }

@media (prefers-reduced-motion: reduce) {
  .prompt-tree-disclosure,
  .prompt-tree-branch-enter-active,
  .prompt-tree-branch-leave-active { transition-duration: 0.01ms !important; transform: none !important; }
}
</style>
