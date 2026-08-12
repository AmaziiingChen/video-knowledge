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
})

test('Telegram controls are absent from the desktop UI', () => {
  assert.doesNotMatch(appSource, /telegram-/)
  assert.doesNotMatch(chromeSource, /Telegram|telegram/)
})

test('privacy settings disclose Cloudflare delivery and the three-month retention boundary', () => {
  assert.match(source, /17 个固定检查点/)
  assert.match(source, /低频发送到 Cloudflare/)
  assert.match(source, /匿名数据最多保留 3 个月/)
  assert.match(source, /关闭后会删除本机待发送事件/)
  assert.doesNotMatch(source, /未配置官方 HTTPS 收集端前不会上传/)
})

test('Xiaohongshu feature capabilities keep single-note credentials separate from unsupported sync', () => {
  assert.match(source, /当前仅支持主动导入单篇图文，收藏、创作者同步与评论采集暂未开放/)
  assert.match(source, /:disabled="!platformAuthAvailable \|\| !xiaohongshuSessionProbeAvailable"/)
  assert.match(source, /:disabled="!xiaohongshuSessionProbeAvailable" @click="loadXiaohongshuCookieStatus/)
  assert.match(source, /v-if="xiaohongshuCredentialStorageAvailable" class="settings-manual-credential"/)
  assert.match(source, /collector_available/)
  assert.match(source, /response\.data\?\.capabilities/)
  assert.match(source, /if \(!xiaohongshuCredentialStorageAvailable\.value\) return/)
  assert.match(source, /if \(!xiaohongshuSessionProbeAvailable\.value\) return/)
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
