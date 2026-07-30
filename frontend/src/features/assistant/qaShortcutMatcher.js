const RULES = [
  { names: ['质疑'], pattern: /真的吗|真的是|靠谱吗|可靠(?:吗|性)|可信(?:吗|度)|质疑|漏洞|夸大|过度推断|是否正确|是否可信/u },
  { names: ['反例'], pattern: /反例|边界(?:条件)?|局限|失效|不适用|例外|替代解释|误用/u },
  { names: ['术语'], pattern: /术语|概念|名词|什么意思|是什么(?:意思)?|解释一下/u },
  { names: ['行动'], pattern: /怎么做|怎么办|行动(?:建议)?|实践(?:方案)?|执行(?:步骤)?|清单/u },
  { names: ['举例'], pattern: /举个?(?:例子|例)|示例|案例/u },
  { names: ['关联'], pattern: /关联|联系|相同(?:点)?|不同(?:点)?|区别|对比/u },
  { names: ['拓展'], pattern: /拓展|延伸|进一步(?:了解|学习)?|背景|原理/u },
  { names: ['总结'], pattern: /总结|概括|梳理|提炼|核心(?:内容|观点)|主要(?:内容|观点)|讲了什么/u },
  { names: ['问我'], pattern: /问我|考考我|出题/u }
]

function availableShortcuts(templates) {
  return (Array.isArray(templates) ? templates : [])
    .map((template) => ({
      name: String(template?.name || '').trim(),
      template: String(template?.template || '').trim()
    }))
    .filter((template) => template.name && template.template)
}

/**
 * Resolve only an intentionally small set of Chinese intent phrases locally.
 * This is deterministic and never sends the raw question to another service.
 */
export function matchQaShortcut(question, templates) {
  const input = String(question || '').trim()
  if (!input || input.includes('@')) return null

  const byName = new Map(availableShortcuts(templates).map((shortcut) => [shortcut.name, shortcut]))
  for (const rule of RULES) {
    if (!rule.pattern.test(input)) continue
    const matched = rule.names.map((name) => byName.get(name)).find(Boolean)
    if (matched) return matched
  }
  return null
}
