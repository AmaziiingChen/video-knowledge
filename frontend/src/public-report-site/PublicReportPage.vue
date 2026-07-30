<template>
  <div class="public-report-page">
    <main ref="reader" class="public-report-reader" tabindex="-1">
      <header class="public-report-topbar">
        <a class="public-report-brand" href="#report-title" aria-label="返回本期报告开头">
          <span class="public-report-brand-mark" aria-hidden="true">知</span>
          <span>知识简报</span>
        </a>
        <div class="public-report-actions">
          <span>{{ reportMeta.groupName }} · {{ reportMeta.reportLabel }}</span>
          <a class="public-report-archive-link" :href="archiveHref">历史档案</a>
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
          <button type="button" @click="printReport">打印</button>
        </div>
      </header>

      <article class="public-report-article" aria-labelledby="report-title">
        <header class="public-report-hero">
          <div class="public-report-issue">
            <span>{{ reportMeta.reportLabel }}</span>
            <i aria-hidden="true"></i>
            <span>{{ reportMeta.periodLabel }}</span>
          </div>
          <div class="public-report-hero-grid">
            <div>
              <h1 id="report-title">{{ reportMeta.title }}</h1>
            </div>
          </div>
          <div class="public-report-facts" aria-label="本期概览">
            <div><span>报告区间</span><strong>{{ reportMeta.dayCount }} 天</strong></div>
            <div><span>分析文章</span><strong>{{ reportMeta.sourceCount }} 篇</strong></div>
            <div><span>正文引用</span><strong>{{ reportMeta.citedSourceCount }} 篇</strong></div>
            <div><span>报告栏目</span><strong>{{ reportMeta.sectionCount }} 个</strong></div>
            <div><span>正文字数</span><strong>{{ readingStats.characters }} 字</strong></div>
            <div><span>预计阅读</span><strong>约 {{ readingStats.minutes }} 分钟</strong></div>
          </div>
        </header>

        <p v-if="loadError" class="public-report-load-error">{{ loadError }}</p>
        <div
          v-else
          ref="reportContent"
          class="public-report-prose"
          v-html="reportHtml"
          @pointerover="positionFootnotePreview"
          @focusin="positionFootnotePreview"
        ></div>
      </article>
    </main>

    <ReportOutlineRail
      :scroll-root="reader"
      :content-root="reportContent"
      :content-version="reportHtml"
      report-key="test-10-public-report"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import rawTestReport from 'virtual:knowledgehub-test-report'
import ReportOutlineRail from '../workbench/ReportOutlineRail.vue'
import { renderMarkdown, stripReportMarkdownHeader } from '../utils/viewFormatters.js'

const reader = ref(null)
const reportContent = ref(null)
const themeToggle = ref(null)
const isNight = ref(false)
const loadError = ref('')
const isHostedReport = typeof window !== 'undefined' && /\/reports\/[^/]+\/?$/.test(window.location.pathname)
const reportData = ref({
  title: '校园生活区间汇总',
  groupName: '校园生活',
  reportLabel: '测试 10',
  periodLabel: '2026.07.13 — 07.19',
  dayCount: 7,
  sourceCount: 118,
  citedSourceCount: 117,
  sectionCount: 9,
  markdown: rawTestReport,
})
const archiveHref = computed(() => (isHostedReport ? '../../archive.html' : './archive.html'))
const reportMarkdown = computed(() => stripReportMarkdownHeader(reportData.value.markdown || ''))
const reportHtml = computed(() => linkPublicCitationsToSources(
  renderMarkdown(reportMarkdown.value),
))
const readingStats = computed(() => readingStatsFromMarkdown(reportMarkdown.value))
const reportMeta = computed(() => reportData.value)

function printReport() {
  window.print()
}

onMounted(() => {
  try {
    isNight.value = window.localStorage.getItem('knowledgehub-public-report-theme') === 'night'
  } catch {
    isNight.value = false
  }
  applyTheme()
  void loadHostedReport()
})

async function loadHostedReport() {
  if (!isHostedReport) return
  try {
    const response = await window.fetch('./report.json', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const next = await response.json()
    if (!next || typeof next !== 'object' || !String(next.title || '').trim() || !String(next.markdown || '').trim()) {
      throw new Error('报告数据不完整')
    }
    reportData.value = {
      ...reportData.value,
      ...next,
      dayCount: Number(next.dayCount) || 1,
      sourceCount: Number(next.sourceCount) || 0,
      citedSourceCount: Number(next.citedSourceCount) || 0,
      sectionCount: Number(next.sectionCount) || 0,
    }
    document.title = `${reportData.value.title} · 知识简报`
  } catch {
    loadError.value = '这期公开报告暂时无法加载。'
  }
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

function positionFootnotePreview(event) {
  const target = event?.target
  if (!(target instanceof Element)) return
  const reference = target.closest('.markdown-footnote-ref a')
  const preview = reference?.querySelector('.markdown-footnote-preview')
  if (!(reference instanceof HTMLElement) || !(preview instanceof HTMLElement)) return

  const bounds = reader.value?.getBoundingClientRect() || document.documentElement.getBoundingClientRect()
  const referenceBounds = reference.getBoundingClientRect()
  const previewWidth = preview.getBoundingClientRect().width
  const leftSpace = referenceBounds.right - bounds.left
  const rightSpace = bounds.right - referenceBounds.left
  preview.classList.toggle('is-open-right', leftSpace < previewWidth - 10 && rightSpace > leftSpace)
}

function linkPublicCitationsToSources(html) {
  const documentFragment = new DOMParser().parseFromString(html, 'text/html')
  documentFragment.querySelectorAll('.markdown-footnote-ref a[href^="#fn-"]').forEach((reference) => {
    const sourceId = reference.getAttribute('href')?.slice(1)
    const sourceLink = sourceId ? documentFragment.getElementById(sourceId)?.querySelector('a[href]') : null
    if (!(sourceLink instanceof HTMLAnchorElement)) return
    reference.href = sourceLink.href
    reference.target = '_blank'
    reference.rel = 'noreferrer'
    reference.setAttribute('aria-label', `在新标签页打开来源：${sourceLink.textContent || '原始文章'}`)
  })
  return documentFragment.body.innerHTML
}

function readingStatsFromMarkdown(markdown) {
  const prose = String(markdown || '')
    .replace(
      /(?:^|\n)\[\^([A-Za-z0-9_-]+)\]:[ \t]*([\s\S]*?)(?=\n\[\^[A-Za-z0-9_-]+\]:|\n{2,}(?=#{1,6}\s)|$)/g,
      '',
    )
    .replace(/!?(?:\[[^\]]*\])\((?:<[^>]+>|[^)]+)\)/g, '')
    .replace(/<https?:\/\/[^>]+>|https?:\/\/\S+/g, '')
    .replace(/\[\^[A-Za-z0-9_-]+\]/g, '')
    .replace(/`[^`]*`/g, '')
    .replace(/[#>*_~|\\[\]{}()]/g, '')

  const characters = Array.from(prose).filter((character) => /[\p{L}\p{N}]/u.test(character)).length
  return {
    characters: characters.toLocaleString('zh-CN'),
    minutes: Math.max(1, Math.ceil(characters / 400)),
  }
}
</script>
