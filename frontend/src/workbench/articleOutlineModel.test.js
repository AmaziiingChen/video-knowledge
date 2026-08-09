import assert from 'node:assert/strict'
import test from 'node:test'
import { articleOutlineHeadingSelector, createArticleOutlineModel } from './articleOutlineModel.js'

function heading(tagName = 'H2', inside = false) {
  return { tagName, closest: () => inside ? {} : null }
}

test('admits meaningful article headings but excludes reader duplication and capture noise', () => {
  const model = createArticleOutlineModel({ activeArticleTitle: () => '一份完整 标题' })
  assert.equal(articleOutlineHeadingSelector, 'h1, h2, h3, h4, .article-section-heading')
  assert.equal(model.isArticleOutlineHeading(heading(), '一个有效章节'), true)
  assert.equal(model.isArticleOutlineHeading(heading(), ' 一份完整\n标题 '), false)
  assert.equal(model.isArticleOutlineHeading(heading(), '原文内容'), false)
  assert.equal(model.isArticleOutlineHeading(heading(), '图片文字 12'), false)
  assert.equal(model.isArticleOutlineHeading(heading('H2', true), '图片中的章节'), false)
})

test('keeps outline lengths bounded and maps visual heading levels deterministically', () => {
  const model = createArticleOutlineModel({ activeArticleTitle: () => '' })
  assert.equal(model.isArticleOutlineHeading(heading(), '单'), false)
  assert.equal(model.isArticleOutlineHeading(heading(), '一'.repeat(85)), false)
  assert.equal(model.articleOutlineHeadingLevel(heading('h1')), 2)
  assert.equal(model.articleOutlineHeadingLevel(heading('H2')), 2)
  assert.equal(model.articleOutlineHeadingLevel(heading('h3')), 3)
  assert.equal(model.articleOutlineHeadingLevel(heading('div')), 3)
})
