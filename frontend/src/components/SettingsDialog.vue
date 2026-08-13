<template>
  <el-dialog
    v-model="modelValue"
    width="min(1080px, calc(100vw - 32px))"
    class="settings-dialog"
    :show-close="false"
    align-center
  >
    <template #header>
      <div class="settings-dialog-header">
        <h2>设置</h2>
        <button class="settings-close-button" type="button" aria-label="关闭设置" @click="modelValue = false">
          <IconX :size="20" stroke-width="1.8" />
        </button>
      </div>
    </template>

    <div class="settings-layout">
      <nav class="settings-nav" aria-label="设置分类">
        <section v-for="group in settingsNavigationGroups" :key="group.label" class="settings-nav-group">
          <p class="settings-nav-group-label">{{ group.label }}</p>
          <button
            v-for="item in group.items"
            :key="item.value"
            type="button"
            class="settings-nav-item"
            :class="{ 'is-active': settingsSection === item.value }"
            :aria-current="settingsSection === item.value ? 'page' : undefined"
            @click="settingsSection = item.value"
          >
            <SvgMaskIcon :src="settingsSection === item.value ? (item.activeIcon || item.icon) : item.icon" :size="18" />
            <span>{{ item.label }}</span>
            <span v-if="item.badge" class="settings-nav-badge" aria-hidden="true">{{ item.badge }}</span>
          </button>
        </section>
      </nav>

      <div class="settings-content">
        <section v-show="settingsSection === 'local'" class="settings-page settings-form-page" aria-label="本机处理">
          <div class="settings-page-toolbar">
            <el-button size="small" :loading="runtimeComponentsLoading" @click="emit('load-runtime-components')">重新检查</el-button>
          </div>

          <div class="settings-group">
            <div class="settings-group-head">已选语音模型</div>
            <p class="settings-group-note">本机只使用 {{ runtimeBackendName }}。默认固定使用一个模型，避免短视频策略额外保留另一套权重。</p>
            <div v-for="model in selectedRuntimeModels" :key="`${model.backend}:${model.model}`" class="settings-row">
              <div class="settings-row-copy">
                <h3>{{ model.model }}</h3>
                <p>{{ model.backend === 'mlx' ? 'Apple Silicon 优化模型' : 'Faster-Whisper 模型' }} · {{ model.available ? `已占用 ${formatBytes(model.installed_bytes)}` : model.bundled ? `随应用附带，安装约 ${formatBytes(model.estimated_bytes)}` : `下载约 ${formatBytes(model.estimated_bytes)}` }}</p>
                <details v-if="modelFailureDetail(model)" class="settings-inline-details">
                  <summary>查看下载失败详情</summary>
                  <p>{{ modelFailureDetail(model) }}</p>
                </details>
              </div>
              <div class="settings-row-control settings-row-actions"><span class="settings-status" :class="model.available ? 'is-valid' : 'is-warning'">{{ componentStatusText(model, '已准备', model.bundled ? '可安装' : '未下载') }}</span><el-button size="small" :loading="model.state === 'downloading'" :disabled="model.available" @click="emit('download-asr-model', model)">{{ model.available ? '已可用' : model.bundled ? '安装模型' : '下载模型' }}</el-button></div>
            </div>
            <div v-if="!selectedRuntimeModels.length" class="settings-empty-state">正在读取当前模型的准备状态。</div>
          </div>

          <div class="settings-group">
            <div v-for="model in installedRuntimeModels" :key="`storage:${model.backend}:${model.model}`" class="settings-row">
              <div class="settings-row-copy">
                <h3>{{ model.model }}</h3>
                <p>{{ model.backend === 'mlx' ? 'MLX' : 'Faster-Whisper' }} · 已占用 {{ formatBytes(model.installed_bytes) }}<span v-if="!model.preferred"> · 旧兼容缓存</span></p>
              </div>
              <div class="settings-row-control settings-row-actions">
                <span class="settings-status" :class="isCurrentRuntimeModel(model) ? 'is-active' : 'is-idle'">{{ isCurrentRuntimeModel(model) ? '当前使用' : '可移除' }}</span>
                <el-button size="small" :disabled="isCurrentRuntimeModel(model)" @click="emit('delete-asr-model', model)">{{ isCurrentRuntimeModel(model) ? '当前模型' : '移除' }}</el-button>
              </div>
            </div>
            <div v-if="!installedRuntimeModels.length" class="settings-empty-state">尚未下载本机语音模型。</div>
          </div>
        </section>

        <section v-show="settingsSection === 'appearance'" class="settings-page settings-appearance-page" aria-label="外观">
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-theme-grid">
                <button v-for="option in themeOptions" :key="option.value" type="button" class="settings-theme-card" :class="{ 'is-selected': selectedTheme === option.value }" :aria-pressed="selectedTheme === option.value" @click="selectedTheme = option.value">
                  <span class="settings-theme-card-swatches"><i :style="{ background: option.accent }"></i><i :style="{ background: option.background }"></i><i :style="{ background: option.foreground }"></i></span>
                  <span><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
                </button>
              </div>
            </div>
          </div>
        </section>

        <section v-show="settingsSection === 'privacy'" class="settings-page settings-form-page" aria-label="隐私与诊断">
          <div class="settings-group" :aria-busy="telemetryStatusLoading || telemetrySaving">
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>发送去标识使用诊断</h3>
                <p>新安装默认开启，低频发送 17 个固定检查点到 Cloudflare。不会包含文章、视频、OCR 文本、搜索词、路径、链接、账号、密钥或错误原文；数据最多保留 3 个月。事件范围或用途变更时会再次告知。</p>
              </div>
              <div class="settings-row-control settings-switch-control">
                <el-switch
                  v-model="telemetryEnabled"
                  :loading="telemetryStatusLoading || telemetrySaving"
                  :disabled="!telemetryStatusLoaded || telemetryStatusLoading || telemetrySaving"
                  aria-label="发送去标识使用诊断"
                  aria-describedby="telemetry-status-note"
                  @change="saveTelemetry"
                />
              </div>
            </div>
            <p id="telemetry-status-note" class="settings-group-note" role="status" aria-live="polite">
              <template v-if="telemetryStatusLoading">正在读取当前诊断状态…</template>
              <template v-else-if="telemetryStatusError">
                {{ telemetryStatusError }}
                <el-button link size="small" @click="loadTelemetryStatus">重试</el-button>
              </template>
              <template v-else-if="telemetryStatusLoaded">本机待发送：{{ telemetryPendingEvents }} 条。关闭会删除本机队列和随机安装标识，只保留“不发送”的本机偏好；已发送数据将在保留期结束后删除。</template>
              <template v-else>尚未读取当前诊断状态。</template>
            </p>
          </div>
        </section>

        <section v-show="settingsSection === 'local'" class="settings-page settings-form-page" aria-label="本机处理">
          <div class="settings-group settings-group-note-only">
            <p class="settings-group-note">音视频转写会自动使用本机原生识别与 small 模型，无需单独调整。</p>
          </div>
        </section>

        <section v-show="settingsSection === 'ai'" class="settings-page settings-ai-page" aria-label="AI 服务">
          <div class="settings-group settings-ai-collection-group">
            <div class="settings-ai-field settings-ai-toggle-field">
              <div class="settings-ai-field-heading">
                <h3>主动收藏自动生成 AI 总结</h3>
                <p>主动保存的内容自动生成总结；关闭后仅入库，不调用模型。</p>
              </div>
              <div class="settings-ai-toggle-control">
                <el-switch v-model="manualAutoSummarize" aria-label="主动收藏自动生成 AI 总结" @change="emit('save-manual-collection-settings')" />
              </div>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-head">文本模型</div>
            <div class="settings-ai-field settings-ai-service">
              <div class="settings-ai-field-heading">
                <h3>文本模型服务</h3>
                <p>管理 DeepSeek、千问、MiMo 与其他 OpenAI 兼容服务。不会自动切换服务。</p>
              </div>
              <TextModelProviderSettings
                v-model:selected-model="selectedAiModel"
                @options-updated="emit('text-model-options-updated', $event)"
              />
            </div>
            <div class="settings-ai-field settings-ai-pricing-field">
              <details class="settings-ai-pricing-disclosure" open>
                <summary><span>DeepSeek Token 估算价格</span></summary>
                <p>单位为元／百万 tokens；仅用于本机估算，最终扣费以服务商账单为准。</p>
                <div class="settings-pricing-control">
                  <div v-for="model in textPricingModels" :key="model.key" class="settings-pricing-card">
                    <strong>{{ model.label }}</strong>
                    <label><span>缓存命中</span><el-input-number v-model="deepseekPricing[model.key].input_cache_hit" :min="0" :max="1000000" :step="0.001" :precision="3" :controls="false" /></label>
                    <label><span>缓存未命中</span><el-input-number v-model="deepseekPricing[model.key].input_cache_miss" :min="0" :max="1000000" :step="0.1" :precision="3" :controls="false" /></label>
                    <label><span>输出</span><el-input-number v-model="deepseekPricing[model.key].output" :min="0" :max="1000000" :step="0.1" :precision="3" :controls="false" /></label>
                  </div>
                  <div class="settings-pricing-peak">
                    <span><strong>高峰计价</strong> 如服务商账单启用，北京时间每日 9:00–12:00、14:00–18:00</span>
                    <label>高峰倍率<el-input-number v-model="deepseekPeakPricingMultiplier" :min="0" :max="100" :step="0.1" :precision="2" :controls="false" /></label>
                  </div>
                </div>
                <div class="settings-actions settings-ai-actions">
                  <el-button type="primary" size="small" :loading="savingDeepseekSettings" :disabled="savingDeepseekSettings" @click="emit('save-deepseek-settings')">保存估算价格</el-button>
                </div>
              </details>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-head">视觉模型</div>
            <div class="settings-ai-field settings-ai-service">
              <div class="settings-ai-field-heading">
                <h3>AI 图像模型</h3>
                <p>用于生成公众号日报、周报的封面图片。</p>
              </div>
              <label class="settings-ai-input-label" for="visual-model">Model</label>
              <el-select id="visual-model" v-model="wechatQwenCoverModel" class="settings-ai-select" name="visual-model" filterable allow-create default-first-option aria-label="图像模型名称" placeholder="选择或输入模型">
                <el-option v-for="option in visualModelOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <label class="settings-ai-input-label" for="visual-api-key">API Key</label>
              <el-input id="visual-api-key" v-model="wechatQwenCoverApiKey" class="settings-ai-icon-input" :type="showWechatQwenCoverApiKey ? 'text' : 'password'" name="visual-api-key" autocomplete="off" spellcheck="false" aria-label="图像模型 API Key" :placeholder="credentialPlaceholder(wechatQwenCoverSettings.configured, 'API Key')">
                <template #prefix><SvgMaskIcon :src="keyCircleIcon" :size="17" /></template>
                <template #suffix><button class="settings-ai-input-icon-button" type="button" :aria-label="showWechatQwenCoverApiKey ? '隐藏图像模型 API Key' : '显示图像模型 API Key'" @mousedown.prevent @click="toggleWechatQwenCoverApiKeyVisibility"><SvgMaskIcon :src="showWechatQwenCoverApiKey ? eyeSlashIcon : eyeIcon" :size="17" /></button></template>
              </el-input>
              <label class="settings-ai-input-label" for="visual-base-url">Base URL</label>
              <el-input id="visual-base-url" v-model="wechatQwenCoverEndpoint" class="settings-ai-icon-input" type="url" name="visual-base-url" autocomplete="off" inputmode="url" spellcheck="false" aria-label="图像模型 Base URL">
                <template #prefix><SvgMaskIcon :src="globeIcon" :size="17" /></template>
              </el-input>
              <div class="settings-ai-field-actions">
                <el-button size="small" :loading="testingWechatQwenCoverConnection" :disabled="savingWechatQwenCoverSettings" @click="emit('test-wechat-qwen-cover-connection')">测试连接</el-button>
                <el-button size="small" type="primary" :loading="savingWechatQwenCoverSettings" :disabled="testingWechatQwenCoverConnection" @click="emit('save-wechat-qwen-cover-settings')">保存</el-button>
              </div>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-head">向量模型</div>
            <div class="settings-ai-field settings-ai-service">
              <div class="settings-ai-field-heading">
                <h3>Embedding 模型</h3>
                <p>用于知识库的语义检索。</p>
              </div>
              <label class="settings-ai-input-label" for="embedding-model">Model</label>
              <el-select id="embedding-model" v-model="embeddingModel" class="settings-ai-select" name="embedding-model" filterable allow-create default-first-option aria-label="Embedding 模型名称" placeholder="选择或输入模型">
                <el-option v-for="option in embeddingModelOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <label class="settings-ai-input-label" for="embedding-api-key">API Key</label>
              <el-input id="embedding-api-key" v-model="embeddingApiKey" class="settings-ai-icon-input" :type="showEmbeddingApiKey ? 'text' : 'password'" name="embedding-api-key" autocomplete="off" spellcheck="false" aria-label="Embedding API Key" :placeholder="credentialPlaceholder(embeddingConfigured, 'API Key')">
                <template #prefix><SvgMaskIcon :src="keyCircleIcon" :size="17" /></template>
                <template #suffix><button class="settings-ai-input-icon-button" type="button" :aria-label="showEmbeddingApiKey ? '隐藏 Embedding API Key' : '显示 Embedding API Key'" @mousedown.prevent @click="toggleEmbeddingApiKeyVisibility"><SvgMaskIcon :src="showEmbeddingApiKey ? eyeSlashIcon : eyeIcon" :size="17" /></button></template>
              </el-input>
              <label class="settings-ai-input-label" for="embedding-base-url">Base URL</label>
              <el-input id="embedding-base-url" v-model="embeddingBaseUrl" class="settings-ai-icon-input" type="url" name="embedding-base-url" autocomplete="off" inputmode="url" spellcheck="false" aria-label="Embedding Base URL" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1">
                <template #prefix><SvgMaskIcon :src="globeIcon" :size="17" /></template>
              </el-input>
              <div class="settings-ai-field-actions">
                <el-button size="small" :loading="testingEmbeddingConnection" :disabled="savingEmbeddingSettings" @click="emit('test-embedding-connection')">测试连接</el-button>
                <el-button size="small" type="primary" :loading="savingEmbeddingSettings" :disabled="testingEmbeddingConnection" @click="emit('save-embedding-settings')">保存</el-button>
              </div>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-head">文档识别</div>
            <div class="settings-ai-field settings-ai-service">
              <div class="settings-ai-field-heading">
                <h3>PaddleOCR 文档识别</h3>
                <p>识别文章图片中的文字和表格。</p>
              </div>
              <label class="settings-ai-input-label" for="paddleocr-model">Model</label>
              <el-select id="paddleocr-model" v-model="paddleOcrModel" class="settings-ai-select" name="paddleocr-model" filterable allow-create default-first-option aria-label="PaddleOCR 模型名称" placeholder="选择或输入模型">
                <el-option v-for="option in paddleOcrModelOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
              <label class="settings-ai-input-label" for="paddleocr-access-token">Access Token</label>
              <el-input id="paddleocr-access-token" v-model="paddleOcrAccessToken" class="settings-ai-icon-input" :type="showPaddleOcrAccessToken ? 'text' : 'password'" name="paddleocr-access-token" autocomplete="off" spellcheck="false" aria-label="PaddleOCR Access Token" :placeholder="credentialPlaceholder(paddleOcrConfigured, 'Access Token')">
                <template #prefix><SvgMaskIcon :src="keyCircleIcon" :size="17" /></template>
                <template #suffix><button class="settings-ai-input-icon-button" type="button" :aria-label="showPaddleOcrAccessToken ? '隐藏 PaddleOCR Access Token' : '显示 PaddleOCR Access Token'" @mousedown.prevent @click="togglePaddleOcrAccessTokenVisibility"><SvgMaskIcon :src="showPaddleOcrAccessToken ? eyeSlashIcon : eyeIcon" :size="17" /></button></template>
              </el-input>
              <label class="settings-ai-input-label" for="paddleocr-base-url">Base URL</label>
              <el-input id="paddleocr-base-url" v-model="paddleOcrBaseUrl" class="settings-ai-icon-input" type="url" name="paddleocr-base-url" autocomplete="off" inputmode="url" spellcheck="false" aria-label="PaddleOCR Base URL" placeholder="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs">
                <template #prefix><SvgMaskIcon :src="globeIcon" :size="17" /></template>
              </el-input>
              <div class="settings-ai-field-actions">
                <el-button size="small" type="primary" :loading="savingPaddleOcrSettings" @click="emit('save-paddle-ocr-settings')">保存</el-button>
              </div>
            </div>
          </div>
        </section>

        <section v-show="settingsSection === 'storage'" class="settings-page settings-form-page" aria-label="存储">
          <div class="settings-group">
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>自动写入 Markdown</h3>
                <p>启用后，文章正文、图片 OCR 文本和视频信息会写入下方资料库目录；关闭后仅保存在应用本地资料库。</p>
              </div>
              <div class="settings-row-control settings-switch-control">
                <el-switch v-model="obsidianAutoWrite" aria-label="自动写入 Markdown" @change="emit('save-obsidian')" />
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>B 站字幕内容下载视频预览</h3>
                <p>关闭时优先保存字幕文本，不下载视频；开启后会额外下载本地预览视频，视频缓存保留 14 天。</p>
              </div>
              <div class="settings-row-control settings-switch-control">
                <el-switch v-model="autoDownloadBilibiliVideo" aria-label="B站字幕内容自动下载视频预览" @change="emit('save-video-download-settings')" />
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>抖音视频下载质量</h3>
                <p>标准质量适合本机预览与转写；省流量优先减少缓存占用，高质量适合需要保留画面的内容。</p>
              </div>
              <div class="settings-row-control">
                <el-select v-model="douyinVideoQuality" aria-label="抖音视频下载质量" @change="emit('save-video-download-settings')">
                  <el-option label="省流量" value="low" />
                  <el-option label="标准" value="standard" />
                  <el-option label="高质量" value="high" />
                </el-select>
              </div>
            </div>
            <div class="settings-row settings-row-multiline">
              <div class="settings-row-copy">
                <h3>资料库写入目录</h3>
                <p>可以是 Obsidian 仓库，也可以是任意本机文件夹。切换目录时，会迁移应用已入库的文章、视频和附件；不会移动你的其他文件。</p>
              </div>
              <div class="settings-row-control settings-input-control">
                <el-input v-model="obsidianVaultPath" name="obsidian-vault-path" autocomplete="off" aria-label="自动写入目录" placeholder="选择本机文件夹…" @change="emit('save-obsidian')" />
                <el-button round @click="emit('choose-obsidian-folder')">选择文件夹</el-button>
              </div>
            </div>
            <div class="settings-row settings-row-multiline">
              <div class="settings-row-copy">
                <h3>默认导出目录</h3>
                <p>AI 对话区的“导出 Markdown”会写到这里；同名文件同样会覆盖。</p>
              </div>
              <div class="settings-row-control settings-input-control">
                <el-input v-model="markdownExportPath" name="markdown-export-path" autocomplete="off" aria-label="默认导出目录" placeholder="选择默认导出文件夹…" @change="emit('save-obsidian')" />
                <el-button round @click="emit('choose-export-folder')">选择文件夹</el-button>
              </div>
            </div>
          </div>
        </section>

        <section v-show="settingsSection === 'connections'" class="settings-page settings-form-page" aria-label="连接">

          <div class="settings-group">
            <div class="settings-group-head">本机服务</div>
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>本机剪贴板监听</h3>
                <p>识别复制到剪贴板的链接，并创建处理任务。</p>
              </div>
              <div class="settings-row-control settings-row-actions">
                <span class="settings-status" :class="clipboardWatching ? 'is-active' : 'is-idle'">{{ clipboardWatching ? '监听中' : '未开启' }}</span>
                <el-switch :model-value="clipboardWatching" aria-label="本机剪贴板监听" :disabled="clipboardScanning" @change="emit('toggle-clipboard', $event)" />
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-copy">
                <h3>本地资料收件箱</h3>
                <p>监听一个指定文件夹；仅导入开启后新放入的文件，原件会复制到应用资料库。</p>
                <small v-if="folderImportPath" class="settings-folder-path" :title="folderImportPath">{{ folderImportPath }}</small>
              </div>
              <div class="settings-row-control settings-row-actions">
                <el-button size="small" :disabled="folderImportScanning" @click="emit('choose-folder-import')">选择文件夹</el-button>
                <span class="settings-status" :class="folderImportWatching ? 'is-active' : 'is-idle'">{{ folderImportWatching ? '监听中' : '未开启' }}</span>
                <el-switch :model-value="folderImportWatching" aria-label="本地资料收件箱监听" :disabled="folderImportScanning" @change="emit('toggle-folder-import', $event)" />
              </div>
            </div>
            <div class="settings-row settings-openclaw-row">
              <div class="settings-row-copy">
                <h3>微信链接自动处理</h3>
                <p>在微信发送支持的链接后，OpenClaw 会将它交给这台 Mac 处理。</p>
              </div>
              <div class="settings-row-control settings-row-actions">
                <span class="settings-status" :class="openclawStatusTone">{{ openclawStatusText }}</span>
                <el-button size="small" :loading="openclawScanning" @click="emit('start-openclaw')">
                  {{ openclawRunning ? '诊断' : '启动' }}
                </el-button>
              </div>
              <div class="settings-openclaw-path" aria-label="微信链接自动处理连接状态">
                <span v-for="item in openclawConnectionItems" :key="item.key" class="settings-openclaw-path-item">
                  <span class="settings-status" :class="item.stateClass">{{ item.label }}</span>
                  <span class="settings-openclaw-path-detail">{{ item.detail }}</span>
                </span>
              </div>
            </div>
          </div>

        </section>

        <section v-show="settingsSection === 'wechat'" class="settings-page settings-wechat-page" aria-label="微信公众号">
          <div class="settings-page-toolbar">
            <div class="settings-wechat-summary">
              <span class="settings-status" :class="wechatAccountStatusTone">
                {{ wechatAccountStatusSummary }}
              </span>
              <el-button size="small" :loading="wechatLoading" @click="emit('load-wechat')">刷新状态</el-button>
              <el-button size="small" round @click="emit('open-wechat-manager')">前往公众号管理</el-button>
            </div>
          </div>
          <WeChatWorkspace
            mode="accounts"
            embedded
            v-model:selected-account-id="wechatSelectedAccountId"
            v-model:account-display-name="wechatAccountDisplayName"
            v-model:manual-token="wechatManualToken"
            v-model:manual-cookie="wechatManualCookie"
            v-model:search-query="wechatSearchQuery"
            v-model:subscription-interval="wechatSubscriptionInterval"
            v-model:auto-process="wechatAutoProcess"
            v-model:publishing-display-name="wechatPublishingDisplayName"
            v-model:publishing-app-id="wechatPublishingAppId"
            v-model:publishing-app-secret="wechatPublishingAppSecret"
            v-model:public-site-base-url="wechatPublicSiteBaseUrl"
            :loading="wechatLoading"
            :accounts="wechatAccounts"
            :subscriptions="wechatSubscriptions"
            :qr-login="wechatQrLogin"
            :qr-starting="wechatQrStarting"
            :manual-connecting="wechatManualConnecting"
            :search-results="wechatSearchResults"
            :searching="wechatSearching"
            :interval-options="wechatIntervalOptions"
            :subscription-states="wechatSubscriptionStates"
            :syncing-subscription-id="wechatSyncingSubscriptionId"
            :content-filters="wechatContentFilters"
            :report-groups="wechatReportGroups"
            :generating-group-id="wechatGeneratingGroupId"
            :saving-filter="wechatFilterSaving"
            :auto-sync-summary="wechatAutoSyncSummary"
            :last-sync-summary="wechatLastSyncSummary"
            :publishing-settings="wechatPublishingSettings"
            :saving-publishing-settings="savingWechatPublishingSettings"
            @start-qr="emit('start-wechat-qr')"
            @reauthorize-account="emit('reauthorize-account', $event)"
            @connect-manual="emit('connect-wechat-manually')"
            @delete-account="emit('delete-wechat-account', $event)"
            @transfer-account-subscriptions="emit('transfer-account-subscriptions', $event)"
            @search="emit('search-wechat')"
            @subscribe="emit('subscribe-wechat', $event)"
            @update-subscription="(subscription, payload) => emit('update-wechat-subscription', subscription, payload)"
            @sync-subscription="(subscriptionId, maxItems) => emit('sync-wechat-subscription', subscriptionId, maxItems)"
            @delete-subscription="emit('delete-wechat-subscription', $event)"
            @create-filter="(payload, done) => emit('create-wechat-filter', payload, done)"
            @delete-filter="emit('delete-wechat-filter', $event)"
            @create-report-group="(payload, done) => emit('create-wechat-report-group', payload, done)"
            @generate-report="(groupId, reportType) => emit('generate-wechat-report', groupId, reportType)"
            @copy-rss="emit('copy-wechat-rss', $event)"
            @export-subscriptions="emit('export-wechat-subscriptions')"
            @save-publishing-settings="emit('save-wechat-publishing-settings')"
          />
        </section>

        <section v-show="settingsSection === 'credentials'" class="settings-page settings-form-page" aria-label="下载与凭据">
          <div class="settings-group">
            <div class="settings-group-head">下载工具</div>
            <div class="settings-row settings-row-secret">
              <div class="settings-row-copy"><h3>ffmpeg</h3><p>用于音频提取、视频合并和压缩。留空时自动从系统中检测；可运行 <code>brew install ffmpeg</code> 后重新检测。</p></div>
              <div class="settings-row-control settings-credential-control">
                <div class="settings-credential-meta"><span class="settings-status" :class="mediaTools.ffmpeg_path?.available ? 'is-valid' : 'is-warning'">{{ mediaTools.ffmpeg_path?.available ? '已找到' : '未找到' }}</span><span class="settings-credential-domain">{{ mediaTools.ffmpeg_path?.resolved_path || '请填写完整可执行文件路径' }}</span></div>
                <div class="settings-input-group"><el-input v-model="ffmpegPath" name="ffmpeg-path" autocomplete="off" spellcheck="false" aria-label="ffmpeg 可执行文件路径" placeholder="例如：/opt/homebrew/bin/ffmpeg…" /><el-button class="settings-input-group-action" @click="emit('choose-media-tool', 'ffmpeg')">选择文件</el-button></div>
                <div class="settings-secret-actions settings-tool-actions settings-input-stack-actions"><el-button size="small" type="primary" :loading="savingMediaTools" @click="emit('save-media-tools')">保存并检测</el-button></div>
              </div>
            </div>
            <div class="settings-row settings-row-secret">
              <div class="settings-row-copy"><h3>yt-dlp</h3><p>用于下载视频和获取字幕。留空时自动从系统中检测；可运行 <code>brew install yt-dlp</code> 后重新检测。</p></div>
              <div class="settings-row-control settings-credential-control">
                <div class="settings-credential-meta"><span class="settings-status" :class="mediaTools.yt_dlp_path?.available ? 'is-valid' : 'is-warning'">{{ mediaTools.yt_dlp_path?.available ? '已找到' : '未找到' }}</span><span class="settings-credential-domain">{{ mediaTools.yt_dlp_path?.resolved_path || '请填写完整可执行文件路径' }}</span></div>
                <div class="settings-input-group"><el-input v-model="ytDlpPath" name="yt-dlp-path" autocomplete="off" spellcheck="false" aria-label="yt-dlp 可执行文件路径" placeholder="例如：/opt/homebrew/bin/yt-dlp…" /><el-button class="settings-input-group-action" @click="emit('choose-media-tool', 'yt-dlp')">选择文件</el-button></div>
                <div class="settings-secret-actions settings-tool-actions settings-input-stack-actions"><el-button size="small" type="primary" :loading="savingMediaTools" @click="emit('save-media-tools')">保存并检测</el-button></div>
              </div>
            </div>
            <div class="settings-row">
              <div class="settings-row-copy"><h3>浏览器组件</h3><p>{{ runtimeComponents.browser?.available ? runtimeComponents.browser.detail : '抖音下载失败时使用的浏览器兜底。优先复用本机 Chrome。' }}</p></div>
              <div class="settings-row-control settings-row-actions"><span class="settings-status" :class="runtimeComponents.browser?.available ? 'is-valid' : 'is-warning'">{{ componentStatusText(runtimeComponents.browser, '已准备', '未准备') }}</span><el-button size="small" :loading="runtimeComponents.browser?.state === 'downloading'" :disabled="runtimeComponents.browser?.available" @click="emit('install-browser')">{{ runtimeComponents.browser?.available ? '已可用' : '下载组件' }}</el-button></div>
            </div>
          </div>
          <div class="settings-group">
            <div class="settings-group-head">平台凭据</div>
            <div class="settings-platform-credential">
              <div class="settings-row-copy">
                <h3>抖音下载凭证</h3>
                <p>{{ cookieConfigured ? '已保存。状态栏会定期检测真实下载可用性。' : '在应用内登录后自动保存，不需要复制浏览器 Cookie。' }}</p>
              </div>
              <div class="settings-platform-credential-meta">
                <span class="settings-status" :class="`is-${cookieState}`">{{ cookieChecking ? '正在检测' : cookieStatusText }}</span>
                <span class="settings-credential-domain">douyin.com</span>
              </div>
              <div class="settings-platform-credential-actions">
                <span>登录窗口与主应用隔离；原始 Cookie 不会显示或复制到页面。</span>
                <div class="settings-platform-credential-buttons">
                  <el-button size="small" type="primary" round :loading="platformAuthConnecting === 'douyin'" :disabled="!platformAuthAvailable" @click="emit('connect-platform-auth', 'douyin')">登录并连接</el-button>
                  <el-button size="small" plain round :loading="cookieChecking" @click="emit('check-platform-auth', 'douyin')">检查可用性</el-button>
                  <el-button v-if="cookieConfigured && platformAuthAvailable" size="small" text class="settings-disconnect-button" :disabled="platformAuthConnecting === 'douyin'" @click="emit('disconnect-platform-auth', 'douyin')">断开</el-button>
                </div>
              </div>
              <details class="settings-manual-credential"><summary>手动粘贴 Cookie（备用）</summary><div class="settings-platform-credential-input"><div class="settings-input-group"><span class="settings-input-group-addon">Cookie</span><el-input class="settings-cookie-input" v-model="cookieInput" type="password" name="douyin-cookie" autocomplete="off" spellcheck="false" aria-label="抖音下载 Cookie" :placeholder="credentialPlaceholder(cookieConfigured, 'Cookie')" /><el-button class="settings-input-group-action" type="primary" :loading="savingCookie" :disabled="!cookieInput.trim()" @click="emit('save-cookie')">保存</el-button></div></div></details>
            </div>
            <div class="settings-platform-credential">
              <div class="settings-row-copy">
                <h3>B站登录凭证</h3>
                <p>{{ bilibiliCookieConfigured ? '已保存，可用于提取需登录的字幕和下载受限清晰度。' : '在应用内登录后自动保存，可用于字幕、收藏夹和受限清晰度。' }}</p>
              </div>
              <div class="settings-platform-credential-meta">
                <span class="settings-status" :class="`is-${bilibiliCookieState}`">{{ bilibiliCookieStatusText }}</span>
                <span class="settings-credential-domain">bilibili.com</span>
              </div>
              <div class="settings-platform-credential-actions">
                <span>登录窗口与主应用隔离；只保存 B站会话，不会展示原始 Cookie。</span>
                <div class="settings-platform-credential-buttons">
                  <el-button size="small" type="primary" round :loading="platformAuthConnecting === 'bilibili'" :disabled="!platformAuthAvailable" @click="emit('connect-platform-auth', 'bilibili')">登录并连接</el-button>
                  <el-button size="small" plain round :loading="bilibiliCookieState === 'loading'" @click="emit('check-platform-auth', 'bilibili')">检查可用性</el-button>
                  <el-button v-if="bilibiliCookieConfigured && platformAuthAvailable" size="small" text class="settings-disconnect-button" :disabled="platformAuthConnecting === 'bilibili'" @click="emit('disconnect-platform-auth', 'bilibili')">断开</el-button>
                </div>
              </div>
              <details class="settings-manual-credential"><summary>手动粘贴 Cookie（备用）</summary><div class="settings-platform-credential-input"><div class="settings-input-group"><span class="settings-input-group-addon">Cookie</span><el-input class="settings-cookie-input" v-model="bilibiliCookieInput" type="password" name="bilibili-cookie" autocomplete="off" spellcheck="false" aria-label="B站登录 Cookie" :placeholder="credentialPlaceholder(bilibiliCookieConfigured, 'Cookie')" /><el-button class="settings-input-group-action" type="primary" :loading="savingBilibiliCookie" :disabled="!bilibiliCookieInput.trim()" @click="emit('save-bilibili-cookie')">保存</el-button></div></div></details>
            </div>
            <div class="settings-platform-credential">
              <div class="settings-row-copy">
                <h3>小红书登录凭据</h3>
                <p>{{ xiaohongshuNoteCaptureAvailable ? (xiaohongshuCookieConfigured ? '已保存，可用于主动导入单篇图文。' : '在应用内登录后自动保存，不需要复制浏览器 Cookie。') : xiaohongshuNoteCaptureReason }}</p>
              </div>
              <div class="settings-platform-credential-meta">
                <span class="settings-status" :class="`is-${xiaohongshuCookieState}`">{{ xiaohongshuCookieStatusText }}</span>
                <span class="settings-credential-domain">xiaohongshu.com</span>
              </div>
              <div class="settings-platform-credential-actions">
                <span>登录窗口与主应用隔离；凭据仅保存在本机且不会展示。当前仅支持主动导入单篇图文，收藏、创作者同步与评论采集暂未开放。</span>
                <div class="settings-platform-credential-buttons">
                  <el-button size="small" type="primary" round :loading="xiaohongshuAuthConnecting" :disabled="!platformAuthAvailable || !xiaohongshuSessionProbeAvailable" @click="connectXiaohongshuAuth">登录并连接</el-button>
                  <el-button size="small" plain round :loading="xiaohongshuCookieState === 'loading'" :disabled="!xiaohongshuSessionProbeAvailable" @click="loadXiaohongshuCookieStatus(true)">检查可用性</el-button>
                  <el-button v-if="xiaohongshuCookieConfigured && platformAuthAvailable" size="small" text class="settings-disconnect-button" :disabled="xiaohongshuAuthConnecting" @click="disconnectXiaohongshuAuth">断开</el-button>
                </div>
              </div>
              <details v-if="xiaohongshuCredentialStorageAvailable" class="settings-manual-credential"><summary>手动粘贴 Cookie（备用）</summary><div class="settings-platform-credential-input"><div class="settings-input-group"><span class="settings-input-group-addon">Cookie</span><el-input class="settings-cookie-input" v-model="xiaohongshuCookieInput" type="password" name="xiaohongshu-cookie" autocomplete="off" spellcheck="false" aria-label="小红书 Cookie" :placeholder="credentialPlaceholder(xiaohongshuCookieConfigured, 'Cookie')" /><el-button class="settings-input-group-action" type="primary" :loading="savingXiaohongshuCookie" :disabled="!xiaohongshuCookieInput.trim()" @click="saveXiaohongshuCookie">保存</el-button></div></div></details>
            </div>
          </div>
        </section>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { IconX } from './macosSymbolComponents.js'
