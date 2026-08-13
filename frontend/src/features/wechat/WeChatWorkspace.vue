<template>
  <div
    v-loading="loading"
    class="wechat-workspace"
    :class="[`wechat-workspace--${mode}`, { 'is-settings-embedded': embedded }]"
  >
    <div class="wechat-workspace-grid">
      <aside v-if="mode === 'accounts'" class="wechat-credential-rail">
        <section class="wechat-sheet wechat-accounts-sheet">
          <header class="wechat-sheet-head">
            <div>
              <h3>授权账号</h3>
              <p>{{ authorizationAvailable ? '登录态只保存在本机 Keychain，不写入内容库或处理日志。' : '受上游接口限制，新增授权与订阅暂不可用；已有公众号合集、分组和 RSS 保持可读。' }}</p>
            </div>
            <div class="wechat-connect-actions">
              <el-button class="wechat-connect-button" size="small" :loading="qrStarting" :disabled="!authorizationAvailable" :title="authorizationUnavailableMessage" @click="emit('start-qr')">
                扫码连接
              </el-button>
            </div>
          </header>

          <Transition name="wechat-qr-card">
            <div v-if="qrLogin.qr_image_data_url" class="wechat-qr-card">
              <img :src="qrLogin.qr_image_data_url" alt="微信公众平台登录二维码" width="96" height="96" decoding="async">
              <div>
                <strong>{{ qrLogin.message || '请使用微信扫描二维码' }}</strong>
                <p>{{ qrLogin.reauthorize_account_id ? '正在更新原账号的授权，现有订阅不会变化。' : (qrLogin.status === 'scanned' ? '已扫码，请在手机上确认登录。' : '二维码有效期内会自动检查登录结果。') }}</p>
              </div>
            </div>
          </Transition>

          <div v-if="accounts.length" class="wechat-account-list">
            <article
              v-for="account in accounts"
              :key="account.id"
              class="wechat-account-item"
              :class="{ 'is-selected': selectedAccountId === account.id, 'is-error': account.status === 'requires_reauth', 'is-warning': accountRateLimited(account) }"
            >
              <button class="wechat-account-main" type="button" @click="emit('update:selectedAccountId', account.id)">
                <span class="wechat-account-dot" aria-hidden="true"></span>
                <span>
                  <strong>{{ account.display_name }}</strong>
                  <small>{{ accountStateSummary(account) }} · 已关联 {{ Number(account.subscription_count || 0) }} 个公众号</small>
                </span>
              </button>
              <div class="wechat-account-actions">
                <button v-if="account.status === 'requires_reauth'" class="wechat-account-action" type="button" :disabled="!authorizationAvailable" :title="authorizationUnavailableMessage" @click="emit('reauthorize-account', account.id)">重新授权</button>
                <button v-if="Number(account.subscription_count || 0) && selectedAccountId && selectedAccountId !== account.id" class="wechat-account-action" type="button" :disabled="!authorizationAvailable" :title="authorizationUnavailableMessage" @click="requestSubscriptionTransfer(account)">迁移订阅</button>
                <button class="wechat-remove-button" type="button" aria-label="移除授权账号" @click="requestAccountRemoval(account)">移除</button>
              </div>
            </article>
          </div>
          <div v-else class="wechat-empty-account">
            <span>还没有可用账号</span>
            <small>{{ authorizationAvailable ? '先扫码连接，再开始订阅公众号。' : '新增授权目前不可用；已有资料和公众号合集不会受影响。' }}</small>
          </div>

          <details class="wechat-manual-disclosure">
            <summary>无法扫码？使用手动授权</summary>
            <div class="wechat-manual-fields">
              <label class="wechat-field">
                <span>账号显示名称</span>
                <el-input
                  :model-value="accountDisplayName"
                  name="wechat-account-name"
                  autocomplete="off"
                  aria-label="账号显示名称"
                  placeholder="例如：运营号…"
                  :disabled="!authorizationAvailable"
                  @update:model-value="emit('update:accountDisplayName', $event)"
                />
              </label>
              <label class="wechat-field">
                <span>微信公众平台 token</span>
                <el-input
                  :model-value="manualToken"
                  name="wechat-platform-token"
                  autocomplete="off"
                  spellcheck="false"
                  aria-label="微信公众平台 token"
                  placeholder="粘贴 token…"
                  :disabled="!authorizationAvailable"
                  @update:model-value="emit('update:manualToken', $event)"
                />
              </label>
              <label class="wechat-field">
                <span>微信公众平台 Cookie</span>
                <el-input
                  :model-value="manualCookie"
                  type="textarea"
                  name="wechat-platform-cookie"
                  autocomplete="off"
                  spellcheck="false"
                  aria-label="微信公众平台 Cookie"
                  :rows="3"
                  placeholder="粘贴完整 Cookie…"
                  :disabled="!authorizationAvailable"
                  @update:model-value="emit('update:manualCookie', $event)"
                />
              </label>
              <el-button class="wechat-manual-submit" size="small" :loading="manualConnecting" :disabled="!authorizationAvailable" :title="authorizationUnavailableMessage" @click="emit('connect-manual')">
                连接账号
              </el-button>
            </div>
          </details>
        </section>

        <section class="wechat-sheet wechat-publishing-sheet" aria-labelledby="wechat-publishing-title">
          <header class="wechat-sheet-head">
            <div>
              <h3 id="wechat-publishing-title">报告发布到订阅号</h3>
              <p>报告只会存入公众号草稿箱；最终发表仍需在公众号后台人工确认。</p>
            </div>
            <span class="wechat-publishing-status" :class="publishingSettings.configured ? 'is-configured' : 'is-idle'">
              {{ publishingSettings.configured ? '已配置' : '未配置' }}
            </span>
          </header>
          <div class="wechat-publishing-form">
            <label class="wechat-field">
              <span>订阅号名称</span>
              <el-input
                :model-value="publishingDisplayName"
                name="wechat-publishing-display-name"
                autocomplete="organization"
                aria-label="订阅号名称"
                placeholder="例如：每日简报…"
                @update:model-value="emit('update:publishingDisplayName', $event)"
              />
            </label>
            <label class="wechat-field">
              <span>AppID</span>
              <el-input
                :model-value="publishingAppId"
                name="wechat-publishing-app-id"
                autocomplete="off"
                spellcheck="false"
                aria-label="订阅号 AppID"
                :placeholder="publishingSettings.app_id_masked || '公众号后台 → 基本配置'"
                @update:model-value="emit('update:publishingAppId', $event)"
              />
            </label>
            <label class="wechat-field wechat-publishing-secret">
              <span>AppSecret</span>
              <el-input
                :model-value="publishingAppSecret"
                type="password"
                name="wechat-publishing-app-secret"
                autocomplete="off"
                spellcheck="false"
                show-password
                aria-label="订阅号 AppSecret"
                placeholder="仅保存到本机 Keychain"
                @update:model-value="emit('update:publishingAppSecret', $event)"
              />
            </label>
            <label class="wechat-field">
              <span>公开网站地址</span>
              <el-input
                :model-value="publicSiteBaseUrl"
                name="wechat-public-site-base-url"
                autocomplete="url"
                spellcheck="false"
                aria-label="公开网站地址"
                placeholder="https://report.example.com"
                @update:model-value="emit('update:publicSiteBaseUrl', $event)"
              />
            </label>
            <div class="wechat-publishing-action">
              <small v-if="publishingSettings.last_error">{{ publishingSettings.last_error }}</small>
              <small v-else>GitHub Pages 已连接时，创建草稿前会自动构建、上传并校验“阅读原文”链接。</small>
              <el-button
                size="small"
                type="primary"
                :loading="savingPublishingSettings"
                :disabled="!publishingAppId.trim() || !publishingAppSecret.trim()"
                @click="emit('save-publishing-settings')"
              >保存发布账号</el-button>
            </div>
          </div>
        </section>

      </aside>

      <div v-if="mode !== 'accounts'" class="wechat-workspace-content">
        <section class="wechat-sheet wechat-discovery-sheet">
          <header class="wechat-sheet-head wechat-discovery-head">
            <div>
              <h3>新增订阅</h3>
              <p>搜索公众号，订阅后会检查最近文章并自动分析新增内容。</p>
            </div>
            <div v-if="selectedAccount && accounts.length === 1" class="wechat-discovery-account">
              <span>使用账号</span>
              <i aria-hidden="true"></i>
              <strong>{{ selectedAccount.display_name }}</strong>
            </div>
          </header>

          <div class="wechat-discovery-form">
            <div class="wechat-search-composer">
              <label class="wechat-field wechat-search-field">
                <span>搜索公众号</span>
                <el-input
                  :model-value="searchQuery"
                  name="wechat-discovery-search"
                  autocomplete="off"
                  aria-label="搜索公众号"
                  placeholder="输入公众号名称或关键词，例如：晚点 LatePost…"
                  @keyup.enter="emit('search')"
                  @update:model-value="emit('update:searchQuery', $event)"
                />
              </label>
              <el-button
                class="wechat-search-button"
                type="primary"
                :disabled="!selectedAccountId || !searchQuery.trim() || selectedAccountRateLimited"
                :title="selectedAccountRateLimited ? '微信正在频控冷却，恢复后可继续搜索' : '搜索公众号'"
                :loading="searching"
                @click="emit('search')"
              >
                搜索
              </el-button>
            </div>

            <label v-if="accounts.length > 1" class="wechat-field wechat-account-select-field">
              <span>使用授权账号</span>
              <el-select
                :model-value="selectedAccountId"
                placeholder="选择一个账号"
                @update:model-value="emit('update:selectedAccountId', $event)"
              >
                <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
              </el-select>
            </label>
          </div>

          <div v-if="searchResults.length" class="wechat-search-results" aria-live="polite">
            <article v-for="item in searchResults" :key="item.fakeid" class="wechat-search-result">
              <img v-if="item.avatar_url" :src="item.avatar_url" alt="" width="58" height="58" loading="lazy" decoding="async">
              <div class="wechat-search-result-copy">
                <strong>{{ item.name }}</strong>
                <span>{{ item.description || item.fakeid }}</span>
              </div>
              <el-button
                size="small"
                :type="searchResultState(item) === 'subscribed' ? 'default' : 'primary'"
                :loading="['subscribing', 'checking'].includes(searchResultState(item))"
                :disabled="searchResultState(item) === 'subscribed'"
                @click="emit('subscribe', item)"
              >
                {{ searchResultActionLabel(item) }}
              </el-button>
            </article>
          </div>
        </section>

        <section class="wechat-sheet wechat-feed-sheet">
          <header class="wechat-sheet-head wechat-feed-head">
            <div>
              <h3>已订阅公众号</h3>
              <p>开启后按频率检查；手动同步会立即检查一次。</p>
            </div>
            <div v-if="subscriptions.length" class="wechat-feed-export-actions">
              <el-button size="small" text @click="emit('copy-rss')">复制聚合 RSS</el-button>
              <el-button size="small" text @click="emit('export-subscriptions')">导出订阅</el-button>
            </div>
          </header>

          <div v-if="!subscriptions.length" class="wechat-empty-feed">
            <strong>还没有公众号订阅</strong>
            <p>先在上方搜索并订阅一个内容源。</p>
          </div>
          <div v-else class="wechat-feed-list">
            <article v-for="subscription in subscriptions" :key="subscription.id" class="wechat-feed-item">
              <img v-if="subscription.avatar_url" :src="subscription.avatar_url" alt="" width="58" height="58" loading="lazy" decoding="async">
              <div class="wechat-feed-copy">
                <div class="wechat-feed-title-line">
                  <strong>{{ subscription.mp_name }}</strong>
                  <span class="wechat-feed-status" :class="{ 'is-paused': !subscription.enabled, 'is-warning': subscription.account_status !== 'active' || subscriptionRateLimited(subscription) }">
                    {{ subscriptionStatusLabel(subscription) }}
                  </span>
                </div>
                <span>{{ autoSyncSummary(subscription) }} · {{ subscription.auto_process ? '新文章自动分析' : '新文章仅入库' }}</span>
                <small>{{ lastSyncSummary(subscription) }}</small>
                <small v-if="subscription.last_error" class="wechat-feed-error">{{ subscription.last_error }}</small>
              </div>
              <div class="wechat-feed-controls">
                <div class="wechat-feed-schedule-controls">
                  <el-switch
                    :model-value="subscription.enabled"
                    aria-label="启用自动检查"
                    @update:model-value="emit('update-subscription', subscription, { enabled: $event })"
                  />
                  <el-select
                    class="wechat-feed-interval"
                    :model-value="subscription.sync_interval_minutes"
                    size="small"
                    aria-label="自动同步频率"
                    @update:model-value="emit('update-subscription', subscription, { sync_interval_minutes: $event })"
                  >
                    <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
                  </el-select>
                </div>
                <div class="wechat-feed-action-controls">
                  <el-button size="small" text @click="emit('update-subscription', subscription, { auto_process: !subscription.auto_process })">
                    {{ subscription.auto_process ? '改为仅入库' : '开启自动分析' }}
                  </el-button>
                  <el-button size="small" text :loading="syncingSubscriptionId === subscription.id" :disabled="subscriptionRateLimited(subscription)" @click="startSync(subscription, 'latest')">检查最新</el-button>
                  <el-button size="small" text :disabled="subscriptionRateLimited(subscription)" @click="startSync(subscription, 'history')">回溯历史</el-button>
                  <el-button size="small" text @click="emit('copy-rss', subscription.id)">RSS</el-button>
                  <el-button size="small" text type="danger" @click="requestSubscriptionRemoval(subscription)">取消订阅</el-button>
                  <el-select class="wechat-subscription-group" :model-value="subscription.group_ids || []" size="small" multiple collapse-tags :max-collapse-tags="1" :multiple-limit="3" placeholder="未分组" clearable @update:model-value="emit('update-subscription', subscription, { group_ids: $event })">
                    <el-option v-for="group in reportGroups" :key="group.id" :label="group.name" :value="group.id" />
                  </el-select>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section class="wechat-sheet wechat-report-sheet">
          <header class="wechat-sheet-head"><div><h3>分组报告</h3><p>将来源明确归入分组后，即可按时间范围生成报告。</p></div></header>
          <div class="wechat-report-create"><el-input v-model="groupDraft" name="wechat-report-group" autocomplete="off" aria-label="新建报告分组" placeholder="新分组，例如：学术动态…" @keyup.enter="createGroup" /><el-button type="primary" :disabled="!groupDraft.trim()" @click="createGroup">添加分组</el-button></div>
          <div v-if="!reportGroups.length" class="wechat-empty-feed"><strong>还没有分组</strong><p>创建分组后，将公众号归入相应类别。</p></div>
          <div v-else class="wechat-report-group-list"><article v-for="group in reportGroups" :key="group.id" class="wechat-report-group"><div><strong>{{ group.name }}</strong><span>{{ group.source_count ?? group.subscription_count }} 个来源</span></div><div><el-button size="small" text :disabled="!(group.source_count ?? group.subscription_count)" :loading="generatingGroupId === `${group.id}:daily`" @click="emit('generate-report', group.id, 'daily')">生成今日日报</el-button><el-button size="small" text :disabled="!(group.source_count ?? group.subscription_count)" :loading="generatingGroupId === `${group.id}:weekly`" @click="emit('generate-report', group.id, 'weekly')">生成本周周报</el-button></div></article></div>
        </section>

        <section class="wechat-sheet wechat-filter-sheet">
          <header class="wechat-sheet-head">
            <div>
              <h3>正文清洗</h3>
              <p>在入库、检索和 AI 总结前移除广告、推荐阅读或固定尾注。</p>
            </div>
          </header>
          <div class="wechat-filter-form">
            <label class="wechat-field">
              <span>规则名称</span>
              <el-input v-model="filterDraft.name" name="wechat-filter-name" autocomplete="off" aria-label="清洗规则名称" placeholder="例如：去除文末推荐…" />
            </label>
            <label class="wechat-field">
              <span>作用范围</span>
              <el-select v-model="filterDraft.subscription_id" clearable placeholder="全局：适用于所有公众号">
                <el-option label="全局：所有公众号" value="" />
                <el-option v-for="subscription in subscriptions" :key="subscription.id" :label="subscription.mp_name" :value="subscription.id" />
              </el-select>
            </label>
            <label class="wechat-field wechat-filter-wide">
              <span>CSS 选择器</span>
              <el-input v-model="filterDraft.selectors" name="wechat-filter-selectors" autocomplete="off" spellcheck="false" aria-label="CSS 选择器" placeholder="例如：.ad, #js_recommend…" />
            </label>
            <label class="wechat-field wechat-filter-wide">
              <span>文本正则（可选）</span>
              <el-input v-model="filterDraft.text_patterns" name="wechat-filter-patterns" autocomplete="off" spellcheck="false" aria-label="文本匹配规则" placeholder="例如：关注后回复.*…" />
            </label>
            <el-button type="primary" :loading="savingFilter" :disabled="!filterDraft.name.trim() || (!filterDraft.selectors.trim() && !filterDraft.text_patterns.trim())" @click="saveFilter">
              添加规则
            </el-button>
          </div>
          <div v-if="!contentFilters.length" class="wechat-empty-feed">
            <strong>还没有清洗规则</strong>
            <p>先从常见的广告或文末推荐区块开始配置。</p>
          </div>
          <div v-else class="wechat-filter-list">
            <article v-for="rule in contentFilters" :key="rule.id" class="wechat-filter-item">
              <div class="wechat-filter-copy">
                <strong>{{ rule.name }}</strong>
                <span>{{ rule.subscription_id ? subscriptionName(rule.subscription_id) : '全局规则' }} · 优先级 {{ rule.priority }}</span>
                <small>{{ rule.selectors.join(' · ') || rule.text_patterns.join(' · ') }}</small>
              </div>
              <el-button size="small" text type="danger" @click="requestFilterDeletion(rule)">删除</el-button>
            </article>
          </div>
        </section>
      </div>
    </div>
    <HistorySyncDialog
      v-model="historyDialog.open"
      :source-label="subscriptionName(historyDialog.subscriptionId)"
      :max-items="1000"
      @confirm="confirmHistorySync"
    />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import HistorySyncDialog from '../../components/HistorySyncDialog.vue'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm'

