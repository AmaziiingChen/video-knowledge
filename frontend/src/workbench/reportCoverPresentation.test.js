import assert from 'node:assert/strict'
import test from 'node:test'

import {
  adjacentReportCover,
  reportCoverIndex,
  reportCoverUrl,
} from './reportCoverPresentation.js'

const history = {
  active_cover_id: 'cover-2',
  covers: [
    { id: 'cover-1', url: '/one.png' },
    { id: 'cover-2', url: '/two.png' },
  ],
}

test('selects the active report cover and adjacent version deterministically', () => {
  assert.equal(reportCoverIndex(history), 1)
  assert.equal(reportCoverUrl(history, '/fallback.png'), '/two.png')
  assert.equal(adjacentReportCover(history, -1)?.id, 'cover-1')
  assert.equal(adjacentReportCover(history, 1), null)
})

test('uses the newest cover or durable content cover when history is incomplete', () => {
  const staleHistory = { active_cover_id: 'missing', covers: history.covers }
  assert.equal(reportCoverIndex(staleHistory), 1)
  assert.equal(reportCoverUrl({ covers: [] }, '/fallback.png'), '/fallback.png')
  assert.equal(adjacentReportCover(staleHistory, -1, { busy: true }), null)
})
