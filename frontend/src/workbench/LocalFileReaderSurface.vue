<template>
  <article v-if="mode === 'pdf'" class="pdf-reader" aria-label="PDF 原件预览">
    <iframe
      v-if="originalUrl"
      class="pdf-preview-frame"
      :src="originalUrl"
      :title="`${content?.title || '导入 PDF'}原件`"
    ></iframe>
    <div v-else class="local-file-loading">正在打开 PDF 原件…</div>
  </article>
  <article v-else class="image-reader" aria-label="原图预览">
    <figure class="image-reader-figure">
      <img
        v-if="originalUrl"
        :src="originalUrl"
        :alt="content?.title || '导入图片'"
      />
    </figure>
  </article>
</template>

<script setup>
defineProps({
  mode: {
    type: String,
    required: true,
    validator: (value) => ['image', 'pdf'].includes(value),
  },
  content: { type: Object, default: null },
  originalUrl: { type: String, default: '' },
})
</script>

<style scoped>
.image-reader {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  background: var(--vk-bg-center);
}

.image-reader-figure {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.image-reader-figure img {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  max-width: none;
  height: auto;
  max-height: none;
  object-fit: contain;
  background: transparent;
}

.pdf-reader {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: var(--vk-bg-center);
}

.pdf-preview-frame {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  background: var(--vk-bg-center);
}

.local-file-loading {
  max-width: 780px;
  white-space: pre-wrap;
  color: color-mix(in srgb, var(--vk-text) 90%, var(--vk-muted));
  font-size: var(--vk-type-reading-size);
  line-height: 1.75;
}
</style>