const props = defineProps({
  mode: { type: String, default: 'full' },
  embedded: { type: Boolean, default: false },
  authorizationAvailable: { type: Boolean, default: true },
  loading: { type: Boolean, default: false },
  accounts: { type: Array, default: () => [] },
  subscriptions: { type: Array, default: () => [] },
  selectedAccountId: { type: [String, Number], default: '' },
  accountDisplayName: { type: String, default: '' },
  qrLogin: { type: Object, default: () => ({}) },
  qrStarting: { type: Boolean, default: false },
  manualToken: { type: String, default: '' },
  manualCookie: { type: String, default: '' },
  manualConnecting: { type: Boolean, default: false },
  searchQuery: { type: String, default: '' },
  searchResults: { type: Array, default: () => [] },
  searching: { type: Boolean, default: false },
  subscriptionInterval: { type: Number, default: 1440 },
  intervalOptions: { type: Array, default: () => [] },
  autoProcess: { type: Boolean, default: true },
  subscriptionStates: { type: Object, default: () => ({}) },
  syncingSubscriptionId: { type: String, default: '' },
  contentFilters: { type: Array, default: () => [] },
  reportGroups: { type: Array, default: () => [] },
  generatingGroupId: { type: String, default: '' },
  savingFilter: { type: Boolean, default: false },
  autoSyncSummary: { type: Function, default: () => '' },
  lastSyncSummary: { type: Function, default: () => '' },
  publishingSettings: { type: Object, default: () => ({ configured: false }) },
  publishingDisplayName: { type: String, default: '订阅号' },
  publishingAppId: { type: String, default: '' },
  publishingAppSecret: { type: String, default: '' },
  publicSiteBaseUrl: { type: String, default: '' },
  savingPublishingSettings: { type: Boolean, default: false },
})

