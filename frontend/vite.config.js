import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendOrigin = 'http://127.0.0.1:8000'
const backendInstanceToken = String(process.env.KNOWLEDGEHUB_INSTANCE_TOKEN || '').trim()

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
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: backendOrigin,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (request) => {
            if (backendInstanceToken) request.setHeader('X-KnowledgeHub-Token', backendInstanceToken)
          })
        },
      },
    },
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
