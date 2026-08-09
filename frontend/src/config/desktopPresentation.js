export const DESKTOP_ASR_POLICY = Object.freeze({
  whisper_model: 'small',
  asr_backend: 'auto',
  asr_model_strategy: 'manual',
  asr_short_video_model: 'base',
  asr_long_video_model: 'small',
  asr_beam_size: 1,
  asr_vad_filter: true,
  asr_fallback_enabled: false,
})

export const appearanceThemes = [
  { value: 'paper', label: '清纸', description: '橄榄与暖白，适合日常收集', accent: '#6F8D3E', background: '#FDF6E3', foreground: '#2F2A1F' },
  { value: 'pure', label: '素白', description: '近白与石墨，最大限度减少视觉噪声', accent: '#66756B', background: '#FAFAF9', foreground: '#252825' },
  { value: 'typora', label: 'Typora', description: '极简 Markdown 文档感，适合连续写作', accent: '#428BCA', background: '#FFFFFF', foreground: '#333333' },
  { value: 'warm', label: '暖阅', description: '暖棕与宋体，适合长文深读', accent: '#9E5D5A', background: '#FAF4ED', foreground: '#575279' },
  { value: 'absolutely', label: '羊皮纸', description: '陶土强调，保留纸张质感', accent: '#CC7D5E', background: '#F9F9F7', foreground: '#2D2D2B' },
  { value: 'proof', label: '校稿', description: '低饱和绿，适合审阅与整理', accent: '#3D755D', background: '#F5F3ED', foreground: '#2F312D' },
  { value: 'focus', label: '留白', description: '中性留白，弱化工作台噪声', accent: '#536B55', background: '#F5F6F2', foreground: '#28302B' },
  { value: 'notion', label: '简记', description: '克制白底，适合轻量笔记', accent: '#3183D8', background: '#FFFFFF', foreground: '#37352F' },
  { value: 'github', label: '晨雾', description: '清冷白灰，信息层级利落', accent: '#0969DA', background: '#FFFFFF', foreground: '#1F2328' },
  { value: 'rose-pine', label: '玫瑰松', description: '雾粉与灰紫，温和但有辨识度', accent: '#D7827E', background: '#FAF4ED', foreground: '#575279' },
  { value: 'catppuccin', label: '雾紫', description: '柔和紫灰，适合低对比写作', accent: '#8839EF', background: '#EFF1F5', foreground: '#4C4F69' },
  { value: 'codex', label: '蓝图', description: '明快蓝色，适合检索与结构化工作', accent: '#0169CC', background: '#FFFFFF', foreground: '#0D0D0D' },
  { value: 'raycast', label: '朱砂', description: '高辨识暖红，用于快速操作', accent: '#E64949', background: '#FFFFFF', foreground: '#030303' },
  { value: 'night', label: '夜读', description: '墨绿与暖白，适合低光长读', accent: '#9AB970', background: '#1D211C', foreground: '#E3E5D8' },
  { value: 'graphite', label: '石墨', description: '深灰而非纯黑，适合夜间专注', accent: '#B9C3B9', background: '#1C1D1C', foreground: '#E8EBE7' },
  { value: 'nord', label: '北境', description: '冷灰蓝深色，适合夜间专注', accent: '#88C0D0', background: '#2E3440', foreground: '#ECEFF4' },
]

export function normalizeAppearanceTheme(theme) {
  const legacyThemes = { everforest: 'paper', one: 'codex' }
  return appearanceThemes.some((item) => item.value === theme)
    ? theme
    : legacyThemes[theme] || 'paper'
}