const selectedAccount = computed(() => props.accounts.find((account) => String(account.id) === String(props.selectedAccountId)) || null)
const authorizationUnavailableMessage = '微信公众平台新增授权与订阅暂不可用，已有公众号合集仍可使用。'
const selectedAccountRateLimited = computed(() => accountRateLimited(selectedAccount.value))
const filterDraft = reactive({ name: '', subscription_id: '', selectors: '', text_patterns: '' })
const groupDraft = ref('')
const historyDialog = reactive({ open: false, subscriptionId: '' })
const subscriptionName = (id) => props.subscriptions.find((item) => item.id === id)?.mp_name || '已移除的订阅'
const searchResultState = (item) => {
  const fakeid = String(item?.fakeid || '')
  const pendingState = props.subscriptionStates[`${props.selectedAccountId}:${fakeid}`]
  if (pendingState) return pendingState
  return props.subscriptions.some((subscription) => (
    String(subscription.account_id) === String(props.selectedAccountId)
    && String(subscription.fakeid) === fakeid
  )) ? 'subscribed' : 'idle'
}
const searchResultActionLabel = (item) => {
  const state = searchResultState(item)
  if (state === 'subscribing') return '订阅中'
  if (state === 'checking') return '检查中'
  if (state === 'subscribed') return '已订阅'
  return '订阅'
}

