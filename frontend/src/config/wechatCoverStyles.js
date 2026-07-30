import transparentWatercolorPreview from '../assets/wechat-cover-styles/transparent-watercolor.jpg'
import twilightPainterlyPreview from '../assets/wechat-cover-styles/twilight-painterly.jpg'
import duotoneRisographPreview from '../assets/wechat-cover-styles/duotone-risograph.jpg'
import modernGeometricPreview from '../assets/wechat-cover-styles/modern-geometric.jpg'
import editorialCollectorPreview from '../assets/wechat-cover-styles/editorial-collector.jpg'
import orientalInkPreview from '../assets/wechat-cover-styles/oriental-ink.jpg'

export const WECHAT_COVER_STYLE_OPTIONS = Object.freeze([
  {
    value: 'minimal_zine',
    label: 'Minimal Zine',
    description: '纸面留白、微型排字与克制的印刷颗粒',
    preview: '',
    previewAlt: 'Minimal Zine 横版纸面海报风格示意'
  },
  {
    value: 'transparent_watercolor',
    label: '雨幕透明水彩',
    description: '透明薄涂、纸张纹理与安静的空气感',
    preview: transparentWatercolorPreview,
    previewAlt: '雨幕透明水彩横版风格参考'
  },
  {
    value: 'twilight_painterly',
    label: '暮色氛围绘画',
    description: '以光线、色彩和笔触承载主题情绪',
    preview: twilightPainterlyPreview,
    previewAlt: '暮色氛围绘画横版风格参考'
  },
  {
    value: 'duotone_risograph',
    label: '两色孔版印刷',
    description: '双色套印、半调网点与独立杂志质感',
    preview: duotoneRisographPreview,
    previewAlt: '两色孔版印刷横版风格参考',
    previewPosition: 'center 58%'
  },
  {
    value: 'modern_geometric',
    label: '现代几何平涂',
    description: '大色块、几何秩序与成熟的现代平面感',
    preview: modernGeometricPreview,
    previewAlt: '现代几何平涂横版风格参考'
  },
  {
    value: 'editorial_collector',
    label: '编辑型收藏海报',
    description: '用一条视觉线索组织克制的编辑叙事',
    preview: editorialCollectorPreview,
    previewAlt: '编辑型收藏海报横版风格参考',
    previewPosition: 'center 28%'
  },
  {
    value: 'oriental_ink',
    label: '东方水墨留白',
    description: '墨色层次、雾气与横向手卷式留白',
    preview: orientalInkPreview,
    previewAlt: '东方水墨留白横版风格参考',
    previewPosition: 'center 45%'
  }
])
