import { matchQaShortcut } from './qaShortcutMatcher.js'

export function insertQaShortcutToken(currentValue, name) {
  const shortcutName = String(name || '').trim()
  if (!shortcutName) return null
  const token = `@${shortcutName}`
  const current = currentValue || ''
  return /(?:^|\s)@[^\s@]*$/u.test(current)
    ? current.replace(/@[^\s@]*$/u, `${token} `)
    : `${current}${current && !/\s$/u.test(current) ? ' ' : ''}${token} `
}

export function composeQaQuestion(
  draftQuestion,
  templates,
  {
    autoRecognitionEnabled = true,
    matchShortcut = matchQaShortcut,
  } = {},
) {
  const byName = new Map(
    templates
      .filter((template) => template?.name?.trim() && template?.template?.trim())
      .map((template) => [template.name.trim(), template.template.trim()]),
  )
  const parts = []
  const shortcutBodies = []
  const remainingText = draftQuestion.replace(/@([^\s@]+)/gu, (token, name) => {
    const template = byName.get(name)
    if (!template) return token
    shortcutBodies.push(`@${name}\n${template}`)
    return ''
  }).replace(/\s{2,}/gu, ' ').trim()

  if (shortcutBodies.length) {
    parts.push(`已选择的追问方式：\n${shortcutBodies.join('\n\n')}`)
  }
  if (remainingText) {
    parts.push(`用户补充：\n${remainingText}`)
  }
  if (shortcutBodies.length) {
    return {
      prompt: parts.join('\n\n'),
      autoShortcutName: '',
    }
  }

  const autoShortcut = autoRecognitionEnabled
    ? matchShortcut(draftQuestion, templates)
    : null
  if (autoShortcut) {
    return {
      prompt: [
        `已选择的追问方式：\n@${autoShortcut.name}\n${autoShortcut.template}`,
        `用户补充：\n${draftQuestion}`,
      ].join('\n\n'),
      autoShortcutName: autoShortcut.name,
    }
  }
  return {
    prompt: parts.join('\n\n') || draftQuestion,
    autoShortcutName: '',
  }
}
