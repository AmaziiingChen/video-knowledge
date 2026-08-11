<template>
  <SvgMaskIcon class="process-log-toggle-icon" :src="collapsed ? 'status.bottom.expand' : 'status.bottom.collapse'" :size="18" />
</template>

<script setup>
import SvgMaskIcon from './SvgMaskIcon.vue'

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})
</script>

<style scoped>
.process-log-toggle-icon {
  color: currentColor;
}
</style>
