<template>
  <component
    :is="iconComponent"
    class="svg-mask-icon"
    :size="size"
    :stroke-width="1.7"
    aria-hidden="true"
  />
</template>

<script setup>
import { computed } from 'vue'
import {
  IconArchive,
  IconArchiveFilled,
  IconArrowRight,
  IconBrandWechat,
  IconBuilding,
  IconBuildingBank,
  IconCircleArrowUpFilled,
  IconCircleCheck,
  IconCircleX,
  IconClipboard,
  IconDots,
  IconDotsCircleHorizontal,
  IconDownload,
  IconEraser,
  IconEye,
  IconEyeOff,
  IconFileExport,
  IconFilePlus,
  IconFileText,
  IconFolder,
  IconFolderFilled,
  IconFolderPlus,
  IconHighlight,
  IconInbox,
  IconKey,
  IconLink,
  IconMessagePlus,
  IconMessageQuestion,
  IconMovie,
  IconPalette,
  IconPin,
  IconPlayerPauseFilled,
  IconPlayerPlayFilled,
  IconQuote,
  IconRefresh,
  IconRobot,
  IconRosette,
  IconRss,
  IconSchool,
  IconSearch,
  IconSend,
  IconSettings,
  IconShieldFilled,
  IconSparkles,
  IconTrash,
  IconVideo,
  IconWaveSine,
  IconWorld,
} from '@tabler/icons-vue'

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  size: {
    type: Number,
    default: 18
  }
})

const ICONS = Object.freeze({
  '01-公文通': IconSchool,
  '02-中德智能制造学院': IconSchool,
  '03-人工智能学院': IconSchool,
  '04-新材料与新能源学院': IconSchool,
  '05-城市交通与物流学院': IconSchool,
  '06-健康与环境工程学院': IconSchool,
  '07-工程物理学院': IconSchool,
  '08-药学院': IconSchool,
  '09-集成电路与光电芯片学院': IconSchool,
  '10-未来技术学院': IconSchool,
  '11-创意设计学院': IconSchool,
  '12-商学院': IconSchool,
  '13-外国语学院': IconSchool,
  '14-音乐学院': IconSchool,
  'append.page': IconFilePlus,
  'apple.intelligence': IconSparkles,
  archivebox: IconArchive,
  'archivebox.fill': IconArchiveFilled,
  'arrow.clockwise': IconRefresh,
  'arrow.down.document': IconFileExport,
  'arrow.right': IconArrowRight,
  'arrow.up.circle.fill': IconCircleArrowUpFilled,
  'arrow.up.to.line': IconPin,
  'bubble.and.pencil': IconMessagePlus,
  'checkmark.circle': IconCircleCheck,
  'chineseyuanrenminbisign.bank.building.fill': IconBuildingBank,
  'custom.paperplane.fill': IconSend,
  'document.on.clipboard': IconClipboard,
  'dot.scope': IconRosette,
  ellipsis: IconDots,
  'ellipsis.bubble': IconDotsCircleHorizontal,
  eraser: IconEraser,
  eye: IconEye,
  'eye.slash': IconEyeOff,
  film: IconVideo,
  finder: IconSearch,
  folder: IconFolder,
  'folder.badge.plus': IconFolderPlus,
  'folder.fill': IconFolderFilled,
  gearshape: IconSettings,
  globe: IconWorld,
  'h.square': IconBuilding,
  'h.square.fill': IconBuilding,
  highlighter: IconHighlight,
  key: IconKey,
  'key.circle': IconKey,
  link: IconLink,
  magnifyingglass: IconSearch,
  movieclapper: IconMovie,
  openclaw: IconRobot,
  paintpalette: IconPalette,
  'pause.fill': IconPlayerPauseFilled,
  'play.fill': IconPlayerPlayFilled,
  'questionmark.bubble.fill': IconMessageQuestion,
  'questionmark.text.page': IconFileText,
  'r.square': IconRss,
  'r.square.fill': IconRss,
  rsshub: IconRss,
  seal: IconRosette,
  'seal.fill': IconRosette,
  'shield.fill': IconShieldFilled,
  'sparkles.tv': IconSparkles,
  'sparkles.tv.fill': IconSparkles,
  'square.and.arrow.down': IconDownload,
  'text.document': IconFileText,
  'text.page': IconFileText,
  'text.page.fill': IconFileText,
  'text.quote': IconQuote,
  trash: IconTrash,
  'tray.badge': IconInbox,
  'tray.badge.fill': IconInbox,
  waveform: IconWaveSine,
  wechat: IconBrandWechat,
  'x.circle': IconCircleX,
})

const iconComponent = computed(() => ICONS[props.src] || IconFileText)
</script>

<style scoped>
.svg-mask-icon {
  display: block;
  flex: 0 0 auto;
  opacity: 0.78;
  transition:
    opacity 0.16s ease,
    transform 0.12s ease;
}

@media (prefers-reduced-motion: reduce) {
  .svg-mask-icon {
    transition: opacity var(--vk-motion-fast) ease;
  }
}
</style>
