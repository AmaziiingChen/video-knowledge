import { createApp } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDatePicker,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElPagination,
  ElPopover,
  ElPopconfirm,
  ElProgress,
  ElSegmented,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  messageConfig
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import AppTooltip from './components/AppTooltip.vue'

const root = document.querySelector('#app')
let appMounted = false

function reportRuntimeFailure(error, source = 'runtime') {
  console.error(`[KnowledgeHub ${source} 错误]`, error)
}

function renderStartupFailure(error) {
  const detail = error instanceof Error ? error.message : String(error || '未知错误')
  console.error('[KnowledgeHub 启动失败]', error)
  if (!root) return
  root.replaceChildren()
  const panel = document.createElement('main')
  panel.className = 'knowledgehub-startup-failure'
  const title = document.createElement('h1')
  title.textContent = 'KnowledgeHub 未能启动'
  const message = document.createElement('p')
  message.textContent = '前端加载发生错误。请重新载入；若仍失败，可将错误日志提供给开发者。'
  const detailNode = document.createElement('code')
  detailNode.textContent = detail || '未提供错误详情'
  const reload = document.createElement('button')
  reload.type = 'button'
  reload.textContent = '重新载入'
  reload.addEventListener('click', () => window.location.reload())
  panel.append(title, message, detailNode, reload)
  root.append(panel)
}

window.addEventListener('error', (event) => {
  if (!event.error) return
  if (appMounted) {
    reportRuntimeFailure(event.error)
    return
  }
  renderStartupFailure(event.error)
})
window.addEventListener('unhandledrejection', (event) => {
  // A late API timeout is recoverable: the workbench owns retries and a
  // visible reconnect state. Replacing a mounted application with a blank
  // startup error page makes that recovery impossible.
  if (appMounted) {
    reportRuntimeFailure(event.reason, '异步')
    return
  }
  renderStartupFailure(event.reason)
})

const elementComponents = [
  ElAlert,
  ElButton,
  ElDatePicker,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElPopover,
  ElPopconfirm,
  ElProgress,
  ElSegmented,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag
]

try {
  const rawAppearance = localStorage.getItem('video-knowledge.appearance-settings.v1')
  const savedTheme = rawAppearance ? JSON.parse(rawAppearance).theme : ''
  document.documentElement.dataset.theme = savedTheme || 'paper'
} catch {
  document.documentElement.dataset.theme = 'paper'
}

try {
  const app = createApp(App)
  app.config.errorHandler = (error) => {
    if (appMounted) {
      reportRuntimeFailure(error, 'Vue')
      return
    }
    renderStartupFailure(error)
  }
  elementComponents.forEach((component) => app.use(component))
  app.component('ElTooltip', AppTooltip)
  app.use(ElLoading)

Object.assign(messageConfig, {
  duration: 2200,
  grouping: true,
  offset: 14,
  max: 3
})

  app.mount('#app')
  appMounted = true
} catch (error) {
  renderStartupFailure(error)
}
