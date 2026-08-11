<template>
  <SvgMaskIcon class="panel-toggle-icon" :src="icon" :size="18" />
</template>

<script setup>
import { computed } from 'vue'
import SvgMaskIcon from './SvgMaskIcon.vue'

const props = defineProps({
  side: {
    type: String,
    required: true,
    validator: (value) => value === 'left' || value === 'right'
  },
  collapsed: {
    type: Boolean,
    default: false
  }
})

const icon = computed(() => {
  const state = props.collapsed ? 'expand' : 'collapse'
  return `sidebar.${props.side}.${state}`
})
</script>

<style scoped>
.panel-toggle-icon {
  color: currentColor;
}
</style>
