<template>
  <el-dialog
    v-model="visible"
    class="source-group-editor-dialog"
    width="min(680px, calc(100vw - 40px))"
    align-center
    append-to-body
    @closed="emit('closed')"
  >
    <template #header>
      <header class="source-group-editor-heading">
        <h2>编辑来源</h2>
        <p><strong>{{ group?.name || '未命名分组' }}</strong><span aria-hidden="true">·</span>{{ sourceSummary }}</p>
      </header>
    </template>

    <section class="source-group-editor-body" aria-label="分组来源">
      <p class="source-group-editor-caption">移出分组仅解除关联；来源订阅和已收集内容仍保留在资料库。</p>

      <div v-if="sources.length" class="source-group-editor-table" role="table" aria-label="来源列表">
        <div class="source-group-editor-table-head" role="row">
          <span role="columnheader">来源</span>
          <span role="columnheader">类型</span>
          <span class="source-group-editor-table-action-head" role="columnheader">操作</span>
        </div>
        <div v-for="source in sources" :key="sourceKey(source)" class="source-group-editor-row" role="row">
          <strong :title="source.label || '未命名来源'" role="cell">{{ source.label || '未命名来源' }}</strong>
          <span class="source-group-editor-kind" role="cell">{{ sourceKindLabel(source.kind) }}</span>
          <div class="source-group-editor-action" role="cell">
            <el-button
              class="source-group-editor-remove"
              size="small"
              text
              type="danger"
              :loading="removingSourceKey === sourceKey(source)"
              :disabled="Boolean(removingSourceKey)"
              @click="emit('remove-source', source)"
            >移出分组</el-button>
          </div>
        </div>
      </div>
      <div v-else class="source-group-editor-empty">
        <strong>尚未添加来源</strong>
        <p>可从公众号、网页或 RSS 管理中把来源加入“{{ group?.name || '此分组' }}”。</p>
      </div>
    </section>

    <template #footer>
      <div class="source-group-editor-footer">
        <span>{{ sources.length ? '更改会立即生效。' : '添加来源后会显示在这里。' }}</span>
        <el-button @click="visible = false">完成</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  group: { type: Object, default: null },
  removingSourceKey: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'remove-source', 'closed'])

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const sources = computed(() => Array.isArray(props.group?.sources) ? props.group.sources : [])
const sourceSummary = computed(() => `${sources.value.length} 个来源`)

function sourceKey(source) {
  return `${source?.kind || 'source'}:${source?.source_id || source?.id || ''}`
}

function sourceKindLabel(kind) {
  return { wechat: '公众号', campus: '校园网页', rss: 'RSS 订阅' }[kind] || '内容来源'
}
</script>

<style scoped>
:global(.source-group-editor-dialog) {
  border: 1px solid color-mix(in srgb, var(--vk-border) 82%, transparent);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-panel);
  box-shadow: 0 10px 26px color-mix(in srgb, var(--vk-text) 12%, transparent);
  overflow: hidden;
}

:global(.source-group-editor-dialog .el-dialog__header) {
  margin: 0;
  padding: var(--vk-space-panel) var(--vk-space-section) 0;
}

:global(.source-group-editor-dialog .el-dialog__body) {
  padding: var(--vk-space-cluster) var(--vk-space-section) 0;
}

:global(.source-group-editor-dialog .el-dialog__footer) {
  padding: var(--vk-space-panel) var(--vk-space-section);
}

.source-group-editor-heading h2 {
  color: var(--vk-text);
  font-size: var(--vk-type-heading-size);
  font-weight: var(--vk-weight-display);
  letter-spacing: var(--vk-tracking-display);
  line-height: var(--vk-leading-display);
  margin: 0;
}

.source-group-editor-heading p {
  color: var(--vk-muted);
  display: flex;
  flex-wrap: wrap;
  gap: var(--vk-space-xs);
  margin: var(--vk-space-xs) 0 0;
  font-size: var(--vk-type-body-size);
  line-height: var(--vk-leading-body);
}

.source-group-editor-heading strong { color: var(--vk-text); font-weight: var(--vk-weight-medium); }

.source-group-editor-body { min-width: 0; }

.source-group-editor-caption {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  line-height: var(--vk-leading-body);
  margin: 0 0 var(--vk-space-control);
}

.source-group-editor-table {
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-radius: var(--vk-radius-surface);
  overflow: hidden;
}

.source-group-editor-table-head,
.source-group-editor-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, .32fr) minmax(0, .32fr);
  gap: var(--vk-space-cluster);
  justify-items: center;
  text-align: center;
}

.source-group-editor-table-head {
  align-items: center;
  min-height: var(--vk-control-height-comfortable);
  padding: 0 var(--vk-space-cluster);
  background: var(--vk-bg-quiet);
  border-bottom: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  font-weight: var(--vk-weight-medium);
}

.source-group-editor-table-action-head { text-align: center; }

.source-group-editor-row {
  align-items: center;
  min-height: 64px;
  padding: 0 var(--vk-space-cluster);
  transition: background var(--vk-motion-fast) var(--vk-ease-out);
}

.source-group-editor-row + .source-group-editor-row { border-top: 1px solid color-mix(in srgb, var(--vk-border) 66%, transparent); }

.source-group-editor-row:hover { background: var(--vk-bg-hover); }

.source-group-editor-row strong {
  color: var(--vk-text);
  font-size: var(--vk-type-body-size);
  font-weight: var(--vk-weight-medium);
  justify-self: stretch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-group-editor-kind {
  color: var(--vk-muted);
  font-size: var(--vk-type-meta-size);
  justify-self: stretch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-group-editor-action { display: flex; justify-content: center; }

.source-group-editor-remove { color: var(--vk-danger); min-height: var(--vk-control-height-compact); }

.source-group-editor-empty {
  padding: var(--vk-space-section) var(--vk-space-panel);
  border: 1px solid color-mix(in srgb, var(--vk-border) 72%, transparent);
  border-radius: var(--vk-radius-surface);
  color: var(--vk-muted);
  text-align: center;
}

.source-group-editor-empty strong { color: var(--vk-text); display: block; font-size: var(--vk-type-body-size); font-weight: var(--vk-weight-medium); }
.source-group-editor-empty p { font-size: var(--vk-type-meta-size); line-height: var(--vk-leading-body); margin: var(--vk-space-xs) 0 0; }

.source-group-editor-footer {
  align-items: center;
  color: var(--vk-muted);
  display: flex;
  font-size: var(--vk-type-meta-size);
  justify-content: space-between;
}

.source-group-editor-footer :deep(.el-button) {
  min-height: var(--vk-control-height-default);
  border-radius: var(--vk-radius-control);
}

@media (max-width: 520px) {
  .source-group-editor-table-head { display: none; }
  .source-group-editor-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--vk-space-sm) var(--vk-space-cluster);
    padding: var(--vk-space-control) var(--vk-space-cluster);
  }
  .source-group-editor-kind { grid-column: 1; }
  .source-group-editor-action { grid-column: 2; grid-row: 1 / span 2; }
}

@media (prefers-reduced-motion: reduce) {
  .source-group-editor-row { transition: none; }
}
</style>
