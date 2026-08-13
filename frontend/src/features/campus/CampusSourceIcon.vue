<template>
  <span
    class="campus-source-icon"
    :data-source-icon="sourceSlug"
    :style="iconStyle"
    aria-hidden="true"
  >
    <SvgMaskIcon :src="presentation.icon" :size="glyphSize" />
  </span>
</template>

<script setup>
import { computed } from 'vue'
import SvgMaskIcon from '../../components/SvgMaskIcon.vue'

const props = defineProps({
  sourceSlug: { type: String, default: '' },
  size: { type: Number, default: 30 },
})

const sourcePresentations = Object.freeze({
  gwt: { icon: '01-公文通', color: '#3478D4' },
  sztu: { icon: 'shield.fill', color: '#16815D' },
  sgim: { icon: '02-中德智能制造学院', color: '#B66A18' },
  ai: { icon: '03-人工智能学院', color: '#6258C7' },
  nmne: { icon: '04-新材料与新能源学院', color: '#A66B00' },
  utl: { icon: '05-城市交通与物流学院', color: '#087E8B' },
  hsee: { icon: '06-健康与环境工程学院', color: '#3A7D44' },
  cep: { icon: '07-工程物理学院', color: '#3B63A3' },
  cop: { icon: '08-药学院', color: '#B23A58' },
  icoc: { icon: '09-集成电路与光电芯片学院', color: '#6E4BC3' },
  'future-tech': { icon: '10-未来技术学院', color: '#7B4FB3' },
  design: { icon: '11-创意设计学院', color: '#A13C78' },
  business: { icon: '12-商学院', color: '#365274' },
  sfl: { icon: '13-外国语学院', color: '#A6532F' },
  music: { icon: '14-音乐学院', color: '#B33A3A' },
  'sztu-procurement': { icon: 'chineseyuanrenminbisign.bank.building.fill', color: '#1C3387' },
})

const normalizedSlug = computed(() => String(props.sourceSlug || '').trim().toLowerCase())
const presentation = computed(() => sourcePresentations[normalizedSlug.value] || sourcePresentations.gwt)
const glyphSize = computed(() => Math.max(14, Math.round(props.size * 0.6)))
const iconStyle = computed(() => ({
  '--source-icon-color': presentation.value.color,
  '--source-icon-size': `${props.size}px`,
}))
</script>

<style scoped>
.campus-source-icon {
  width: var(--source-icon-size);
  height: var(--source-icon-size);
  display: grid;
  place-items: center;
  flex: 0 0 var(--source-icon-size);
  border: 1px solid color-mix(in srgb, var(--source-icon-color) 20%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--source-icon-color) 14%, var(--vk-bg-panel));
  color: var(--source-icon-color);
  box-shadow: inset 0 1px 0 color-mix(in srgb, white 32%, transparent);
}
</style>
