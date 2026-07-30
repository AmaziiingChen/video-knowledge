<template>
  <section class="wechat-manager manager-surface" :aria-busy="loading">
    <header class="wechat-manager-head">
      <div class="wechat-manager-title">
        <h2>公众号管理</h2>
        <div class="wechat-manager-title-meta">
          <span class="wechat-manager-count">{{ subscriptions.length }} 个订阅</span>
          <span class="wechat-manager-account-status" :class="accountStatusClass">
            <i aria-hidden="true"></i>
            {{ accountStatusLabel }}
          </span>
        </div>
      </div>
      <div v-if="!batchMode" class="wechat-manager-head-actions">
        <el-button
          :disabled="!subscriptions.length || bulkSyncActive || !collectableAccounts.length"
          :title="bulkSyncActive ? bulkSyncProgressTitle : (!collectableAccounts.length && rateLimitedAccounts.length ? '微信正在频控冷却，恢复后才能检查' : '逐个检查所有已启用公众号，并自动补齐上次检查后的新文章')"
          @click="emit('sync-all')"
        >
          <el-icon><Refresh /></el-icon>
          {{ bulkSyncButtonLabel }}
        </el-button>
        <el-button type="primary" @click="openSubscriptionDialog">
          <el-icon><Plus /></el-icon>
          新增订阅
        </el-button>
        <el-dropdown trigger="click" placement="bottom-end" @command="handleHeaderCommand">
          <button type="button" class="wechat-manager-head-more" aria-label="更多公众号管理操作">
            <el-icon><MoreFilled /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="batch" :disabled="!subscriptions.length">批量管理</el-dropdown-item>
              <el-dropdown-item command="refresh" :disabled="loading">重新载入列表</el-dropdown-item>
              <el-dropdown-item command="rss">复制聚合 RSS 地址</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <section class="wechat-manager-toolbar" aria-label="公众号管理工具栏">
      <Transition name="wechat-toolbar-swap" mode="out-in">
        <BatchSelectionToolbar
          v-if="batchMode"
          key="batch"
          :all-selected="allFilteredSubscriptionsSelected"
          :indeterminate="filteredSelectionIndeterminate"
          :selected-count="selectedSubscriptionIds.length"
          selection-unit="个"
          :summary="`当前结果共 ${filteredSubscriptions.length} 个公众号`"
          select-all-label="选择当前结果中的全部公众号"
          :clear-disabled="!selectedSubscriptionIds.length"
          @update:all-selected="toggleFilteredSubscriptionSelection"
          @clear="clearBatchSelection"
          @exit="toggleBatchMode"
        >
          <template #actions>
            <el-popover
              :visible="bulkGroupPickerOpen"
              placement="bottom-start"
              :width="224"
              trigger="click"
              teleported
              popper-class="wechat-manager-bulk-group-popper"
              @update:visible="bulkGroupPickerOpen = $event"
            >
              <template #reference>
                <el-button size="small" :disabled="!selectedSubscriptionIds.length">加入分组</el-button>
              </template>
              <div class="wechat-manager-group-menu wechat-manager-bulk-group-menu">
                <p>添加到选中的 {{ selectedSubscriptionIds.length }} 个公众号</p>
                <button v-for="group in reportGroups" :key="group.id" type="button" @click="addGroupToSelectedSubscriptions(group.id)">
                  <span>{{ group.name }}</span><span>添加</span>
                </button>
                <p v-if="!reportGroups.length" class="wechat-manager-group-menu-empty">尚未创建分组，请先在“生成报告”中新增。</p>
              </div>
            </el-popover>
            <el-dropdown trigger="click" @command="updateSelectedInterval">
              <el-button size="small" :disabled="!selectedSubscriptionIds.length">检查频率</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="option in intervalOptions" :key="option.value" :command="option.value">{{ option.label }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-dropdown trigger="click" @command="updateSelectedProcessingMode">
              <el-button size="small" :disabled="!selectedSubscriptionIds.length">处理方式</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="analyze">自动分析</el-dropdown-item>
                  <el-dropdown-item command="inbox">仅入库</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-dropdown trigger="click" @command="updateSelectedNotificationState">
              <el-button size="small" :disabled="!selectedSubscriptionIds.length">通知</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="enabled">开启新文章通知</el-dropdown-item>
                  <el-dropdown-item command="disabled">关闭新文章通知</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-dropdown trigger="click" @command="updateSelectedEnabledState">
              <el-button size="small" :disabled="!selectedSubscriptionIds.length">启用状态</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="enabled">启用自动检查</el-dropdown-item>
                  <el-dropdown-item command="paused">暂停自动检查</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </BatchSelectionToolbar>

        <div v-else key="normal" class="wechat-manager-toolbar-normal">
          <div class="wechat-manager-discovery-controls">
            <div class="wechat-manager-search-anchor">
              <el-input
                v-model="subscriptionSearchDraft"
                clearable
                class="wechat-manager-source-search"
                name="subscription-search"
                autocomplete="off"
                aria-label="搜索已订阅公众号"
                placeholder="搜索名称、简介或分组…"
              >
                <template #prefix><el-icon><Search /></el-icon></template>
              </el-input>
            </div>
            <el-popover placement="bottom-start" :width="288" trigger="click" teleported popper-class="wechat-manager-filter-popper">
              <template #reference>
                <el-button class="wechat-manager-filter-trigger">
                  <el-icon><Filter /></el-icon>
                  筛选<span v-if="activeFilterCount"> {{ activeFilterCount }}</span>
                </el-button>
              </template>
              <div class="wechat-manager-filter-panel">
                <label>分组
                  <el-select v-model="selectedGroupFilter" placeholder="所有分组">
                    <el-option label="所有分组" value="" />
                    <el-option label="未分组" value="__ungrouped__" />
                    <el-option v-for="group in reportGroups" :key="group.id" :label="group.name" :value="String(group.id)" />
                  </el-select>
                </label>
                <label>同步状态
                  <el-select v-model="selectedStatusFilter" placeholder="全部状态">
                    <el-option label="全部状态" value="" />
                    <el-option label="正常同步" value="enabled" />
                    <el-option label="已暂停" value="paused" />
                  <el-option label="需要授权" value="reauth" />
                  <el-option label="频控冷却" value="rate_limit" />
                  <el-option label="检查失败" value="failed" />
                  </el-select>
                </label>
                <button type="button" class="wechat-manager-filter-reset" :disabled="!activeFilterCount" @click="clearActiveFilters">清除条件</button>
              </div>
            </el-popover>
            <el-select v-model="sortBy" class="wechat-manager-sort-select manager-control-select" aria-label="排序方式">
              <el-option label="最近检查" value="recent" />
              <el-option label="新文章优先" value="newest" />
              <el-option label="公众号名称" value="name" />
            </el-select>
          </div>
          <div v-if="activeFilterCount" class="wechat-manager-active-filters" aria-label="当前筛选条件">
            <button v-if="selectedGroupFilter" type="button" @click="selectedGroupFilter = ''">
              分组：{{ selectedGroupFilterLabel }}<el-icon><Close /></el-icon>
            </button>
            <button v-if="selectedStatusFilter" type="button" @click="selectedStatusFilter = ''">
              状态：{{ selectedStatusFilterLabel }}<el-icon><Close /></el-icon>
            </button>
          </div>
        </div>
      </Transition>
    </section>

    <section class="wechat-manager-card wechat-manager-list-card">
      <CollectionState v-if="loading && !subscriptions.length" mode="loading" loading-label="正在读取公众号订阅" />
      <CollectionState
        v-else-if="!filteredSubscriptions.length"
        :title="subscriptions.length ? '没有符合条件的公众号' : '还没有公众号订阅'"
        :description="subscriptions.length ? '调整搜索或筛选条件后再试。' : '点击右上角“新增订阅”开始添加。'"
      />

      <div v-else class="wechat-manager-list-main">
        <div ref="listViewport" class="wechat-manager-table-scroll vk-scroll-area" @scroll.passive="updateListScrollEdge">
          <div class="wechat-manager-table-head" :class="{ 'is-batch-mode': batchMode, 'is-scrolled': listScrolled }" role="row">
            <span v-if="batchMode" class="wechat-manager-selection-cell">
              <el-checkbox
                :model-value="allFilteredSubscriptionsSelected"
                :indeterminate="filteredSelectionIndeterminate"
                aria-label="选择当前结果中的全部公众号"
                @update:model-value="toggleFilteredSubscriptionSelection"
              />
            </span>
            <span class="column-source">公众号</span><span class="column-group">分组</span><span class="column-activity">活动</span><span class="column-analysis">自动分析</span><span class="column-notification">通知</span><span class="column-enabled">自动检查</span><span class="column-frequency">检查频率</span><span class="wechat-manager-table-actions-label column-actions">操作</span>
          </div>
          <div v-for="subscription in filteredSubscriptions" :key="subscription.id" class="wechat-manager-table-row" :class="{ 'is-batch-mode': batchMode }">
            <span v-if="batchMode" class="wechat-manager-selection-cell">
              <el-checkbox
                :model-value="subscriptionIsSelected(subscription.id)"
                :aria-label="`选择 ${subscription.mp_name}`"
                @update:model-value="toggleSubscriptionSelection(subscription.id, $event)"
              />
            </span>
            <span class="wechat-manager-source-cell column-source">
              <img v-if="subscription.avatar_url" :src="subscription.avatar_url" alt="" width="34" height="34" loading="lazy" decoding="async">
              <span v-else class="wechat-manager-avatar-fallback">{{ initials(subscription.mp_name) }}</span>
              <span class="wechat-manager-source-copy">
                <strong>{{ subscription.mp_name }}</strong>
                <small v-if="subscription.mp_description" :title="subscription.mp_description">{{ subscription.mp_description }}</small>
              </span>
            </span>
            <span class="wechat-manager-inline-control column-group">
              <ReportGroupMultiSelect
                :model-value="subscription.group_ids || []"
                :groups="reportGroups"
                :aria-label="`${subscription.mp_name} 的报告分组`"
                @update:model-value="emit('update-subscription', subscription, { group_ids: $event })"
              />
            </span>
            <span class="wechat-manager-activity-cell column-activity">
              <strong :class="activityClass(subscription)">{{ activityLabel(subscription) }}</strong>
              <small>{{ activityMeta(subscription) }}</small>
            </span>
            <span class="wechat-manager-source-setting-cell column-analysis">
              <el-switch :model-value="subscription.auto_process" :aria-label="`${subscription.auto_process ? '关闭' : '开启'} ${subscription.mp_name} 的自动分析`" @update:model-value="emit('update-subscription', subscription, { auto_process: $event })" />
            </span>
            <span class="wechat-manager-source-setting-cell column-notification">
              <el-switch :model-value="subscription.notify_on_new" :aria-label="`${subscription.notify_on_new ? '关闭' : '开启'} ${subscription.mp_name} 的新文章通知`" @update:model-value="emit('update-subscription', subscription, { notify_on_new: $event })" />
            </span>
            <span class="wechat-manager-source-setting-cell column-enabled">
              <el-switch :model-value="subscription.enabled" :aria-label="`${subscription.enabled ? '暂停' : '启用'} ${subscription.mp_name} 的自动检查`" @update:model-value="emit('update-subscription', subscription, { enabled: $event })" />
            </span>
            <span class="wechat-manager-source-setting-cell column-frequency">
              <el-select :model-value="subscription.sync_interval_minutes" size="small" :aria-label="`${subscription.mp_name} 的检查频率`" @update:model-value="updateInterval(subscription, $event)">
                <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
              </el-select>
            </span>
            <span class="wechat-manager-operation-cell column-actions">
              <span class="wechat-manager-row-actions">
                <el-button
                  text
                  size="small"
                  :loading="syncingSubscriptionId === subscription.id"
                  :disabled="subscriptionRateLimited(subscription)"
                  :title="subscriptionRateLimited(subscription) ? `频控冷却至 ${formatTimestamp(subscription.account_rate_limited_until)}` : '检查最新文章'"
                  @click="startLatestSync(subscription)"
                >
                  {{ historyRunningSubscriptionId === subscription.id ? '回溯中' : (syncingSubscriptionId === subscription.id ? '检查中' : '检查') }}
                </el-button>
                <el-popover
                  :visible="actionMenuSubscriptionId === subscription.id"
                  placement="bottom-end"
                  :width="204"
                  trigger="click"
                  teleported
                  transition="el-zoom-in-top"
                  popper-class="wechat-manager-action-popper"
                  @update:visible="setActionMenuVisible(subscription.id, $event)"
                >
                  <template #reference>
                    <button class="wechat-manager-more" type="button" :aria-label="`${subscription.mp_name} 的更多操作`" @click.stop><el-icon><MoreFilled /></el-icon></button>
                  </template>
                  <div class="wechat-manager-action-menu">
                    <button type="button" :disabled="refreshingProfileId === subscription.id || subscriptionRateLimited(subscription)" @click="runAction(subscription, 'profile')">
                      {{ refreshingProfileId === subscription.id ? '正在更新资料…' : (subscription.mp_description ? '更新公众号资料' : '补全公众号资料') }}
                    </button>
                    <button type="button" :disabled="subscriptionRateLimited(subscription)" @click="runAction(subscription, 'history')">回溯历史文章</button>
                    <button type="button" @click="runAction(subscription, 'rss')">复制 RSS 地址</button>
                    <button type="button" class="is-danger" @click="requestSubscriptionRemoval(subscription)">取消订阅</button>
                  </div>
                </el-popover>
              </span>
            </span>
          </div>
        </div>
      </div>
    </section>

    <el-dialog
      v-model="subscriptionDialogOpen"
      title="新增订阅"
      width="min(680px, calc(100vw - 32px))"
      append-to-body
      class="wechat-manager-subscribe-dialog"
      @opened="focusSubscriptionDialogSearch"
      @closed="resetSubscriptionDialog"
    >
      <div class="wechat-subscribe-dialog-body">
        <div v-if="accounts.length > 1" class="wechat-subscribe-account-row">
          <span>使用授权账号</span>
          <el-select
            :model-value="selectedAccountId"
            placeholder="选择授权账号"
            @update:model-value="emit('update:selectedAccountId', $event)"
          >
            <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
        </div>

        <div v-if="accounts.length" class="wechat-subscribe-search-row">
          <el-input
            ref="subscriptionSearchInput"
            :model-value="searchQuery"
            clearable
            placeholder="输入公众号名称或关键词"
            @clear="emit('clear-search-results')"
            @keyup.enter="runSubscriptionDiscovery"
            @update:model-value="updateSearchQuery"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button
            type="primary"
            :disabled="!selectedAccountId || !searchQuery.trim()"
            :loading="searching"
            @click="runSubscriptionDiscovery"
          >
            搜索公众号
          </el-button>
        </div>

        <div v-else class="wechat-subscribe-account-empty">
          尚未连接微信公众平台账号，请先在设置中完成授权。
        </div>

        <Transition name="wechat-quick-config">
          <section v-if="quickConfigSubscription" class="wechat-subscribe-quick-config" aria-live="polite">
            <header>
              <div>
                <strong>{{ quickConfigSubscription.mp_name }} 已订阅</strong>
                <span>完成常用设置，之后也可在公众号列表中修改。</span>
              </div>
              <el-button text size="small" @click="finishQuickConfig">完成</el-button>
            </header>
            <div class="wechat-subscribe-quick-config-fields">
              <label>
                <span>报告分组</span>
                <el-select
                  :model-value="(quickConfigSubscription.group_ids || []).map(String)"
                  multiple
                  collapse-tags
                  :max-collapse-tags="1"
                  :multiple-limit="3"
                  placeholder="未分组"
                  @update:model-value="updateQuickConfig({ group_ids: $event })"
                >
                  <el-option v-for="group in reportGroups" :key="group.id" :label="group.name" :value="String(group.id)" />
                </el-select>
              </label>
              <label>
                <span>检查频率</span>
                <el-select :model-value="quickConfigSubscription.sync_interval_minutes" @update:model-value="updateQuickConfig({ sync_interval_minutes: $event })">
                  <el-option v-for="option in intervalOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
              </label>
              <label>
                <span>处理方式</span>
                <el-select :model-value="quickConfigSubscription.auto_process ? 'analyze' : 'inbox'" @update:model-value="updateQuickConfigProcessingMode">
                  <el-option label="自动分析" value="analyze" />
                  <el-option label="仅入库" value="inbox" />
                </el-select>
              </label>
            </div>
          </section>
        </Transition>

        <section v-if="recentSearchQueries.length" class="wechat-subscribe-recent">
          <div class="wechat-subscribe-section-head">
            <strong>最近搜索</strong>
            <button type="button" @click="clearDiscoveryHistory">清除记录</button>
          </div>
          <div class="wechat-subscribe-query-list">
            <button v-for="query in recentSearchQueries" :key="query" type="button" @click="searchRecentQuery(query)">
              {{ query }}
            </button>
          </div>
        </section>

        <section v-loading="searching" class="wechat-subscribe-discovery">
          <Transition name="wechat-discovery-state" mode="out-in">
            <div v-if="searchResults.length" key="results" class="wechat-subscribe-discovery-state">
            <div class="wechat-subscribe-section-head">
              <strong>搜索结果</strong>
              <span>{{ searchResults.length }} 个公众号</span>
            </div>
            <div class="wechat-subscribe-result-list" aria-live="polite">
              <article v-for="item in searchResults" :key="item.fakeid" class="wechat-manager-search-result">
                <img v-if="item.avatar_url" :src="item.avatar_url" alt="" width="32" height="32" loading="lazy" decoding="async">
                <span v-else class="wechat-manager-avatar-fallback">{{ initials(item.name) }}</span>
                <div>
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.description || '该公众号未返回简介' }}</span>
                </div>
                <el-button
                  :type="searchResultState(item) === 'subscribed' ? 'default' : 'primary'"
                  size="small"
                  :loading="['subscribing', 'checking'].includes(searchResultState(item))"
                  :disabled="searchResultState(item) === 'subscribed'"
                  @click="beginSubscribe(item)"
                >
                  {{ searchResultActionLabel(item) }}
                </el-button>
              </article>
            </div>
            </div>

            <div v-else-if="interestRecommendations.length && !searchQuery.trim()" key="recommendations" class="wechat-subscribe-discovery-state">
            <div class="wechat-subscribe-section-head">
              <strong>可能感兴趣</strong>
              <span>根据最近搜索整理</span>
            </div>
            <div class="wechat-subscribe-result-list">
              <article v-for="item in interestRecommendations" :key="item.fakeid" class="wechat-manager-search-result">
                <img v-if="item.avatar_url" :src="item.avatar_url" alt="" width="32" height="32" loading="lazy" decoding="async">
                <span v-else class="wechat-manager-avatar-fallback">{{ initials(item.name) }}</span>
                <div>
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.description || '来自最近搜索结果' }}</span>
                </div>
                <el-button
                  :type="searchResultState(item) === 'subscribed' ? 'default' : 'primary'"
                  size="small"
                  :loading="['subscribing', 'checking'].includes(searchResultState(item))"
                  :disabled="searchResultState(item) === 'subscribed'"
                  @click="beginSubscribe(item)"
                >
                  {{ searchResultActionLabel(item) }}
                </el-button>
              </article>
            </div>
            </div>

            <div v-else-if="!searching" key="empty" class="wechat-subscribe-discovery-empty">
              <strong>{{ searchQuery.trim() ? '没有找到匹配的公众号' : '搜索想订阅的公众号' }}</strong>
              <span>{{ searchQuery.trim() ? '换一个名称或关键词再试。' : '搜索记录会保存在本机，并用于生成后续推荐。' }}</span>
            </div>
          </Transition>
        </section>
      </div>
    </el-dialog>

    <HistorySyncDialog
      v-model="historyDialog.open"
      :source-label="historyDialog.sourceLabel"
      :max-items="1000"
      @confirm="confirmHistorySync"
    />
  </section>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElCheckbox } from 'element-plus'