function timestamp(value) {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : 0
}

function formatTimestamp(value) {
  const parsed = timestamp(value)
  if (!parsed) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(parsed)
}

function accountRateLimited(account) {
  return timestamp(account?.rate_limited_until) > Date.now()
}

function subscriptionRateLimited(subscription) {
  return timestamp(subscription?.account_rate_limited_until) > Date.now()
}

function accountStateSummary(account) {
  if (account?.status !== 'active') return '需要重新授权'
  if (accountRateLimited(account)) return `频控冷却至 ${formatTimestamp(account.rate_limited_until)}`
  return '授权有效，可用于搜索与同步'
}

function subscriptionStatusLabel(subscription) {
  if (!subscription.enabled) return '已暂停'
  if (subscription.account_status !== 'active') return '需重新授权'
  if (subscriptionRateLimited(subscription)) return '频控冷却'
  return '正常'
}
function saveFilter() {
  emit('create-filter', {
    name: filterDraft.name.trim(),
    subscription_id: filterDraft.subscription_id || null,
    selectors: filterDraft.selectors.split(',').map((item) => item.trim()).filter(Boolean),
    text_patterns: filterDraft.text_patterns.split('\n').map((item) => item.trim()).filter(Boolean)
  }, () => Object.assign(filterDraft, { name: '', subscription_id: '', selectors: '', text_patterns: '' }))
}
function createGroup() { emit('create-report-group', { name: groupDraft.value.trim() }, () => { groupDraft.value = '' }) }

