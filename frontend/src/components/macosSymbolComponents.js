import { defineComponent, h } from 'vue'
import SvgMaskIcon from './SvgMaskIcon.vue'

function symbolComponent(componentName, symbolName) {
  return defineComponent({
    name: componentName,
    inheritAttrs: false,
    setup(_, { attrs }) {
      return () => h(SvgMaskIcon, {
        ...attrs,
        src: symbolName,
        size: Number(attrs.size) || 16,
      })
    },
  })
}

export const Aim = symbolComponent('MacosAimIcon', 'dot.scope')
export const ArrowDown = symbolComponent('MacosArrowDownIcon', 'arrow.down')
export const ArrowLeft = symbolComponent('MacosArrowLeftIcon', 'arrow.left')
export const ArrowRight = symbolComponent('MacosArrowRightIcon', 'arrow.right')
export const ArrowUp = symbolComponent('MacosArrowUpIcon', 'arrow.up')
export const Check = symbolComponent('MacosCheckIcon', 'checkmark')
export const Close = symbolComponent('MacosCloseIcon', 'xmark')
export const Delete = symbolComponent('MacosDeleteIcon', 'trash')
export const Filter = symbolComponent('MacosFilterIcon', 'filter')
export const IconX = Close
export const Minus = symbolComponent('MacosMinusIcon', 'minus')
export const MoreFilled = symbolComponent('MacosMoreIcon', 'ellipsis')
export const Plus = symbolComponent('MacosPlusIcon', 'plus')
export const Refresh = symbolComponent('MacosRefreshIcon', 'arrow.clockwise')
export const Search = symbolComponent('MacosSearchIcon', 'magnifyingglass')
