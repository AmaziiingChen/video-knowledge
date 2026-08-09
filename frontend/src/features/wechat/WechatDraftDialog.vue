<template>
  <el-dialog
    v-model="dialogVisible"
    class="wechat-draft-dialog"
    width="min(560px, calc(100vw - 40px))"
    align-center
    :show-close="true"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
  >
    <template #header>
      <div class="wechat-draft-dialog-title">
        <strong>存入公众号草稿</strong>
        <span>仅保存到 {{ displayName || '订阅号' }} 草稿箱，不会自动发表</span>
      </div>
    </template>

    <div v-loading="loadingDefaults" class="wechat-draft-dialog-form">
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="draftTitle" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="摘要（选填）">
          <el-input
            :model-value="digest"
            type="textarea"
            :rows="3"
            resize="none"
            @update:model-value="$emit('update:digest', $event)"
          />
          <small class="wechat-draft-dialog-hint">微信公众号按字节限制摘要；中文约可输入 40 个字。</small>
        </el-form-item>
        <el-form-item label="作者（选填）">
          <el-input v-model="draftAuthor" maxlength="64" />
        </el-form-item>
        <el-form-item label="文章封面">
          <div class="wechat-draft-cover">
            <div class="wechat-draft-cover-frame">
              <img v-if="coverUrl" :src="coverUrl" :alt="`${title || '公众号文章'}封面`" />
              <span v-else>尚未生成封面</span>
            </div>
            <div class="wechat-draft-cover-action">
              <small v-if="coverUrl">已保存到本机；存入草稿时将直接复用这张封面。</small>
              <small v-else-if="coverAvailable">请先从报告右上角“三点”菜单生成并确认封面。</small>
              <small v-else>请先在“AI 服务”设置中配置图像模型，再从报告右上角生成封面。</small>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <section
        v-if="ipPreflight"
        class="wechat-draft-ip-preflight"
        :class="`is-${ipPreflight.status || 'unverified'}`"
        aria-live="polite"
      >
        <div>
          <strong>公众号 IP 预检</strong>
          <span>{{ ipPreflight.current_ip ? `当前 ${ipPreflight.current_ip}` : '暂未获取 IP' }}</span>
        </div>
        <p>{{ ipPreflight.message }}</p>
        <small v-if="ipPreflight.last_verified_ip">上次公众号验证：{{ ipPreflight.last_verified_ip }}</small>
        <el-button
          v-if="['changed', 'verification_failed'].includes(ipPreflight.status)"
          size="small"
          :loading="verifyingIp"
          @click="$emit('verify-ip')"
        >已加入白名单，重新验证</el-button>
      </section>

      <details v-if="previewHtml" class="wechat-draft-preview">
        <summary>查看固定版式预览</summary>
        <p>存入草稿箱时将使用此版式；正文引用可跳转至文末来源和原始文章。</p>
        <iframe title="公众号报告排版预览" :srcdoc="previewHtml" />
      </details>

      <section v-if="taskRunning" class="wechat-draft-task-state" aria-live="polite">
        <div>
          <strong>{{ taskStageLabel(task.stage) }}</strong>
          <span>{{ Math.round(Number(task.progress || 0)) }}%</span>
        </div>
        <el-progress :percentage="Math.round(Number(task.progress || 0))" :show-text="false" :stroke-width="5" />
        <small>可关闭此窗口，任务会继续在后台完成。</small>
      </section>
      <section v-else-if="task?.status === 'failed'" class="wechat-draft-task-state is-failed" role="alert">
        <strong>存入草稿箱未完成</strong>
        <small>{{ task.error || '任务执行失败，请检查网络后重试。' }}</small>
      </section>

      <div v-if="latestPublication?.status === 'draft_created'" class="wechat-draft-publication-state">
        <span>草稿已创建，等待公众号后台发表。</span>
        <el-button size="small" @click="$emit('confirm-publication')">已发表，写入历史档案</el-button>
      </div>
      <div v-else-if="latestPublication?.status === 'published'" class="wechat-draft-publication-state is-published">
        <span>该报告已写入历史档案。</span>
      </div>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">关闭</el-button>
      <el-button
        type="primary"
        :loading="creating"
        :disabled="submitDisabled"
        @click="$emit('submit')"
      >{{ submitLabel }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import {
  wechatDraftSubmitState,
  wechatDraftTaskStageLabel,
} from './wechatDraftPresentation.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  displayName: { type: String, default: '' },
  loadingDefaults: { type: Boolean, default: false },
  title: { type: String, default: '' },
  digest: { type: String, default: '' },
  author: { type: String, default: '' },
  coverUrl: { type: String, default: '' },
  coverAvailable: { type: Boolean, default: false },
  ipPreflight: { type: Object, default: null },
  verifyingIp: { type: Boolean, default: false },
  previewHtml: { type: String, default: '' },
  task: { type: Object, default: null },
  latestPublication: { type: Object, default: null },
  creating: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:visible',
  'update:title',
  'update:digest',
  'update:author',
  'verify-ip',
  'confirm-publication',
  'submit',
])

