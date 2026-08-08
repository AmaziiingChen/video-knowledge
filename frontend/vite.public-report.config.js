import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// This is deliberately a second, small build target. The desktop app remains
// untouched, while the generated directory can be uploaded to static hosting.
export default defineConfig({
  root: 'public-report',
  base: './',
  plugins: [vue()],
  build: {
    outDir: '../dist-public-report',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        report: 'index.html',
        archive: 'archive.html',
      },
    },
  },
})