import { Close, Filter, MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import BatchSelectionToolbar from '../../components/BatchSelectionToolbar.vue'
import HistorySyncDialog from '../../components/HistorySyncDialog.vue'
import ReportGroupMultiSelect from '../../components/ReportGroupMultiSelect.vue'
import CollectionState from '../../components/CollectionState.vue'
import { requestDestructiveConfirmation } from '../../composables/useDestructiveConfirm'
import {
  discoveryRecommendations,
  normalizeDiscoveryHistory,
  recordDiscovery
} from './wechatDiscoveryHistory'

const props = defineProps({
  loading: { type: Boolean, default: false },
  accounts: { type: Array, default: () => [] },
  subscriptions: { type: Array, default: () => [] },
  selectedAccountId: { type: [String, Number], default: '' },
  searchQuery: { type: String, default: '' },
  searchResults: { type: Array, default: () => [] },
  searching: { type: Boolean, default: false },
  intervalOptions: { type: Array, default: () => [] },
  subscriptionStates: { type: Object, default: () => ({}) },
  syncingSubscriptionId: { type: String, default: '' },
  bulkSyncState: { type: Object, default: () => ({ status: 'idle', total: 0, completed: 0 }) },
  refreshingProfileId: { type: String, default: '' },
  reportGroups: { type: Array, default: () => [] }
})

const emit = defineEmits([
  'refresh',
  'search',
  'subscribe',
  'update-subscription',
  'sync-subscription',
  'sync-all',
  'refresh-profile',
  'bulk-add-group',
  'bulk-update-subscriptions',
  'delete-subscription',
  'copy-rss',
  'clear-search-results',
  'update:selectedAccountId',
  'update:searchQuery'
])

const DISCOVERY_HISTORY_KEY = 'knowledgehub.wechat-discovery-history.v1'
const subscriptionSearchDraft = ref('')
const selectedGroupFilter = ref('')
const selectedStatusFilter = ref('')
const sortBy = ref('recent')
const listViewport = ref(null)
const listScrolled = ref(false)
const subscriptionSearchInput = ref(null)
const subscriptionDialogOpen = ref(false)
const quickConfigTarget = ref(null)
const discoveryHistory = ref(readDiscoveryHistory())
const actionMenuSubscriptionId = ref('')
const batchMode = ref(false)
const selectedSubscriptionIds = ref([])
const bulkGroupPickerOpen = ref(false)
const historyDialog = reactive({ open: false, subscriptionId: '', sourceLabel: '' })
const historyRunningSubscriptionId = ref('')

const groupsById = computed(() => new Map(props.reportGroups.map((group) => [String(group.id), group.name])))
const activeAccounts = computed(() => props.accounts.filter((account) => account.status === 'active'))
const rateLimitedAccounts = computed(() => activeAccounts.value.filter(accountRateLimited))
const collectableAccounts = computed(() => activeAccounts.value.filter((account) => !accountRateLimited(account)))
const accountStatusLabel = computed(() => {
  if (!props.accounts.length) return '微信账号未连接'
  if (!activeAccounts.value.length) return '微信账号需要授权'
  if (!collectableAccounts.value.length) return '微信账号频控冷却中'
  if (rateLimitedAccounts.value.length) return `${rateLimitedAccounts.value.length} 个微信账号冷却中`
  if (activeAccounts.value.length === 1) return '微信账号已连接'
  return `${activeAccounts.value.length} 个微信账号已连接`
})
const accountStatusClass = computed(() => ({
  'is-active': Boolean(collectableAccounts.value.length) && !rateLimitedAccounts.value.length,
  'is-warning': Boolean(props.accounts.length) && (!activeAccounts.value.length || Boolean(rateLimitedAccounts.value.length)),
  'is-muted': !props.accounts.length
}))
const activeFilterCount = computed(() => Number(Boolean(selectedGroupFilter.value)) + Number(Boolean(selectedStatusFilter.value)))
const selectedGroupFilterLabel = computed(() => {
  if (selectedGroupFilter.value === '__ungrouped__') return '未分组'
  return groupsById.value.get(String(selectedGroupFilter.value)) || '未知分组'
})
const selectedStatusFilterLabel = computed(() => ({ enabled: '正常同步', paused: '已暂停', reauth: '需要授权', rate_limit: '频控冷却', failed: '检查失败' }[selectedStatusFilter.value] || '全部状态'))

watch(() => props.syncingSubscriptionId, (activeSubscriptionId) => {
  if (historyRunningSubscriptionId.value && activeSubscriptionId !== historyRunningSubscriptionId.value) {
    historyRunningSubscriptionId.value = ''
  }
})

const filteredSubscriptions = computed(() => {
  const normalizedKeyword = subscriptionSearchDraft.value.trim().toLocaleLowerCase()
  const status = selectedStatusFilter.value
  const group = selectedGroupFilter.value
  const rows = props.subscriptions.filter((subscription) => {
    const labels = groupLabels(subscription)
    const haystack = `${subscription.mp_name || ''} ${subscription.mp_description || ''} ${labels.join(' ')}`.toLocaleLowerCase()
    if (normalizedKeyword && !haystack.includes(normalizedKeyword)) return false
    if (group === '__ungrouped__' && labels.length) return false
    if (group && group !== '__ungrouped__' && !(subscription.group_ids || []).map(String).includes(group)) return false
    if (status === 'enabled' && (!subscription.enabled || subscription.account_status !== 'active' || subscriptionRateLimited(subscription) || subscription.last_run_status === 'failed')) return false
    if (status === 'paused' && subscription.enabled) return false
    if (status === 'reauth' && subscription.account_status === 'active') return false
    if (status === 'rate_limit' && !subscriptionRateLimited(subscription)) return false
    if (status === 'failed' && subscription.last_run_status !== 'failed') return false
    return true
  })
  return rows.sort((left, right) => {
    if (sortBy.value === 'name') return String(left.mp_name || '').localeCompare(String(right.mp_name || ''), 'zh-CN')
    if (sortBy.value === 'newest') return Number(right.last_run_imported_count || 0) - Number(left.last_run_imported_count || 0)
    return timestamp(right.last_run_finished_at || right.last_sync_at) - timestamp(left.last_run_finished_at || left.last_sync_at)
  })
})

const selectedSubscriptionIdSet = computed(() => new Set(selectedSubscriptionIds.value.map(String)))
const selectedFilteredSubscriptionCount = computed(() => filteredSubscriptions.value.filter((subscription) => selectedSubscriptionIdSet.value.has(String(subscription.id))).length)
const allFilteredSubscriptionsSelected = computed(() => Boolean(filteredSubscriptions.value.length) && selectedFilteredSubscriptionCount.value === filteredSubscriptions.value.length)
const filteredSelectionIndeterminate = computed(() => selectedFilteredSubscriptionCount.value > 0 && !allFilteredSubscriptionsSelected.value)
const recentSearchQueries = computed(() => discoveryHistory.value.map((entry) => entry.query).filter(Boolean).slice(0, 6))
const interestRecommendations = computed(() => discoveryRecommendations(discoveryHistory.value, props.subscriptions))
const quickConfigSubscription = computed(() => {
  const target = quickConfigTarget.value
  if (!target) return null
  return props.subscriptions.find((subscription) => (
    String(subscription.account_id) === target.accountId
    && String(subscription.fakeid) === target.fakeid
  )) || null
})
const bulkSyncActive = computed(() => ['queued', 'running'].includes(props.bulkSyncState?.status))
const bulkSyncButtonLabel = computed(() => {
  if (!bulkSyncActive.value) return '检查全部'
  const total = Number(props.bulkSyncState?.total || 0)
  const completed = Number(props.bulkSyncState?.completed || 0)
  return total ? `检查 ${Math.min(completed + 1, total)}/${total}` : '准备检查'
})
const bulkSyncProgressTitle = computed(() => {
  const name = String(props.bulkSyncState?.current_name || '').trim()
  return name ? `正在检查：${name}` : '正在准备逐个检查公众号'
})

watch([subscriptionSearchDraft, selectedGroupFilter, selectedStatusFilter, sortBy], async () => {
  await nextTick()
  scrollListToTop()
})

watch(() => props.subscriptions.map((subscription) => String(subscription.id)), (subscriptionIds) => {
  const activeIds = new Set(subscriptionIds)
  selectedSubscriptionIds.value = selectedSubscriptionIds.value.filter((id) => activeIds.has(String(id)))
})

watch(() => props.searching, (searching, wasSearching) => {
  if (wasSearching && !searching && props.searchQuery.trim()) {
    rememberDiscovery(props.searchQuery, props.searchResults)
  }
})

function updateSearchQuery(value) {
  emit('update:searchQuery', value)
  if (props.searchResults.length) emit('clear-search-results')
}

function openSubscriptionDialog() {
  subscriptionDialogOpen.value = true
}

function focusSubscriptionDialogSearch() {
  subscriptionSearchInput.value?.focus?.()
}

function resetSubscriptionDialog() {
  quickConfigTarget.value = null
  emit('clear-search-results')
  emit('update:searchQuery', '')
}

function runSubscriptionDiscovery() {
  if (!props.selectedAccountId || !props.searchQuery.trim() || props.searching) return
  emit('search')
}

function searchRecentQuery(query) {
  emit('update:searchQuery', query)
  emit('clear-search-results')
  nextTick(() => emit('search'))
}

function clearActiveFilters() {
  selectedGroupFilter.value = ''
  selectedStatusFilter.value = ''
}

function readDiscoveryHistory() {
  try {
    const data = JSON.parse(localStorage.getItem(DISCOVERY_HISTORY_KEY) || '[]')
    return normalizeDiscoveryHistory(data)
  } catch {
    return []
  }
}

function persistDiscoveryHistory() {
  try {
    localStorage.setItem(DISCOVERY_HISTORY_KEY, JSON.stringify(discoveryHistory.value))
  } catch {
    // Search history is supplementary and must never block subscribing.
  }
}

function rememberDiscovery(rawQuery, results) {
  discoveryHistory.value = recordDiscovery(discoveryHistory.value, rawQuery, results)
  persistDiscoveryHistory()
}

function clearDiscoveryHistory() {
  discoveryHistory.value = []
  persistDiscoveryHistory()
}

function beginSubscribe(item) {
  if (searchResultState(item) !== 'idle') return
  quickConfigTarget.value = {
    accountId: String(props.selectedAccountId || ''),
    fakeid: String(item?.fakeid || '')
  }
  emit('subscribe', item)
}

function updateQuickConfig(payload) {
  if (!quickConfigSubscription.value) return
  emit('update-subscription', quickConfigSubscription.value, payload)
}

function updateQuickConfigProcessingMode(value) {
  updateQuickConfig({ auto_process: value === 'analyze' })
}

function finishQuickConfig() {
  quickConfigTarget.value = null
  nextTick(() => subscriptionSearchInput.value?.focus?.())
}

function initials(value) {
  return String(value || '公').trim().slice(0, 1) || '公'
}

function searchResultState(item) {
  const fakeid = String(item?.fakeid || '')
  const pendingState = props.subscriptionStates[`${props.selectedAccountId}:${fakeid}`]
  if (pendingState) return pendingState
  return props.subscriptions.some((subscription) => (
    String(subscription.account_id) === String(props.selectedAccountId)
    && String(subscription.fakeid) === fakeid
  )) ? 'subscribed' : 'idle'
}

function searchResultActionLabel(item) {
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

function accountRateLimited(account) {
  return timestamp(account?.rate_limited_until) > Date.now()
}

function subscriptionRateLimited(subscription) {
  return timestamp(subscription?.account_rate_limited_until) > Date.now()
}

function groupLabels(subscription) {
  return (subscription.group_ids || []).map(String).map((id) => groupsById.value.get(id)).filter(Boolean).slice(0, 3)
}

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  bulkGroupPickerOpen.value = false
  if (!batchMode.value) clearBatchSelection()
}

function handleHeaderCommand(command) {
  if (command === 'batch') toggleBatchMode()
  if (command === 'refresh') emit('refresh')
  if (command === 'rss') emit('copy-rss')
}

function subscriptionIsSelected(subscriptionId) {
  return selectedSubscriptionIdSet.value.has(String(subscriptionId))
}

function toggleSubscriptionSelection(subscriptionId, selected) {
  const id = String(subscriptionId)
  const next = new Set(selectedSubscriptionIds.value.map(String))
  if (selected) next.add(id)
  else next.delete(id)
  selectedSubscriptionIds.value = [...next]
}

function toggleFilteredSubscriptionSelection(selected) {
  const next = new Set(selectedSubscriptionIds.value.map(String))
  for (const subscription of filteredSubscriptions.value) {
    if (selected) next.add(String(subscription.id))
    else next.delete(String(subscription.id))
  }
  selectedSubscriptionIds.value = [...next]
}

function clearBatchSelection() {
  selectedSubscriptionIds.value = []
  bulkGroupPickerOpen.value = false
}

function addGroupToSelectedSubscriptions(groupId) {
  if (!selectedSubscriptionIds.value.length) return
  emit('bulk-add-group', { subscriptionIds: [...selectedSubscriptionIds.value], groupId })
  bulkGroupPickerOpen.value = false
}

function selectedSubscriptions() {
  return props.subscriptions.filter((subscription) => selectedSubscriptionIdSet.value.has(String(subscription.id)))
}

function updateSelectedSubscriptions(payload, label) {
  const subscriptions = selectedSubscriptions()
  if (!subscriptions.length) return
  emit('bulk-update-subscriptions', {
    subscriptionIds: subscriptions.map((subscription) => subscription.id),
    payload,
    label
  })
}

function updateSelectedInterval(value) {
  updateSelectedSubscriptions({ sync_interval_minutes: value }, '检查频率')
}

function updateSelectedProcessingMode(value) {
  updateSelectedSubscriptions({ auto_process: value === 'analyze' }, '处理方式')
}

function updateSelectedNotificationState(value) {
  updateSelectedSubscriptions({ notify_on_new: value === 'enabled' }, '新文章通知')
}

function updateSelectedEnabledState(value) {
  updateSelectedSubscriptions({ enabled: value === 'enabled' }, '启用状态')
}

function updateListScrollEdge(event) {
  const viewport = event?.currentTarget || listViewport.value
  listScrolled.value = Number(viewport?.scrollTop || 0) > 1
}

function scrollListToTop() {
  listScrolled.value = false
  listViewport.value?.scrollTo?.({ top: 0 })
}

function intervalLabel(value) {
  return props.intervalOptions.find((option) => String(option.value) === String(value))?.label || '未设置'
}

function updateInterval(subscription, value) {
  if (String(subscription.sync_interval_minutes) === String(value)) return
  emit('update-subscription', subscription, { sync_interval_minutes: value })
}

function updateProcessingMode(subscription, value) {
  const autoProcess = value === 'analyze'
  if (subscription.auto_process === autoProcess) return
  emit('update-subscription', subscription, { auto_process: autoProcess })
}

function activityLabel(subscription) {
  if (!subscription.enabled) return '已暂停'
  if (subscription.account_status !== 'active') return '需要授权'
  if (subscriptionRateLimited(subscription)) return '频控冷却'
  if (historyRunningSubscriptionId.value === subscription.id) return '正在回溯'
  if (isBulkChecking(subscription)) return '检查中'
  if (subscription.last_run_status === 'running' || props.syncingSubscriptionId === subscription.id) return '检查中'
  if (subscription.last_run_status === 'failed') return '检查失败'
  if (!subscription.last_run_status || !subscription.last_run_finished_at) return '尚未检查'
  const importedCount = Number(subscription.last_run_imported_count || 0)
  return importedCount > 0 ? `新增 ${importedCount} 篇` : '无新增'
}

function activityClass(subscription) {
  if (!subscription.enabled) return 'is-muted'
  if (subscription.account_status !== 'active') return 'is-warning'
  if (subscriptionRateLimited(subscription)) return 'is-warning'
  if (subscription.last_run_status === 'failed') return 'is-error'
  if (historyRunningSubscriptionId.value === subscription.id) return 'is-running'
  if (isBulkChecking(subscription)) return 'is-running'
  if (subscription.last_run_status === 'running' || props.syncingSubscriptionId === subscription.id) return 'is-running'
  if (!subscription.last_run_status || !subscription.last_run_finished_at) return 'is-muted'
  if (Number(subscription.last_run_imported_count || 0) > 0) return 'has-new'
  return 'is-default'
}

function isBulkChecking(subscription) {
  return bulkSyncActive.value
    && String(props.bulkSyncState?.current_subscription_id || '') === String(subscription.id || '')
}

function formatTimestamp(value) {
  const parsed = timestamp(value)
  if (!parsed) return '尚未检查'
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(parsed)
}

function activityMeta(subscription) {
  if (subscriptionRateLimited(subscription)) {
    return `预计 ${formatTimestamp(subscription.account_rate_limited_until)} 恢复`
  }
  const value = subscription.last_run_finished_at || subscription.last_sync_at
  return timestamp(value) ? `上次检查 ${formatTimestamp(value)}` : '尚未检查'
}

function startLatestSync(subscription) {
  emit('sync-subscription', subscription.id, { mode: 'latest', max_items: 10 })
}

function openHistory(subscription) {
  historyDialog.subscriptionId = subscription.id
  historyDialog.sourceLabel = subscription.mp_name || '当前公众号'
  historyDialog.open = true
}

function confirmHistorySync(payload) {
  historyDialog.open = false
  historyRunningSubscriptionId.value = historyDialog.subscriptionId
  emit('sync-subscription', historyDialog.subscriptionId, payload)
}

function setActionMenuVisible(subscriptionId, visible) {
  actionMenuSubscriptionId.value = visible ? subscriptionId : ''
}

function runAction(subscription, action) {
  actionMenuSubscriptionId.value = ''
  if (action === 'latest') startLatestSync(subscription)
  if (action === 'profile') emit('refresh-profile', subscription.id)
  if (action === 'history') openHistory(subscription)
  if (action === 'rss') emit('copy-rss', subscription.id)
  if (action === 'remove') emit('delete-subscription', subscription.id)
}

async function requestSubscriptionRemoval(subscription) {
  actionMenuSubscriptionId.value = ''
  const confirmed = await requestDestructiveConfirmation({
    title: '取消订阅',
    message: '取消订阅不会删除已经入库的文章。',
    confirmLabel: '取消订阅',
  })
  if (confirmed) emit('delete-subscription', subscription.id)
}

</script>

<style scoped src="../../styles/wechatManager.css"></style>