const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
})
const draftTitle = computed({
  get: () => props.title,
  set: (value) => emit('update:title', value),
})
const draftAuthor = computed({
  get: () => props.author,
  set: (value) => emit('update:author', value),
})
const submitState = computed(() => wechatDraftSubmitState(props))
const taskRunning = computed(() => submitState.value.taskRunning)
const submitDisabled = computed(() => submitState.value.disabled)
const submitLabel = computed(() => submitState.value.label)
const taskStageLabel = wechatDraftTaskStageLabel
</script>

<style scoped>
.wechat-draft-dialog-title {
  display: grid;
  gap: 3px;
}

.wechat-draft-dialog-title strong {
  color: var(--vk-text);
  font-size: 16px;
  font-weight: var(--vk-weight-strong);
}

.wechat-draft-dialog-title span,
.wechat-draft-dialog-hint,
.wechat-draft-cover-action small {
  color: var(--vk-muted);
  font-size: 12px;
}

.wechat-draft-dialog-form {
  min-height: 196px;
}

.wechat-draft-dialog-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.wechat-draft-dialog-hint {
  margin-top: 6px;
  line-height: 1.45;
}

.wechat-draft-cover {
  display: grid;
  width: 100%;
  gap: var(--vk-space-sm);
}

.wechat-draft-cover-frame {
  display: grid;
  width: 100%;
  aspect-ratio: 900 / 383;
  place-items: center;
  overflow: hidden;
  border: 1px solid var(--vk-line);
  border-radius: var(--vk-radius-surface);
  background: var(--vk-bg-center);
  color: var(--vk-muted);
  font-size: 12px;
}

.wechat-draft-cover-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.wechat-draft-cover-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-sm);
}

.wechat-draft-cover-action small {
  line-height: 1.45;
}

.wechat-draft-ip-preflight {
  display: grid;
  gap: 5px;
  margin: 2px 0 var(--vk-space-panel);
  padding: var(--vk-space-sm) var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-accent) 30%, var(--vk-border));
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-accent) 6%, var(--vk-bg-panel));
}

.wechat-draft-ip-preflight > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--vk-space-sm);
}

.wechat-draft-ip-preflight strong,
.wechat-draft-ip-preflight span,
.wechat-draft-ip-preflight p,
.wechat-draft-ip-preflight small {
  font-size: 12px;
  line-height: 1.45;
}

.wechat-draft-ip-preflight span,
.wechat-draft-ip-preflight small,
.wechat-draft-ip-preflight p {
  color: var(--vk-muted);
}

.wechat-draft-ip-preflight p {
  margin: 0;
}

.wechat-draft-ip-preflight.is-changed,
.wechat-draft-ip-preflight.is-verification_failed {
  border-color: color-mix(in srgb, var(--vk-warning) 46%, var(--vk-border));
  background: color-mix(in srgb, var(--vk-warning) 8%, var(--vk-bg-panel));
}

.wechat-draft-ip-preflight :deep(.el-button) {
  justify-self: start;
  margin-top: 2px;
}

.wechat-draft-preview {
  margin-top: 4px;
  border-top: 1px solid var(--vk-line);
  color: var(--vk-muted);
  font-size: 12px;
}

.wechat-draft-preview summary {
  padding: 12px 0 4px;
  color: var(--vk-text);
  cursor: pointer;
  font-weight: var(--vk-weight-medium);
}

.wechat-draft-preview p {
  margin: 4px 0 10px;
  line-height: 1.5;
}

.wechat-draft-preview iframe {
  width: 100%;
  height: 360px;
  border: 1px solid var(--vk-line);
  border-radius: var(--vk-radius-control);
  background: var(--vk-reader-surface);
}

.wechat-draft-task-state {
  display: grid;
  gap: var(--vk-space-xs);
  margin-top: var(--vk-space-panel);
  padding: var(--vk-space-sm) var(--vk-space-control);
  border: 1px solid color-mix(in srgb, var(--vk-accent) 34%, var(--vk-border));
  border-radius: var(--vk-radius-surface);
  background: color-mix(in srgb, var(--vk-accent) 7%, var(--vk-bg-panel));
}

.wechat-draft-task-state > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--vk-space-sm);
  color: var(--vk-text);
  font-size: 12px;
}

.wechat-draft-task-state strong {
  font-weight: var(--vk-weight-medium);
}

.wechat-draft-task-state span,
.wechat-draft-task-state small {
  color: var(--vk-muted);
  font-size: 11px;
  line-height: 1.45;
}

.wechat-draft-task-state.is-failed {
  border-color: color-mix(in srgb, var(--vk-danger) 34%, var(--vk-border));
  background: color-mix(in srgb, var(--vk-danger) 6%, var(--vk-bg-panel));
}

</style>