async function requestAccountRemoval(account) {
  const subscriptionCount = Number(account.subscription_count || 0)
  if (subscriptionCount) {
    ElMessage.warning(`该账号仍有 ${subscriptionCount} 个订阅；请先重新授权或迁移订阅`)
    return
  }
  const confirmed = await requestDestructiveConfirmation({
    title: '移除授权账号',
    message: '仅移除本地登录态，不会删除已入库文章。',
    confirmLabel: '移除账号',
  })
  if (confirmed) emit('delete-account', account.id)
}

async function requestSubscriptionTransfer(account) {
  const target = props.accounts.find((item) => item.id === props.selectedAccountId)
  if (!target || target.id === account.id) return
  const confirmed = await requestDestructiveConfirmation({
    title: '迁移公众号订阅',
    message: `将“${account.display_name}”下的 ${account.subscription_count} 个订阅迁移到“${target.display_name}”。已入库文章和分组保持不变。`,
    confirmLabel: '迁移订阅',
  })
  if (confirmed) emit('transfer-account-subscriptions', account.id)
}

async function requestSubscriptionRemoval(subscription) {
  const confirmed = await requestDestructiveConfirmation({
    title: '取消订阅',
    message: '取消订阅不会删除已经入库的文章。',
    confirmLabel: '取消订阅',
  })
  if (confirmed) emit('delete-subscription', subscription.id)
}

