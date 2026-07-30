import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'

const testReportPath = '/Users/chen/AmazingWork/Obsidian/Learning/library/区间汇总/校园生活/测试10--dd0d2a801868.md'
const publishedReportsPath = new URL('./public-report/public/published-reports.json', import.meta.url)

function testReportFixture() {
  return {
    name: 'knowledgehub-test-report-fixture',
    resolveId(id) {
      return id === 'virtual:knowledgehub-test-report' ? '\0virtual:knowledgehub-test-report' : null
    },
    load(id) {
      if (id !== '\0virtual:knowledgehub-test-report') return null
      // The public-page prototype uses a real local report to exercise a long
      // reading flow. Redact the only credential-like example before it ever
      // reaches the browser bundle.
      const markdown = readFileSync(testReportPath, 'utf8')
        .replace(/(密码为`)[^`]+(`)/g, '$1[已省略]$2')
      return `export default ${JSON.stringify(markdown)}`
    },
  }
}

function publishedReportsFixture() {
  return {
    name: 'knowledgehub-published-reports-fixture',
    resolveId(id) {
      return id === 'virtual:knowledgehub-published-reports' ? '\0virtual:knowledgehub-published-reports' : null
    },
    load(id) {
      if (id !== '\0virtual:knowledgehub-published-reports') return null
      const manifest = JSON.parse(readFileSync(publishedReportsPath, 'utf8'))
      const reports = Array.isArray(manifest.reports) ? manifest.reports : []
      return `export default ${JSON.stringify({ reports })}`
    },
  }
}

// This is deliberately a second, small build target. The desktop app remains
// untouched, while the generated directory can be uploaded to static hosting.
export default defineConfig({
  root: 'public-report',
  base: './',
  plugins: [vue(), testReportFixture(), publishedReportsFixture()],
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
