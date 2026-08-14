import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(new URL('./SettingsDialog.vue', import.meta.url), 'utf8')
const appSource = await readFile(new URL('../App.vue', import.meta.url), 'utf8')
const chromeSource = await readFile(new URL('../workbench/WorkspaceChromeActions.vue', import.meta.url), 'utf8')
const controllerSource = await readFile(new URL('../composables/useAppController.js', import.meta.url), 'utf8')
const appSettingsControllerSource = await readFile(new URL('../features/settings/useAppSettingsController.js', import.meta.url), 'utf8')
const desktopPresentationSource = await readFile(new URL('../config/desktopPresentation.js', import.meta.url), 'utf8')
const creatorSource = await readFile(new URL('../features/creator/CreatorWorkspace.vue', import.meta.url), 'utf8')
const contentActionControllerSource = await readFile(new URL('../workbench/useEditorContentActionMenuController.js', import.meta.url), 'utf8')

test('appearance settings show theme choices without a redundant heading', () => {
  assert.doesNotMatch(source, /settings-appearance-heading/)
  assert.doesNotMatch(source, /每套主题会同时应用到工作台/)
  assert.match(source, /class="settings-theme-grid"/)
})

test('local processing settings show installed models without a storage heading', () => {
  assert.doesNotMatch(source, />模型存储</)
  assert.doesNotMatch(source, /仅列出已下载的模型/)
  assert.match(source, /v-for="model in installedRuntimeModels"/)
})

test('local processing fixes ASR to the native small-model baseline', () => {
  assert.doesNotMatch(source, /识别后端|模型策略|短视频模型|长视频模型|语音活动检测/)
  assert.match(source, /本机原生识别与 small 模型/)
  assert.doesNotMatch(appSource, /v-model:selected-asr-backend|v-model:asr-model-strategy/)
  assert.match(desktopPresentationSource, /whisper_model: 'small'/)
  assert.match(desktopPresentationSource, /asr_model_strategy: 'manual'/)
  assert.match(desktopPresentationSource, /asr_backend: 'auto'/)
  assert.match(controllerSource, /useAppSettingsController/)
  assert.match(appSettingsControllerSource, /localStorage\.removeItem\(ASR_SETTINGS_KEY\)/)
})

test('settings omit retired cache, conversation-mirror, and Telegram controls', () => {
  assert.doesNotMatch(source, /写入与缓存|图片预览缓存|自动管理/)
  assert.doesNotMatch(source, /完整微信对话镜像|openclawTranscriptMirrorEnabled/)
  assert.doesNotMatch(source, /Telegram|telegramBotToken|telegramAllowedUserIds|telegramReplyEnabled/)
  assert.match(source, /自动写入 Markdown/)
  assert.match(source, /微信链接自动处理/)
  assert.match(source, /修复 MCP/)
  assert.match(source, /repair-openclaw-mcp/)
  assert.match(appSource, /repairOpenClawMcp/)
})

test('Telegram controls are absent from the desktop UI', () => {
  assert.doesNotMatch(appSource, /telegram-/)
  assert.doesNotMatch(chromeSource, /Telegram|telegram/)
})

test('privacy settings explain and control the bounded diagnostic data with upload status', () => {
  assert.match(source, /17 个固定的功能结果与处理阶段数据/)
  assert.match(source, /为改进软件体验/)
  assert.match(source, /低频收集 17 个固定的功能结果与处理阶段数据，并发送至 Cloudflare/)
  assert.match(source, /数据最多保留 3 个月/)
  assert.match(source, /上传状态/)
  assert.match(source, /emit\('save-telemetry'/)
  assert.match(source, /emit\('retry-telemetry-upload'/)
  assert.match(appSource, /useTelemetrySettingsController/)
  assert.match(appSource, /loadTelemetryStatus\(\)/)
  assert.doesNotMatch(source, /仅在你允许后/)
  assert.doesNotMatch(source, /未配置官方 HTTPS 收集端前不会上传/)
})

test('privacy settings expose a manual update check wired to the desktop action', () => {
  assert.match(source, /emit\('check-updates'\)/)
  assert.match(source, />检查更新</)
  assert.match(appSource, /@check-updates="checkManualUpdate\(\{ interactive: true \}\)"/)
})

test('Xiaohongshu credentials remain usable while the initial capability state is unknown', () => {
  assert.match(source, /当前仅支持主动导入单篇图文，收藏、创作者同步与评论采集暂未开放/)
  assert.match(source, /:disabled="!platformAuthAvailable \|\| !xiaohongshuSessionProbeAvailable"/)
  assert.match(source, /xiaohongshuCookieStatusLoading/)
  assert.match(source, /v-if="xiaohongshuCredentialStorageAvailable" class="settings-manual-credential"/)
  assert.match(source, /collector_available/)
  assert.match(source, /response\.data\?\.capabilities/)
  assert.match(source, /if \(!xiaohongshuCredentialStorageAvailable\.value\) return/)
  assert.match(source, /session_probe\?\.available !== false/)
  assert.match(source, /if \(!xiaohongshuFavoritesAvailable\.value\) return/)
  assert.match(source, /emit\('check-platform-auth', 'bilibili'\)/)
  assert.match(source, /emit\('check-platform-auth', 'douyin'\)/)
  assert.match(creatorSource, /xhslink\\\.\(\?:com\|cn\)/)
  assert.match(creatorSource, /source\.provider === 'xiaohongshu'/)
  assert.match(creatorSource, /仅历史与缓存/)
  assert.match(creatorSource, /收藏与创作者同步暂未开放/)
  assert.match(creatorSource, /sourceBusy\(source\) \|\| source\.provider === 'xiaohongshu'/)
  assert.doesNotMatch(creatorSource, /小红书个人主页的收藏页链接/)
  assert.match(contentActionControllerSource, /\['bilibili', 'douyin'\]/)
  assert.doesNotMatch(contentActionControllerSource, /\['bilibili', 'douyin', 'xiaohongshu'\]/)
})

test('WeChat authorization is disabled without hiding retained collections', async () => {
  const wechatWorkspaceSource = await readFile(new URL('../features/wechat/WeChatWorkspace.vue', import.meta.url), 'utf8')
  const wechatManagerSource = await readFile(new URL('../features/wechat/WeChatManager.vue', import.meta.url), 'utf8')
  assert.match(source, /:authorization-available="false"/)
  assert.match(wechatWorkspaceSource, /新增授权与订阅暂不可用；已有公众号合集、分组和 RSS 保持可读/)
  assert.match(wechatWorkspaceSource, /:disabled="!authorizationAvailable"/)
  assert.match(wechatManagerSource, /公众号导入暂不可用；已有公众号合集仍可使用/)
  assert.match(wechatManagerSource, /新增授权订阅暂不可用；已有公众号合集仍可使用/)
  assert.match(wechatManagerSource, /复制聚合 RSS 地址/)
})
