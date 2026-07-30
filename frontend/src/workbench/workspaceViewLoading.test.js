import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isSinglePaneWorkspaceView,
  preloadWorkspaceViewModules,
} from './workspaceViewLoading.js'

test('all management workspaces, including RSS, use the single-pane layout', () => {
  for (const view of ['wechat', 'campus', 'creator', 'rss', 'reports']) {
    assert.equal(isSinglePaneWorkspaceView(view), true)
  }
  assert.equal(isSinglePaneWorkspaceView('library'), false)
  assert.equal(isSinglePaneWorkspaceView('knowledge'), false)
})

test('preloads each workspace module once without letting one failure cancel the rest', async () => {
  let successfulLoads = 0
  const successfulLoader = async () => {
    successfulLoads += 1
    return { default: {} }
  }
  const failedLoader = async () => {
    throw new Error('missing chunk')
  }

  const results = await preloadWorkspaceViewModules([
    successfulLoader,
    successfulLoader,
    failedLoader,
  ])

  assert.equal(successfulLoads, 1)
  assert.deepEqual(results.map((result) => result.status), ['fulfilled', 'rejected'])
})