import WeChatWorkspace from '../features/wechat/WeChatWorkspace.vue'
import TextModelProviderSettings from '../features/settings/TextModelProviderSettings.vue'
import { useTelemetrySettingsController } from '../features/telemetry/useTelemetrySettingsController.js'
import { enqueueSourceSyncTask, observeSourceSyncTask } from '../utils/sourceSyncTask'
import { API_BASE as API } from '../utils/localApiAuth.js'
import SvgMaskIcon from './SvgMaskIcon.vue'
const appleIntelligenceIcon = 'apple.intelligence'
const keyIcon = 'key'
const keyCircleIcon = 'key.circle'
const linkIcon = 'link'
const globeIcon = 'globe'
const eyeIcon = 'eye'
const eyeSlashIcon = 'eye.slash'
const paintPaletteIcon = 'paintpalette'
const wechatIcon = 'wechat'
import { requestDestructiveConfirmation } from '../composables/useDestructiveConfirm'

const modelValue = defineModel({ type: Boolean, default: false })
const selectedTheme = defineModel('selectedTheme', { type: String, default: '' })
const selectedAiModel = defineModel('selectedAiModel', { type: String, default: '' })
const deepseekPricing = defineModel('deepseekPricing', {
  type: Object,
  default: () => ({
    'deepseek-v4-flash': { input_cache_hit: 0.02, input_cache_miss: 1, output: 2 },
    'deepseek-v4-pro': { input_cache_hit: 0.025, input_cache_miss: 3, output: 6 }
  })
})
const deepseekPeakPricingMultiplier = defineModel('deepseekPeakPricingMultiplier', { type: Number, default: 1 })
const embeddingApiKey = defineModel('embeddingApiKey', { type: String, default: '' })
const embeddingBaseUrl = defineModel('embeddingBaseUrl', { type: String, default: 'https://dashscope.aliyuncs.com/compatible-mode/v1' })
const embeddingModel = defineModel('embeddingModel', { type: String, default: 'qwen3.7-text-embedding' })
const paddleOcrAccessToken = defineModel('paddleOcrAccessToken', { type: String, default: '' })
const paddleOcrBaseUrl = defineModel('paddleOcrBaseUrl', { type: String, default: 'https://paddleocr.aistudio-app.com/api/v2/ocr/jobs' })
const paddleOcrModel = defineModel('paddleOcrModel', { type: String, default: 'PaddleOCR-VL-1.6' })
const showEmbeddingApiKey = ref(false)
const showPaddleOcrAccessToken = ref(false)
const showWechatQwenCoverApiKey = ref(false)
const manualAutoSummarize = defineModel('manualAutoSummarize', { type: Boolean, default: true })
const autoDownloadBilibiliVideo = defineModel('autoDownloadBilibiliVideo', { type: Boolean, default: false })
const douyinVideoQuality = defineModel('douyinVideoQuality', { type: String, default: 'standard' })
const obsidianVaultPath = defineModel('obsidianVaultPath', { type: String, default: '' })
const markdownExportPath = defineModel('markdownExportPath', { type: String, default: '' })
const obsidianAutoWrite = defineModel('obsidianAutoWrite', { type: Boolean, default: false })
const cookieInput = defineModel('cookieInput', { type: String, default: '' })
const bilibiliCookieInput = defineModel('bilibiliCookieInput', { type: String, default: '' })
const ffmpegPath = defineModel('ffmpegPath', { type: String, default: '' })
const ytDlpPath = defineModel('ytDlpPath', { type: String, default: '' })
const wechatSelectedAccountId = defineModel('wechatSelectedAccountId', { type: [String, Number], default: '' })
const wechatAccountDisplayName = defineModel('wechatAccountDisplayName', { type: String, default: '' })
const wechatManualToken = defineModel('wechatManualToken', { type: String, default: '' })
const wechatManualCookie = defineModel('wechatManualCookie', { type: String, default: '' })
const wechatSearchQuery = defineModel('wechatSearchQuery', { type: String, default: '' })
const wechatSubscriptionInterval = defineModel('wechatSubscriptionInterval', { type: Number, default: 1440 })
const wechatAutoProcess = defineModel('wechatAutoProcess', { type: Boolean, default: false })
const wechatPublishingDisplayName = defineModel('wechatPublishingDisplayName', { type: String, default: '订阅号' })
const wechatPublishingAppId = defineModel('wechatPublishingAppId', { type: String, default: '' })
const wechatPublishingAppSecret = defineModel('wechatPublishingAppSecret', { type: String, default: '' })
const wechatPublicSiteBaseUrl = defineModel('wechatPublicSiteBaseUrl', { type: String, default: '' })
const wechatQwenCoverApiKey = defineModel('wechatQwenCoverApiKey', { type: String, default: '' })
const wechatQwenCoverEndpoint = defineModel('wechatQwenCoverEndpoint', { type: String, default: '' })
const wechatQwenCoverModel = defineModel('wechatQwenCoverModel', { type: String, default: 'qwen-image-2.0' })
const { 
  initialSection,
  themeOptions,
  selectedThemeOption,
  availableAiModels,
  clipboardWatching,
  clipboardScanning,
  openclawRunning,
  openclawScanning,
  openclawStatusText,
  openclawConnectionItems,
  openclawStatusTone,
  wechatAccounts,
  wechatSubscriptions,
  wechatLoading,
  wechatQrLogin,
  wechatQrStarting,
  wechatManualConnecting,
  wechatSearchResults,
  wechatSearching,
  wechatIntervalOptions,
  wechatSubscriptionStates,
  wechatSyncingSubscriptionId,
  wechatContentFilters,
  wechatReportGroups,
  wechatGeneratingGroupId,
  wechatDeletingGroupId,
  wechatFilterSaving,
  wechatAutoSyncSummary,
  wechatLastSyncSummary,
  wechatPublishingSettings,
  savingWechatPublishingSettings,
  wechatQwenCoverSettings,
  savingWechatQwenCoverSettings,
  testingWechatQwenCoverConnection,
  cookieConfigured,
  cookieState,
  cookieStatusText,
  cookieChecking,
  savingCookie,
  bilibiliCookieConfigured,
  bilibiliCookieState,
  bilibiliCookieStatusText,
  savingBilibiliCookie,
  platformAuthAvailable,
  platformAuthConnecting,
  mediaTools,
  savingMediaTools,
  deepseekConfigured,
  savingDeepseekSettings,
  embeddingConfigured,
  savingEmbeddingSettings,
  testingEmbeddingConnection,
  paddleOcrConfigured,
  savingPaddleOcrSettings,
  runtimeComponents,
  runtimeComponentsLoading
} = defineProps({
  initialSection: { type: String, default: 'overview' },
  themeOptions: { type: Array, default: () => [] },
  selectedThemeOption: { type: Object, required: true },
  availableAiModels: { type: Array, default: () => [] },
  clipboardWatching: Boolean,
  clipboardScanning: Boolean,
  folderImportWatching: Boolean,
  folderImportScanning: Boolean,
  folderImportPath: { type: String, default: '' },
  openclawRunning: Boolean,
  openclawScanning: Boolean,
  openclawStatusText: { type: String, default: '' },
  openclawConnectionItems: { type: Array, default: () => [] },
  openclawStatusTone: { type: String, default: 'is-warning' },
  wechatAccounts: { type: Array, default: () => [] },
  wechatSubscriptions: { type: Array, default: () => [] },
  wechatLoading: Boolean,
  wechatQrLogin: { type: Object, default: () => ({}) },
  wechatQrStarting: Boolean,
  wechatManualConnecting: Boolean,
  wechatSearchResults: { type: Array, default: () => [] },
  wechatSearching: Boolean,
  wechatIntervalOptions: { type: Array, default: () => [] },
  wechatSubscriptionStates: { type: Object, default: () => ({}) },
  wechatSyncingSubscriptionId: { type: String, default: '' },
  wechatContentFilters: { type: Array, default: () => [] },
  wechatReportGroups: { type: Array, default: () => [] },
  wechatGeneratingGroupId: { type: String, default: '' },
  wechatDeletingGroupId: { type: String, default: '' },
  wechatFilterSaving: Boolean,
  wechatAutoSyncSummary: { type: Function, required: true },
  wechatLastSyncSummary: { type: Function, required: true },
  wechatPublishingSettings: { type: Object, default: () => ({ configured: false }) },
  savingWechatPublishingSettings: Boolean,
  wechatQwenCoverSettings: { type: Object, default: () => ({ configured: false, model: 'qwen-image-2.0' }) },
  savingWechatQwenCoverSettings: Boolean,
  testingWechatQwenCoverConnection: Boolean,
  cookieConfigured: Boolean,
  cookieState: { type: String, default: 'unknown' },
  cookieStatusText: { type: String, default: '' },
  cookieChecking: Boolean,
  savingCookie: Boolean,
  bilibiliCookieConfigured: Boolean,
  bilibiliCookieState: { type: String, default: 'unknown' },
  bilibiliCookieStatusText: { type: String, default: '' },
  savingBilibiliCookie: Boolean,
  platformAuthAvailable: Boolean,
  platformAuthConnecting: { type: String, default: '' },
  mediaTools: { type: Object, default: () => ({}) },
  savingMediaTools: Boolean,
  deepseekConfigured: Boolean,
  savingDeepseekSettings: Boolean,
  embeddingConfigured: Boolean,
  savingEmbeddingSettings: Boolean,
  testingEmbeddingConnection: Boolean,
  paddleOcrConfigured: Boolean,
  savingPaddleOcrSettings: Boolean,
  runtimeComponents: { type: Object, default: () => ({}) },
  runtimeComponentsLoading: Boolean
})

