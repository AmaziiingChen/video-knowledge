<template>
  <div class="public-report-page public-archive-page">
    <main class="public-report-reader">
      <header class="public-report-topbar">
        <a class="public-report-brand" href="./index.html" aria-label="打开最新一期报告">
          <span class="public-report-brand-mark" aria-hidden="true">知</span>
          <span>知识简报</span>
        </a>
        <div class="public-report-actions">
          <a class="public-report-archive-link is-current" href="./archive.html" aria-current="page">历史档案</a>
          <button
            ref="themeToggle"
            class="public-report-theme-toggle"
            type="button"
            :aria-label="isNight ? '切换到日间模式' : '切换到夜间模式'"
            @click="toggleTheme"
          >
            <svg v-if="isNight" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M20.6 15.8A8.7 8.7 0 0 1 8.2 3.4 8.7 8.7 0 1 0 20.6 15.8Z" /></svg>
            <span>{{ isNight ? '日间' : '夜间' }}</span>
          </button>
        </div>
      </header>

      <section class="public-archive" aria-labelledby="archive-title">
        <header class="public-archive-heading">
          <h1 id="archive-title">历史档案</h1>
        </header>

        <div class="public-archive-summary" aria-label="档案统计">
          <span>{{ publishedReports.length }} 期已发表</span>
          <i aria-hidden="true"></i>
          <span>{{ reportTypes.size }} 类简报</span>
          <i aria-hidden="true"></i>
          <span>按发表时间归档</span>
        </div>

        <section v-if="publishedReports.length" class="public-archive-list" aria-label="已发布报告列表">
          <article v-for="report in publishedReports" :key="report.id" class="public-archive-item">
            <time :datetime="report.publishedAt">{{ formatPublishedDate(report.publishedAt) }}</time>
            <div class="public-archive-item-main">
              <p>{{ reportLabel(report.type) }} <i aria-hidden="true"></i> {{ report.period }}</p>
              <h2><a :href="report.publicUrl">{{ report.title }}</a></h2>
              <dl>
                <div v-if="report.articleCount"><dt>分析文章</dt><dd>{{ report.articleCount }} 篇</dd></div>
                <div v-if="report.readTimeMinutes"><dt>预计阅读</dt><dd>约 {{ report.readTimeMinutes }} 分钟</dd></div>
                <div><dt>公众号</dt><dd><a v-if="report.wechatUrl" :href="report.wechatUrl" target="_blank" rel="noreferrer">查看原文 ↗</a><span v-else>已发表</span></dd></div>
              </dl>
            </div>
            <a class="public-archive-open" :href="report.publicUrl" :aria-label="`阅读${report.title}`">阅读 <span aria-hidden="true">↗</span></a>
          </article>
        </section>

        <section v-else class="public-archive-empty" aria-label="尚无已发布报告">
          <span class="public-archive-empty-mark" aria-hidden="true">刊</span>
          <div>
            <h2>尚无历史档案</h2>
          </div>
        </section>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import publicationManifest from 'virtual:knowledgehub-published-reports'

const themeToggle = ref(null)
const isNight = ref(false)
const publishedReports = computed(() => (publicationManifest.reports || [])
  .filter((report) => report?.status === 'published' && report?.publicUrl && report?.publishedAt)
  .sort((left, right) => String(right.publishedAt).localeCompare(String(left.publishedAt))))
const reportTypes = computed(() => new Set(publishedReports.value.map((report) => report.type || 'other')))

onMounted(() => {
  try {
    isNight.value = window.localStorage.getItem('knowledgehub-public-report-theme') === 'night'
  } catch {
    isNight.value = false
  }
  applyTheme()
})

function reportLabel(type) {
  return { daily: '日报', weekly: '周报', special: '专题' }[type] || '简报'
}

function formatPublishedDate(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[1]}.${match[2]}.${match[3]}` : value
}

function toggleTheme(event) {
  const nextThemeIsNight = !isNight.value
  const changeTheme = () => {
    isNight.value = nextThemeIsNight
    applyTheme()
    try {
      window.localStorage.setItem('knowledgehub-public-report-theme', nextThemeIsNight ? 'night' : 'day')
    } catch {
      // Theme persistence is a convenience only; a restricted browser can still switch themes.
    }
  }

  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (reducedMotion || typeof document.startViewTransition !== 'function') {
    changeTheme()
    return
  }

  const trigger = event?.currentTarget || themeToggle.value
  const bounds = trigger?.getBoundingClientRect()
  const originX = bounds ? bounds.left + (bounds.width / 2) : window.innerWidth - 36
  const originY = bounds ? bounds.top + (bounds.height / 2) : 36
  const viewportWidth = document.documentElement.clientWidth
  const viewportHeight = document.documentElement.clientHeight
  const radius = Math.hypot(
    Math.max(originX, viewportWidth - originX),
    Math.max(originY, viewportHeight - originY),
  ) * 1.18
  const transition = document.startViewTransition(changeTheme)
  transition.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0 at ${originX}px ${originY}px)`, `circle(${radius}px at ${originX}px ${originY}px)`] },
      {
        duration: 900,
        easing: 'cubic-bezier(.42, 0, .58, 1)',
        pseudoElement: '::view-transition-new(root)',
      },
    )
  })
}

function applyTheme() {
  document.documentElement.dataset.theme = isNight.value ? 'night' : 'day'
}
</script>
