<template>
  <section
    class="collection-state"
    :class="`is-${mode}`"
    :aria-busy="mode === 'loading'"
    :aria-live="mode === 'loading' ? 'polite' : undefined"
  >
    <template v-if="mode === 'loading'">
      <div class="collection-state-skeleton" aria-hidden="true">
        <span v-for="index in rows" :key="index" class="collection-state-skeleton-row">
          <i></i><b></b><em></em><small></small>
        </span>
      </div>
      <p class="sr-only">{{ loadingLabel }}</p>
    </template>
    <template v-else>
      <strong>{{ title }}</strong>
      <p v-if="description">{{ description }}</p>
      <slot name="action"></slot>
    </template>
  </section>
</template>

<script setup>
defineProps({
  mode: { type: String, default: 'empty' },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  loadingLabel: { type: String, default: '正在读取列表' },
  rows: { type: Number, default: 5 },
})
</script>

<style scoped>
.collection-state {
  display: grid;
  min-height: 236px;
  align-content: center;
  justify-items: center;
  gap: var(--vk-space-sm);
  padding: var(--vk-space-section) var(--vk-space-panel);
  color: var(--vk-muted);
  text-align: center;
}

.collection-state > strong {
  color: var(--vk-text);
  font-size: var(--vk-type-reading-size);
  font-weight: var(--vk-weight-strong);
}

.collection-state > p { max-width: 390px; margin: 0; font-size: var(--vk-type-label-size); line-height: var(--vk-leading-body); }
.collection-state .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

.collection-state-skeleton { display: grid; width: min(100%, 920px); gap: 1px; }
.collection-state-skeleton-row {
  min-height: 54px;
  display: grid;
  grid-template-columns: 34px minmax(140px, 1.2fr) minmax(120px, .8fr) 104px;
  align-items: center;
  gap: var(--vk-space-cluster);
  padding-inline: var(--vk-space-panel);
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 58%, transparent);
}
.collection-state-skeleton-row > * { display: block; border-radius: var(--vk-radius-control); background: color-mix(in srgb, var(--vk-bg-hover) 68%, var(--vk-bg-panel)); }
.collection-state-skeleton-row i { width: 28px; height: 28px; border-radius: var(--vk-radius-input); }
.collection-state-skeleton-row b { width: min(100%, 188px); height: 12px; }
.collection-state-skeleton-row em { width: min(100%, 132px); height: 10px; justify-self: center; }
.collection-state-skeleton-row small { width: 46px; height: 24px; justify-self: center; border-radius: var(--vk-radius-pill); }

@media (prefers-reduced-motion: reduce) {
  .collection-state-skeleton-row > * { transition: none; }
}
</style>