const embeddingModelOptions = [
  { label: 'qwen3.7-text-embedding', value: 'qwen3.7-text-embedding' },
  { label: 'text-embedding-v4', value: 'text-embedding-v4' },
  { label: 'text-embedding-v3', value: 'text-embedding-v3' }
]

const visualModelOptions = [
  { label: 'qwen-image-2.0', value: 'qwen-image-2.0' },
  { label: 'qwen-image-2.0-pro', value: 'qwen-image-2.0-pro' },
  { label: 'qwen-image-2.0-pro-2026-06-22', value: 'qwen-image-2.0-pro-2026-06-22' }
]

const paddleOcrModelOptions = [
  { label: 'PaddleOCR-VL-1.6', value: 'PaddleOCR-VL-1.6' },
  { label: 'PP-OCRv6', value: 'PP-OCRv6' }
]

const aiModelOptions = computed(() => (
  (availableAiModels || [])
    .map((option) => ({
      label: String(option?.label || option?.value || option || ''),
      value: String(option?.value || option || '')
    }))
    .filter((option) => option.value)
))

const emit = defineEmits([
  'library-changed',
  'processing-started',
  'save-obsidian',
  'choose-obsidian-folder',
  'choose-export-folder',
  'toggle-clipboard',
  'choose-folder-import',
  'toggle-folder-import',
  'start-openclaw',
  'load-wechat',
  'start-wechat-qr',
  'reauthorize-account',
  'connect-wechat-manually',
  'delete-wechat-account',
  'transfer-account-subscriptions',
  'search-wechat',
  'subscribe-wechat',
  'update-wechat-subscription',
  'sync-wechat-subscription',
  'delete-wechat-subscription',
  'create-wechat-filter',
  'delete-wechat-filter',
  'create-wechat-report-group',
  'delete-wechat-report-group',
  'generate-wechat-report',
  'copy-wechat-rss',
  'export-wechat-subscriptions',
  'save-wechat-publishing-settings',
  'save-wechat-qwen-cover-settings',
  'test-wechat-qwen-cover-connection',
  'open-wechat-manager',
  'save-cookie',
  'save-bilibili-cookie',
  'connect-platform-auth',
  'disconnect-platform-auth',
  'check-platform-auth',
  'save-media-tools',
  'choose-media-tool',
  'save-deepseek-settings',
  'text-model-options-updated',
  'save-embedding-settings',
  'test-embedding-connection',
  'save-paddle-ocr-settings',
  'save-manual-collection-settings',
  'save-video-download-settings',
  'load-runtime-components',
  'install-browser',
  'download-asr-model',
  'delete-asr-model'
])

