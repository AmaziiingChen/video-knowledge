<template>
  <div class="workspace-chrome-actions" aria-label="全局工具与面板控制">
    <div class="workspace-chrome-tool-group">
      <el-tooltip :content="openclawStatusText" placement="bottom">
        <button
          class="topbar-icon-button layout-toggle-button"
          type="button"
          :class="{ 'is-on': openclawRunning, 'is-off': !openclawRunning, loading: openclawScanning }"
          aria-label="启动或查看 OpenClaw Gateway"
          :disabled="startupBlocking || openclawScanning"
          @click="emit('start-openclaw')"
        >
          <SvgMaskIcon :src="openclawIcon" :size="18" />
        </button>
      </el-tooltip>

      <el-tooltip :content="clipboardWatching ? '关闭剪贴板监听' : '开启剪贴板监听'" placement="bottom">
        <button
          class="topbar-icon-button layout-toggle-button"
          type="button"
          :class="{ 'is-on': clipboardWatching, 'is-off': !clipboardWatching, loading: clipboardScanning }"
          aria-label="本机剪贴板监听"
          :aria-pressed="clipboardWatching"
          :disabled="startupBlocking || clipboardScanning"
          @click="emit('toggle-clipboard', !clipboardWatching)"
        >
          <SvgMaskIcon :src="clipboardIcon" :size="18" />
        </button>
      </el-tooltip>

    </div>

    <div class="workspace-chrome-panel-group" aria-label="面板切换">
      <el-tooltip :content="processLogOpen ? '隐藏处理日志' : '显示处理日志'" placement="bottom">
        <button
          class="topbar-icon-button layout-toggle-button"
          type="button"
          :class="{ 'is-on': processLogOpen, 'is-off': !processLogOpen }"
          aria-label="展开或折叠处理日志"
          :aria-pressed="processLogOpen"
          @click="emit('toggle-process-log')"
        >
          <ProcessLogToggleIcon :collapsed="!processLogOpen" />
        </button>
      </el-tooltip>

      <el-tooltip
        v-if="showContextToggle"
        :content="contextSidebarOpen ? contextOpenLabel : contextClosedLabel"
        placement="bottom"
      >
        <button
          class="topbar-icon-button layout-toggle-button"
          type="button"
          :class="{ 'is-on': contextSidebarOpen, 'is-off': !contextSidebarOpen }"
          aria-label="展开或折叠右侧栏"
          :aria-pressed="contextSidebarOpen"
          @click="emit('toggle-context')"
        >
          <PanelToggleIcon side="right" :collapsed="!contextSidebarOpen" />
        </button>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
import PanelToggleIcon from '../components/PanelToggleIcon.vue'
import ProcessLogToggleIcon from '../components/ProcessLogToggleIcon.vue'
const openclawIcon = 'openclaw'
const clipboardIcon = 'document.on.clipboard'

const props = defineProps({
  openclawStatusText: { type: String, default: '' },
  openclawRunning: { type: Boolean, default: false },
  openclawScanning: { type: Boolean, default: false },
  startupBlocking: { type: Boolean, default: false },
  clipboardWatching: { type: Boolean, default: false },
  clipboardScanning: { type: Boolean, default: false },
  activeView: { type: String, default: '' },
  contextSidebarOpen: { type: Boolean, default: false },
  processLogOpen: { type: Boolean, default: false },
})

const emit = defineEmits([
  'start-openclaw',
  'toggle-clipboard',
  'toggle-context',
  'toggle-process-log',
])

const showContextToggle = computed(() => ['library', 'knowledge'].includes(props.activeView))
const contextOpenLabel = computed(() => props.activeView === 'knowledge' ? '隐藏引用原文' : '隐藏 AI 助手')
const contextClosedLabel = computed(() => props.activeView === 'knowledge' ? '显示引用原文' : '显示 AI 助手')
</script>

<style scoped>
.workspace-chrome-actions {
  width: 100%;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--vk-space-xs);
  padding: 0 var(--vk-space-control);
  overflow: hidden;
}

.workspace-chrome-tool-group,
.workspace-chrome-panel-group {
  display: inline-flex;
  align-items: center;
  gap: var(--vk-space-xs);
}

.workspace-chrome-tool-group {
  flex: 0 0 auto;
  min-width: 0;
  overflow: visible;
}

.workspace-chrome-panel-group {
  flex: 0 0 auto;
  margin-left: 0;
}

.topbar-icon-button {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 0;
  outline: 0;
  border-radius: var(--vk-radius-control);
  color: color-mix(in srgb, var(--vk-text) 72%, transparent);
  background: transparent;
  cursor: pointer;
}

.layout-toggle-button {
  box-shadow: none;
  transition:
    color var(--vk-motion-fast) ease,
    opacity var(--vk-motion-fast) ease,
    transform var(--vk-motion-fast) var(--vk-ease-out);
}

.topbar-icon-button.is-on {
  color: var(--vk-accent-strong);
}

.topbar-icon-button.is-off {
  color: color-mix(in srgb, var(--vk-text) 70%, transparent);
}

.topbar-icon-button.loading {
  opacity: 0.56;
  cursor: wait;
}

.layout-toggle-button:hover,
.layout-toggle-button:focus-visible {
  color: var(--vk-text);
}

.layout-toggle-button:focus-visible {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--vk-text) 16%, transparent);
}

.layout-toggle-button:active:not(:disabled) {
  transform: scale(0.97);
}

.layout-toggle-button:disabled {
  cursor: default;
}

</style>
