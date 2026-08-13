import test from 'node:test'
import assert from 'node:assert/strict'

import { composeQaQuestion, insertQaShortcutToken } from './qaPromptComposer.js'

const shortcuts = [
  { name: '总结', template: '提炼核心观点' },
  { name: '质疑', template: '检查证据与推断' },
]

test('inserts a shortcut token and replaces only the unfinished trailing token', () => {
  assert.equal(insertQaShortcutToken('', ' 总结 '), '@总结 ')
  assert.equal(insertQaShortcutToken('请分析', '质疑'), '请分析 @质疑 ')
  assert.equal(insertQaShortcutToken('请分析 @总', '总结'), '请分析 @总结 ')
  assert.equal(insertQaShortcutToken('请分析 @总结 后续', '质疑'), '请分析 @总结 后续 @质疑 ')
  assert.equal(insertQaShortcutToken('保持原文', '  '), null)
})

test('expands explicit shortcuts while retaining unknown tokens as user text', () => {
  assert.deepEqual(
    composeQaQuestion('@总结 请关注风险 @未知', shortcuts),
    {
      prompt: [
        '已选择的追问方式：\n@总结\n提炼核心观点',
        '用户补充：\n请关注风险 @未知',
      ].join('\n\n'),
      autoShortcutName: '',
    },
  )
})

test('applies deterministic automatic recognition only when enabled', () => {
  assert.deepEqual(
    composeQaQuestion('帮我总结一下', shortcuts),
    {
      prompt: [
        '已选择的追问方式：\n@总结\n提炼核心观点',
        '用户补充：\n帮我总结一下',
      ].join('\n\n'),
      autoShortcutName: '总结',
    },
  )
  assert.deepEqual(
    composeQaQuestion('帮我总结一下', shortcuts, { autoRecognitionEnabled: false }),
    { prompt: '用户补充：\n帮我总结一下', autoShortcutName: '' },
  )
})

test('ignores incomplete templates and leaves ordinary questions unchanged', () => {
  assert.deepEqual(
    composeQaQuestion('普通问题', [
      { name: '', template: '无名称' },
      { name: '空模板', template: '   ' },
    ]),
    { prompt: '用户补充：\n普通问题', autoShortcutName: '' },
  )
})
