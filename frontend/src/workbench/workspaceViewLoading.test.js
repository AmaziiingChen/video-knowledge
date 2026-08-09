import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isSinglePaneWorkspaceView,
} from './workspaceViewLoading.js'

test('all management workspaces, including RSS, use the single-pane layout', () => {
  for (const view of ['wechat', 'campus', 'creator', 'rss', 'reports']) {
    assert.equal(isSinglePaneWorkspaceView(view), true)
  }
  assert.equal(isSinglePaneWorkspaceView('library'), false)
  assert.equal(isSinglePaneWorkspaceView('knowledge'), false)
})
