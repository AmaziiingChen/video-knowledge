import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.component.spec.js'],
    coverage: {
      provider: 'v8',
      include: [
        'src/workbench/LibraryContextMenu.vue',
        'src/workbench/ReportCoverPreview.vue',
        'src/workbench/reportCoverPresentation.js',
      ],
      reporter: ['text', 'json-summary'],
      thresholds: {
        branches: 75,
        functions: 85,
        lines: 85,
        statements: 85,
      },
    },
  },
})