const toolsReady = computed(() => Boolean(mediaTools.ffmpeg_path?.available && mediaTools.yt_dlp_path?.available))
const settingsSection = ref('appearance')
const builtInTextPricingModels = [
  { key: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { key: 'deepseek-v4-pro', label: 'deepseek-v4-pro' }
]
const selectedTextModelName = computed(() => {
  const configured = String(selectedAiModel.value || 'deepseek-v4-flash:enabled').trim()
  const withoutThinking = configured.replace(/:(?:enabled|disabled)$/u, '')
  return withoutThinking.includes('::') ? '' : withoutThinking || 'deepseek-v4-flash'
})
const textPricingModels = computed(() => {
  const selected = selectedTextModelName.value
  return !selected || builtInTextPricingModels.some((model) => model.key === selected)
    ? builtInTextPricingModels
    : [...builtInTextPricingModels, { key: selected, label: selected }]
})

function ensureTextModelPricing() {
  const current = deepseekPricing.value || {}
  const missing = textPricingModels.value.filter((model) => !current[model.key])
  if (!missing.length) return
  deepseekPricing.value = {
    ...current,
    ...Object.fromEntries(missing.map((model) => [model.key, { input_cache_hit: 0, input_cache_miss: 0, output: 0 }]))
  }
}

watch([selectedTextModelName, deepseekPricing], ensureTextModelPricing, { immediate: true })
const FAVORITE_API = `${API}/favorite-sources`
const XIAOHONGSHU_COOKIE_API = `${API}/xiaohongshu-cookie`
const EMBEDDING_SECRET_REVEAL_API = `${API}/llm-settings/campus-embedding/reveal`
const PADDLE_OCR_SECRET_REVEAL_API = `${API}/paddle-ocr-settings/reveal`
const VISUAL_MODEL_SECRET_REVEAL_API = `${API}/wechat-publishing/cover-settings/reveal`
const {
  telemetryEnabled, telemetryPendingEvents, telemetrySaving,
  telemetryStatusLoading, telemetryStatusLoaded, telemetryStatusError,
  loadTelemetryStatus, saveTelemetry,
} = useTelemetrySettingsController({
  notifySuccess: (message) => ElMessage.success(message),
  notifyError: (message) => ElMessage.error(message),
})
const favoriteSources = ref([])
const favoriteSourcesLoading = ref(false)
const favoriteBusyId = ref('')
const enablingDouyinFavorites = ref(false)
const addingBilibiliFavorite = ref(false)
const bilibiliFavoriteUrl = ref('')
const bilibiliFavoriteAutoAnalyze = ref(true)
const xiaohongshuCookieInput = ref('')
const xiaohongshuCookieConfigured = ref(false)
const xiaohongshuCookieState = ref('loading')
const xiaohongshuCookieStatusText = ref('正在读取小红书登录态')
const xiaohongshuCapabilities = ref({})
const xiaohongshuCredentialStorageAvailable = computed(() => xiaohongshuCapabilities.value.credential_storage?.available !== false)
const xiaohongshuSessionProbeAvailable = computed(() => Boolean(xiaohongshuCapabilities.value.session_probe?.available))
const xiaohongshuNoteCaptureAvailable = computed(() => Boolean(xiaohongshuCapabilities.value.note_capture?.available))
const xiaohongshuFavoritesAvailable = computed(() => Boolean(xiaohongshuCapabilities.value.favorites_sync?.available))
const xiaohongshuNoteCaptureReason = computed(() => xiaohongshuCapabilities.value.note_capture?.reason || '小红书单篇图文读取暂不可用；已缓存资料仍可阅读')
const savingXiaohongshuCookie = ref(false)
const xiaohongshuAuthConnecting = ref(false)
const syncingXiaohongshuFavorites = ref(false)
const xiaohongshuFavoriteSource = ref(null)
const wechatCoolingAccountCount = computed(() => wechatAccounts.filter((account) => (
  account.status === 'active'
  && Number.isFinite(Date.parse(account.rate_limited_until || ''))
  && Date.parse(account.rate_limited_until) > Date.now()
)).length)
const wechatReauthorizationCount = computed(() => wechatAccounts.filter((account) => account.status === 'requires_reauth').length)
const wechatAccountStatusSummary = computed(() => {
  if (!wechatAccounts.length) return '尚未授权账号'
  if (wechatReauthorizationCount.value) return `${wechatReauthorizationCount.value} 个账号需要重新授权`
  if (wechatCoolingAccountCount.value) return `${wechatCoolingAccountCount.value} 个账号频控冷却中`
  return `${wechatAccounts.length} 个账号已授权`
})
const wechatAccountStatusTone = computed(() => (
  !wechatAccounts.length
    ? 'is-idle'
    : (wechatReauthorizationCount.value || wechatCoolingAccountCount.value ? 'is-warning' : 'is-active')
))
const douyinFavoriteSource = computed(() => favoriteSources.value.find((source) => source.provider === 'douyin'))
const settingsNavigationGroups = computed(() => [
  {
    label: '工作区',
    items: [
      { value: 'appearance', label: '外观', icon: paintPaletteIcon },
      { value: 'privacy', label: '隐私与诊断', icon: linkIcon },
    ],
  },
  {
    label: '处理',
    items: [
      { value: 'local', label: '本机处理', icon: keyIcon, badge: toolsReady.value ? '' : '!' },
      { value: 'ai', label: 'AI 服务', icon: appleIntelligenceIcon, badge: deepseekConfigured ? '' : '!' },
    ],
  },
  {
    label: '来源与数据',
    items: [
      { value: 'wechat', label: '微信公众号', icon: wechatIcon, badge: wechatAccounts.length ? '' : '!' },
      { value: 'storage', label: '存储', icon: linkIcon },
    ],
  },
  {
    label: '连接与下载',
    items: [
      { value: 'connections', label: '连接', icon: linkIcon },
      { value: 'credentials', label: '下载凭据', icon: keyIcon },
    ],
  },
])
const settingsNavigation = computed(() => settingsNavigationGroups.value.flatMap((group) => group.items))

const selectedRuntimeModels = computed(() => {
  const backend = runtimeComponents.preferred_asr_backend || 'mlx'
  return (runtimeComponents.models || []).filter((item) => item.model === 'small' && item.backend === backend)
})

const runtimeBackendName = computed(() => (
  (runtimeComponents.preferred_asr_backend || 'mlx') === 'mlx' ? 'MLX（Apple Silicon）' : 'Faster-Whisper'
))

const installedRuntimeModels = computed(() => (
  [...(runtimeComponents.models || [])]
    .filter((model) => model.available)
    .sort((left, right) => {
      if (left.preferred !== right.preferred) return left.preferred ? -1 : 1
      return Number(right.installed_bytes || 0) - Number(left.installed_bytes || 0)
    })
))

function isCurrentRuntimeModel(model) {
  return selectedRuntimeModels.value.some((selected) => (
    selected.model === model.model && selected.backend === model.backend
  ))
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`
}

function componentStatusText(component, readyText, missingText) {
  if (component?.available) return readyText
  if (component?.state !== 'downloading') return missingText
  const downloaded = Number(component.job?.downloaded_bytes || 0)
  const total = Number(component.job?.total_bytes || 0)
  if (downloaded > 0 && total > 0) {
    const percent = Math.min(99, Math.floor(downloaded / total * 100))
    return `下载中 ${percent}% · ${formatBytes(downloaded)} / ${formatBytes(total)}`
  }
  return component?.model ? '正在准备下载…' : '下载中'
}

function modelFailureDetail(model) {
  if (model?.state !== 'failed') return ''
  const detail = String(model?.detail || '').trim()
  return detail && detail !== '模型下载失败' ? detail : ''
}

function credentialPlaceholder(configured, credentialName) {
  return configured ? '••••••••••••' : `输入 ${credentialName}`
}

async function revealStoredSecret(endpoint, credentialName) {
  try {
    const response = await axios.post(endpoint, {}, { timeout: 5000 })
    const secret = String(response.data?.secret || '')
    if (!secret) {
      ElMessage.warning(`${credentialName} 尚未保存`)
      return ''
    }
    return secret
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, `无法显示 ${credentialName}`))
    return ''
  }
}

async function toggleEmbeddingApiKeyVisibility() {
  if (showEmbeddingApiKey.value) {
    showEmbeddingApiKey.value = false
    return
  }
  if (!embeddingApiKey.value && embeddingConfigured) {
    const secret = await revealStoredSecret(EMBEDDING_SECRET_REVEAL_API, 'Embedding API Key')
    if (!secret) return
    embeddingApiKey.value = secret
  }
  showEmbeddingApiKey.value = true
}

async function toggleWechatQwenCoverApiKeyVisibility() {
  if (showWechatQwenCoverApiKey.value) {
    showWechatQwenCoverApiKey.value = false
    return
  }
  if (!wechatQwenCoverApiKey.value && wechatQwenCoverSettings.configured) {
    const secret = await revealStoredSecret(VISUAL_MODEL_SECRET_REVEAL_API, '图像模型 API Key')
    if (!secret) return
    wechatQwenCoverApiKey.value = secret
  }
  showWechatQwenCoverApiKey.value = true
}

async function togglePaddleOcrAccessTokenVisibility() {
  if (showPaddleOcrAccessToken.value) {
    showPaddleOcrAccessToken.value = false
    return
  }
  if (!paddleOcrAccessToken.value && paddleOcrConfigured) {
    const secret = await revealStoredSecret(PADDLE_OCR_SECRET_REVEAL_API, 'PaddleOCR Access Token')
    if (!secret) return
    paddleOcrAccessToken.value = secret
  }
  showPaddleOcrAccessToken.value = true
}

function favoriteErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function favoriteStatusText(source) {
  if (!source.enabled) return '已暂停自动检查'
  if (source.last_error) return '上次同步失败'
  if (!source.last_sync_at) return '等待首次同步'
  return Number(source.last_created_count || 0) > 0 ? `上次新增 ${source.last_created_count} 条` : '上次无新增'
}

function favoriteStatusClass(source) {
  if (!source.enabled) return 'is-muted'
  return source.last_error ? 'is-error' : 'is-valid'
}

async function loadFavoriteSources() {
  favoriteSourcesLoading.value = true
  try {
    const response = await axios.get(FAVORITE_API, { timeout: 15000 })
    favoriteSources.value = Array.isArray(response.data) ? response.data : []
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '无法读取个人收藏同步状态'))
  } finally {
    favoriteSourcesLoading.value = false
  }
}

async function loadXiaohongshuCookieStatus(refresh = false) {
  xiaohongshuCookieState.value = 'loading'
  try {
    const response = await axios.get(XIAOHONGSHU_COOKIE_API, { params: refresh ? { refresh: true } : undefined, timeout: refresh ? 35000 : 5000 })
    xiaohongshuCookieConfigured.value = Boolean(response.data?.configured)
    const fallbackAvailable = response.data?.collector_available !== false
    xiaohongshuCapabilities.value = response.data?.capabilities || {
      credential_storage: { available: true },
      session_probe: { available: fallbackAvailable, reason: response.data?.collector_reason || '' },
      note_capture: { available: fallbackAvailable, reason: response.data?.collector_reason || '' },
      favorites_sync: { available: false, reason: '个人收藏同步暂未开放' },
    }
    xiaohongshuCookieState.value = response.data?.state || (xiaohongshuCookieConfigured.value ? 'unknown' : 'missing')
    xiaohongshuCookieStatusText.value = response.data?.detail || response.data?.label || (xiaohongshuCookieConfigured.value ? '小红书登录态已保存' : '小红书登录态未连接')
  } catch (error) {
    xiaohongshuCookieConfigured.value = false
    xiaohongshuCookieState.value = 'unknown'
    xiaohongshuCookieStatusText.value = error.response?.data?.detail || error.message || '小红书登录态状态读取失败'
  }
}

async function saveXiaohongshuCookie() {
  if (!xiaohongshuCredentialStorageAvailable.value) return
  savingXiaohongshuCookie.value = true
  try {
    const response = await axios.post(XIAOHONGSHU_COOKIE_API, { cookie: xiaohongshuCookieInput.value }, { timeout: 10000 })
    if (!response.data?.success) {
      ElMessage.error(response.data?.message || '小红书 Cookie 保存失败')
      return
    }
    xiaohongshuCookieInput.value = ''
    await loadXiaohongshuCookieStatus(true)
    if (xiaohongshuCookieState.value === 'valid') {
      ElMessage.success('小红书 Cookie 已保存并验证可用')
    } else if (xiaohongshuCookieState.value === 'invalid') {
      ElMessage.error(`小红书 Cookie 未通过验证：${xiaohongshuCookieStatusText.value}`)
    } else {
      ElMessage.info('小红书 Cookie 已保存，等待平台确认')
    }
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '小红书 Cookie 保存失败'))
  } finally {
    savingXiaohongshuCookie.value = false
  }
}

async function connectXiaohongshuAuth() {
  if (!xiaohongshuSessionProbeAvailable.value) return
  const connect = window.knowledgeHubDesktop?.connectPlatformAuth
  if (!connect) {
    ElMessage.warning('请使用桌面版在应用内登录；浏览器版仍可手动粘贴 Cookie。')
    return
  }
  xiaohongshuAuthConnecting.value = true
  try {
    const status = await connect('xiaohongshu')
    await loadXiaohongshuCookieStatus(true)
    if (status?.state === 'valid' || xiaohongshuCookieState.value === 'valid') {
      ElMessage.success('小红书登录态已连接并验证可用')
    } else if (status?.state === 'invalid' || xiaohongshuCookieState.value === 'invalid') {
      ElMessage.error(xiaohongshuCookieStatusText.value || '小红书登录态未通过平台验证，请重新登录')
    } else if (status?.configured || xiaohongshuCookieConfigured.value) {
      ElMessage.info('小红书登录态已保存，正在等待平台验证')
    } else {
      ElMessage.info('登录窗口已关闭；尚未检测到可用登录态。')
    }
  } catch (error) {
    ElMessage.error(error?.message || '小红书登录状态保存失败')
  } finally {
    xiaohongshuAuthConnecting.value = false
  }
}

async function disconnectXiaohongshuAuth() {
  const disconnect = window.knowledgeHubDesktop?.disconnectPlatformAuth
  if (!disconnect) return
  const confirmed = await requestDestructiveConfirmation({
    title: '断开小红书登录态',
    message: '这会清除本应用保存的小红书登录会话；之后需要重新登录才能主动导入受限单篇图文。已缓存资料不会删除。',
    confirmLabel: '断开登录态',
  })
  if (!confirmed) return
  xiaohongshuAuthConnecting.value = true
  try {
    await disconnect('xiaohongshu')
    await loadXiaohongshuCookieStatus()
    ElMessage.success('小红书登录态已断开')
  } catch (error) {
    ElMessage.error(error?.message || '断开小红书登录态失败')
  } finally {
    xiaohongshuAuthConnecting.value = false
  }
}

async function syncXiaohongshuFavorites() {
  if (!xiaohongshuFavoritesAvailable.value) return
  syncingXiaohongshuFavorites.value = true
  try {
    const task = await enqueueSourceSyncTask({ kind: 'favorite_xiaohongshu', source_title: '小红书个人收藏', source_id: xiaohongshuFavoriteSource.value?.id, auto_analyze: true })
    ElMessage.success('已开始检查小红书个人收藏')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`小红书收藏检查完成：新增 ${result.created_count || 0} 篇`)
        await loadXiaohongshuFavoriteSource()
        emitFavoriteProcessing(result)
      },
      onFailed: (message) => ElMessage.error(message || '小红书收藏同步失败'),
    })
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '小红书收藏同步失败'))
  } finally {
    syncingXiaohongshuFavorites.value = false
  }
}

async function loadXiaohongshuFavoriteSource() {
  try {
    const response = await axios.get(`${FAVORITE_API}/xiaohongshu`, { timeout: 5000 })
    xiaohongshuFavoriteSource.value = response.data || null
  } catch {
    xiaohongshuFavoriteSource.value = null
  }
}

async function updateXiaohongshuFavorite(changes) {
  syncingXiaohongshuFavorites.value = true
  try {
    const response = await axios.patch(`${FAVORITE_API}/xiaohongshu`, changes, { timeout: 10000 })
    xiaohongshuFavoriteSource.value = response.data || null
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '小红书收藏设置保存失败'))
  } finally {
    syncingXiaohongshuFavorites.value = false
  }
}

async function enableDouyinFavorites() {
  const current = douyinFavoriteSource.value
  if (current) return syncFavorite(current)
  enablingDouyinFavorites.value = true
  try {
    const task = await enqueueSourceSyncTask({ kind: 'favorite_douyin', source_title: '抖音个人收藏', auto_analyze: true })
    ElMessage.success('已开始检查抖音个人收藏')
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`抖音个人收藏检查完成：新增 ${result.created_count || 0} 条`)
        await loadFavoriteSources()
        emitFavoriteProcessing(result)
      },
      onFailed: (message) => ElMessage.error(message || '抖音个人收藏启用失败'),
    })
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '抖音个人收藏启用失败'))
  } finally {
    enablingDouyinFavorites.value = false
  }
}

async function addBilibiliFavorite() {
  if (!bilibiliFavoriteUrl.value) return
  addingBilibiliFavorite.value = true
  try {
    const task = await enqueueSourceSyncTask({
      kind: 'favorite_bilibili',
      source_title: 'B站个人收藏',
      source_url_input: bilibiliFavoriteUrl.value,
      auto_analyze: bilibiliFavoriteAutoAnalyze.value,
    })
    ElMessage.success('已开始读取 B 站收藏夹')
    bilibiliFavoriteUrl.value = ''
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`B站收藏夹检查完成：新增 ${result.created_count || 0} 条${bilibiliFavoriteAutoAnalyze.value ? '，已进入处理队列' : ''}`)
        await loadFavoriteSources()
        emitFavoriteProcessing(result)
      },
      onFailed: (message) => ElMessage.error(message || 'B站收藏夹添加失败'),
    })
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, 'B站收藏夹添加失败'))
  } finally {
    addingBilibiliFavorite.value = false
  }
}

async function syncFavorite(source) {
  favoriteBusyId.value = source.id
  try {
    const task = await enqueueSourceSyncTask({ kind: 'favorite_saved', source_title: source.title || '个人收藏', source_id: source.id })
    ElMessage.success(`已开始检查${source.title || '个人收藏'}`)
    observeSourceSyncTask(task.task_id, {
      onSucceeded: async (result) => {
        ElMessage.success(`${source.title}同步完成：新增 ${result.created_count || 0} 条`)
        await loadFavoriteSources()
        emitFavoriteProcessing(result)
      },
      onFailed: (message) => ElMessage.error(message || '个人收藏同步失败'),
    })
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '个人收藏同步失败'))
  } finally {
    favoriteBusyId.value = ''
  }
}

async function processPendingFavorite(source) {
  favoriteBusyId.value = source.id
  try {
    const response = await axios.post(`${FAVORITE_API}/${source.id}/process-pending`, {}, { timeout: 15000 })
    const queuedCount = Number(response.data?.queued_count || 0)
    ElMessage.success(queuedCount ? `${source.title}：已将 ${queuedCount} 条已有内容加入处理队列` : `${source.title}：没有需要补处理的内容`)
    await loadFavoriteSources()
    emitFavoriteProcessing(response.data)
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '补处理已有收藏失败'))
  } finally {
    favoriteBusyId.value = ''
  }
}

function emitFavoriteProcessing(result) {
  emit('library-changed')
  const taskIds = Array.isArray(result?.task_ids) ? result.task_ids : []
  if (!taskIds.length) return
  emit('processing-started', {
    taskIds,
    contentItemIds: Array.isArray(result?.content_item_ids) ? result.content_item_ids : [],
  })
}

async function updateFavorite(source, changes) {
  favoriteBusyId.value = source.id
  try {
    await axios.patch(`${FAVORITE_API}/${source.id}`, changes, { timeout: 15000 })
    await loadFavoriteSources()
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '个人收藏设置保存失败'))
  } finally {
    favoriteBusyId.value = ''
  }
}

async function deleteFavorite(source) {
  const confirmed = await requestDestructiveConfirmation({
    title: '移除个人收藏',
    message: `移除“${source.title}”的自动同步？已入库内容会保留。`,
    confirmLabel: '移除',
  })
  if (!confirmed) return
  favoriteBusyId.value = source.id
  try {
    await axios.delete(`${FAVORITE_API}/${source.id}`, { timeout: 15000 })
    await loadFavoriteSources()
    ElMessage.success('已移除个人收藏同步，已入库内容仍保留')
  } catch (error) {
    ElMessage.error(favoriteErrorMessage(error, '移除个人收藏失败'))
  } finally {
    favoriteBusyId.value = ''
  }
}

watch(modelValue, (opened) => {
  if (opened) {
    loadXiaohongshuCookieStatus()
    void loadTelemetryStatus()
  }
})

watch(modelValue, (isOpen) => {
  if (isOpen) settingsSection.value = settingsNavigation.value.some((item) => item.value === initialSection)
    ? initialSection
    : 'appearance'
})
</script>

<style scoped src="../styles/settings.css"></style>
