import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [vue({
    template: {
      compilerOptions: {
        isCustomElement: (tag) => tag === 'webview',
      },
    },
  })],
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
  build: {
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return undefined
          if (id.includes('/node_modules/element-plus/')) {
            return 'element-plus'
          }
          if (id.includes('/node_modules/@element-plus/icons-vue/')) {
            return 'element-icons'
          }
          if (id.includes('/node_modules/marked/') || id.includes('/node_modules/katex/')) {
            return 'markdown'
          }
          if (id.includes('/node_modules/artplayer/')) {
            return 'player'
          }
          return undefined
        },
      },
    },
  },
})
