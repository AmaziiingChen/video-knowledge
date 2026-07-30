<script>
import { defineComponent, h } from 'vue'
import { ElTooltip } from 'element-plus'

/**
 * The one entry point for the application's hover hints.
 *
 * Existing feature code can keep using <el-tooltip>; main.js registers this
 * wrapper under that name. Explicit per-call props still take precedence for
 * the few content-specific cases (for example, a longer error message).
 */
export default defineComponent({
  name: 'AppTooltip',
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => {
      const tooltipAttrs = { ...attrs }
      const content = tooltipAttrs.content
      const requestedPopperClass = tooltipAttrs.popperClass || tooltipAttrs['popper-class']
      const requestedTransition = tooltipAttrs.transition
      delete tooltipAttrs.content
      delete tooltipAttrs.popperClass
      delete tooltipAttrs['popper-class']
      delete tooltipAttrs.transition
      const isSpecialized = Boolean(requestedPopperClass)

      // Menus and long-form diagnostic poppers retain their own surface. Every
      // ordinary hover hint gets the MicroFlow-style inner bubble below.
      if (isSpecialized) {
        return h(ElTooltip, {
          showAfter: 100,
          hideAfter: 60,
          transition: requestedTransition || 'kh-tooltip-pop',
          popperClass: requestedPopperClass,
          content,
          ...tooltipAttrs
        }, slots)
      }

      return h(ElTooltip, {
        showAfter: 100,
        hideAfter: 60,
        transition: 'kh-tooltip-pop',
        popperClass: 'app-tooltip-popper',
        ...tooltipAttrs
      }, {
        default: slots.default,
        content: () => h('span', { class: 'app-tooltip-bubble' }, slots.content ? slots.content() : content)
      })
    }
  }
})
</script>
