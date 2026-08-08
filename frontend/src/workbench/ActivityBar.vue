<template>
  <nav class="workspace-ribbon" aria-label="主功能">
    <el-tooltip
      v-for="item in items"
      :key="item.view"
      :content="item.label"
      placement="right"
    >
      <button
        class="ribbon-button"
        :class="{ active: activeView === item.view }"
        type="button"
        :aria-label="item.label"
        :aria-current="activeView === item.view ? 'page' : undefined"
        @click="$emit('update:activeView', item.view)"
      >
        <SvgMaskIcon :src="iconFor(item, activeView === item.view)" :size="18" />
      </button>
    </el-tooltip>
    <el-tooltip
      content="设置"
      placement="right"
    >
      <button class="ribbon-button settings-button" type="button" aria-label="设置" @click="$emit('open-settings')">
        <SvgMaskIcon :src="settingsIcon" :size="18" />
      </button>
    </el-tooltip>
  </nav>
</template>

<script setup>
import SvgMaskIcon from '../components/SvgMaskIcon.vue'
const archiveIcon = 'archivebox'
const archiveFillIcon = 'archivebox.fill'
const folderIcon = 'folder'
const folderFillIcon = 'folder.fill'
const promptIcon = 'text.quote'
const wechatIcon = 'seal'
const wechatFillIcon = 'seal.fill'
const campusIcon = 'h.square'
const campusFillIcon = 'h.square.fill'
const reportIcon = 'text.page'
const reportFillIcon = 'text.page.fill'
const knowledgeIcon = 'sparkles.tv'
const knowledgeFillIcon = 'sparkles.tv.fill'
const creatorIcon = 'tray.badge'
const creatorFillIcon = 'tray.badge.fill'
const rssIcon = 'r.square'
const rssFillIcon = 'r.square.fill'
const settingsIcon = 'gearshape'

defineProps({
  activeView: {
    type: String,
    required: true
  },
  items: {
    type: Array,
    required: true
  }
})

defineEmits(['update:activeView', 'open-settings'])

const iconMap = {
  archive: {
    default: archiveIcon,
    active: archiveFillIcon
  },
  folder: {
    default: folderIcon,
    active: folderFillIcon
  },
  prompt: {
    default: promptIcon,
    active: promptIcon
  },
  wechat: {
    default: wechatIcon,
    active: wechatFillIcon
  },
  campus: {
    default: campusIcon,
    active: campusFillIcon
  },
  report: {
    default: reportIcon,
    active: reportFillIcon
  },
  knowledge: {
    default: knowledgeIcon,
    active: knowledgeFillIcon
  },
  creator: {
    default: creatorIcon,
    active: creatorFillIcon
  },
  rss: {
    default: rssIcon,
    active: rssFillIcon
  }
}

function iconFor(item, active) {
  const icon = iconMap[item.icon] || iconMap.folder
  return active ? icon.active : icon.default
}
</script>

<style scoped>
.workspace-ribbon {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 0;
  background: var(--vk-bg-quiet);
  border-right: 1px solid var(--vk-border);
}

.ribbon-button {
  position: relative;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 10px;
  color: var(--vk-muted);
  background: transparent;
  cursor: pointer;
  transition: none;
}

.ribbon-button :deep(.svg-mask-icon) {
  transition: none;
}

.ribbon-button:hover {
  color: var(--vk-text);
  background: transparent;
}

.ribbon-button:focus-visible :deep(.svg-mask-icon) {
  opacity: 0.88;
}

.ribbon-button:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--vk-accent-strong) 42%, transparent);
}

@media (hover: hover) and (pointer: fine) {
  .ribbon-button:hover :deep(.svg-mask-icon) {
    opacity: 0.88;
  }
}

.ribbon-button.active {
  color: var(--vk-accent-strong);
  background: transparent;
}

.ribbon-button.active::before {
  content: "";
  position: absolute;
  left: 2px;
  width: 2px;
  height: 18px;
  border-radius: var(--vk-radius-pill);
  background: var(--vk-accent-strong);
}

.ribbon-button.active :deep(.svg-mask-icon) {
  opacity: 0.92;
}

.settings-button {
  margin-top: auto;
}

@media (max-width: 620px) {
  .workspace-ribbon {
    position: sticky;
    top: 0;
    z-index: 8;
    flex-direction: row;
    justify-content: flex-start;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid var(--vk-border);
  }

  .ribbon-button {
    flex: 0 0 auto;
  }

  .settings-button {
    margin-top: 0;
    margin-left: auto;
  }
}
</style>