async function requestFilterDeletion(rule) {
  const confirmed = await requestDestructiveConfirmation({
    title: '删除清洗规则',
    message: '删除后，新抓取文章将不再使用该规则。',
    confirmLabel: '删除规则',
  })
  if (confirmed) emit('delete-filter', rule.id)
}

function startSync(subscription, command) {
  if (command === 'latest') {
    emit('sync-subscription', subscription.id, { mode: 'latest', max_items: 10 })
    return
  }
  historyDialog.subscriptionId = subscription.id
  historyDialog.open = true
}

function confirmHistorySync(payload) {
  historyDialog.open = false
  emit('sync-subscription', historyDialog.subscriptionId, payload)
}

const emit = defineEmits([
  'start-qr',
  'reauthorize-account',
  'connect-manual',
  'delete-account',
  'transfer-account-subscriptions',
  'search',
  'subscribe',
  'update-subscription',
  'sync-subscription',
  'delete-subscription',
  'create-filter',
  'delete-filter',
  'create-report-group',
  'generate-report',
  'copy-rss',
  'export-subscriptions',
  'update:selectedAccountId',
  'update:accountDisplayName',
  'update:manualToken',
  'update:manualCookie',
  'update:searchQuery',
  'update:subscriptionInterval',
  'update:autoProcess',
  'update:publishingDisplayName',
  'update:publishingAppId',
  'update:publishingAppSecret',
  'update:publicSiteBaseUrl',
  'save-publishing-settings',
])
</script>

<style scoped src="../../styles/wechatWorkspace.css"></style>
